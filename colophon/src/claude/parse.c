#define _DARWIN_C_SOURCE
#include "parse.h"
#include "compose.h"
#include "metadata.h"
#include "reconcile.h"
#include "parse/record.h"
#include "out/jsonw.h"
#include "corpus/subagents.h"
#include "corpus/titles.h"
#include "corpus/turnstatus.h"
#include "corpus/provider.h"
#include "util/time.h"
#include "testing/hooks.h"
#include <stdalign.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define TRY(x)                                                                 \
  do {                                                                         \
    Err e_ = (x);                                                              \
    if (e_.code)                                                               \
      return e_;                                                               \
  } while (0)
static yyjson_val *get(yyjson_val *v, const char *key) {
  return obj_get_last(v, (Str){key, (uint32_t)strlen(key)});
}
static Str text(yyjson_val *v) {
  return yyjson_is_str(v)
             ? (Str){yyjson_get_str(v), (uint32_t)yyjson_get_len(v)}
             : (Str){0};
}
static Err copy(Arena *a, Str s, Str *out) {
  if (!s.p) {
    *out = (Str){0};
    return ERR_SUCCESS;
  }
  return str_copy(a, s, out);
}
static Err alloc(Arena *a, size_t n, size_t size, size_t alignment,
                 void **out) {
  if (size && n > SIZE_MAX / size)
    return err_make(ERR_NOMEM, "Claude allocation overflow");
  TRY(arena_alloc(a, n * size, alignment, out));
  memset(*out, 0, n * size);
  return ERR_SUCCESS;
}
bool claude_known_type(Str kind) {
  const char *names[] = {"user",
                         "assistant",
                         "system",
                         "progress",
                         "summary",
                         "custom-title",
                         "ai-title",
                         "file-history-snapshot",
                         "queue-operation",
                         "last-prompt",
                         "pr-link"};
  for (size_t i = 0; i < sizeof names / sizeof *names; i++)
    if (str_equal(kind, (Str){names[i], (uint32_t)strlen(names[i])}))
      return true;
  return false;
}
typedef struct {
  ClaudeRecord *r;
  Omap shell_ids;
  bool interrupted, api_error, completed;
  size_t capacity;
} Parse;
static void finish(Parse *p) {
  if (!p->r->turn_count)
    return;
  TurnFact *t = p->r->turns[p->r->turn_count - 1];
  t->end_kind = p->interrupted ? STR_LIT("interrupted")
                : p->api_error ? STR_LIT("aborted")
                : p->completed ? STR_LIT("completed")
                               : STR_LIT("open");
  if (!str_equal(t->end_kind, STR_LIT("open")))
    t->end_ms = t->last_ms;
}
static bool prefix(Str s, const char *tag) {
  size_t n = strlen(tag);
  return s.n >= n && !memcmp(s.p, tag, n);
}
static Err content(Arena *a, yyjson_val *v, Str *out, uint64_t *images) {
  *out = (Str){0};
  *images = 0;
  if (yyjson_is_str(v))
    return copy(a, text(v), out);
  size_t n = 0, i, max;
  yyjson_val *q;
  yyjson_arr_foreach(v, i, max, q) {
    if (str_equal(text(get(q, "type")), STR_LIT("text")))
      n += text(get(q, "text")).n + 1;
    else if (str_equal(text(get(q, "type")), STR_LIT("image")))
      (*images)++;
  }
  if (!n)
    return ERR_SUCCESS;
  char *bytes;
  TRY(arena_alloc(a, n + 1, 1, (void **)&bytes));
  size_t at = 0;
  yyjson_arr_foreach(v, i, max, q) {
    if (!str_equal(text(get(q, "type")), STR_LIT("text")))
      continue;
    Str s = text(get(q, "text"));
    if (!s.p)
      continue;
    if (at)
      bytes[at++] = '\n';
    memcpy(bytes + at, s.p, s.n);
    at += s.n;
  }
  bytes[at] = 0;
  *out = (Str){bytes, (uint32_t)at};
  return ERR_SUCCESS;
}
static Err count(Arena *a, Omap *m, Str key) {
  __int128 *v = omap_get(m, key);
  if (v) {
    (*v)++;
    return ERR_SUCCESS;
  }
  TRY(alloc(a, 1, sizeof *v, alignof(__int128), (void **)&v));
  *v = 1;
  return omap_put(m, key, v);
}
Err claude_tool_count(Arena *a, CorpusTools *tools, Str name, bool failed) {
  if (str_equal(name, STR_LIT("Bash"))) {
    tools->shell++;
    tools->shell_failed += failed;
  } else if (str_equal(name, STR_LIT("Edit")) || str_equal(name, STR_LIT("Write")) ||
             str_equal(name, STR_LIT("MultiEdit")) || str_equal(name, STR_LIT("NotebookEdit")))
    tools->file_edits++;
  else if (str_equal(name, STR_LIT("WebFetch")) || str_equal(name, STR_LIT("WebSearch")))
    tools->web++;
  else if (prefix(name, "mcp__")) {
    Str server = {name.p + 5, name.n - 5};
    const char *end = memmem(server.p, server.n, "__", 2);
    if (end && end > server.p) {
      server.n = (uint32_t)(end - server.p);
      TRY(count(a, &tools->mcp, server));
    } else TRY(count(a, &tools->other, name));
  } else TRY(count(a, &tools->other, name));
  return ERR_SUCCESS;
}
static Err on_record(void *context, const ReaderRecord *row) {
  Parse *p = context;
  ClaudeRecord *r = p->r;
  yyjson_val *v = row->record, *message = get(v, "message"),
             *body = get(message, "content");
  Str type = text(get(v, "type"));
  if (str_equal(type, STR_LIT("custom-title"))) {
    Str title = text(get(v, "customTitle"));
    TRY(copy(&r->arena, title, &r->custom_title));
  } else if (str_equal(type, STR_LIT("ai-title"))) {
    Str title = text(get(v, "aiTitle"));
    TRY(copy(&r->arena, title, &r->ai_title));
  }
  MaybeMs at = {0};
  Str stamp = text(get(v, "timestamp"));
  at.present = time_parse_rfc3339(stamp, "claude.timestamp", &at.value);
  if (at.present) {
    if (!r->first_ms.present || at.value < r->first_ms.value)
      r->first_ms = at;
    if (!r->last_ms.present || at.value > r->last_ms.value)
      r->last_ms = at;
  }
  const char *fields[] = {"cwd", "gitBranch"};
  JScalar *targets[] = {&r->meta.cwd, &r->meta.branch};
  for (size_t i = 0; i < 2; i++) {
    Str s = text(get(v, fields[i]));
    if (s.n) {
      targets[i]->kind = JS_STRING;
      TRY(copy(&r->arena, s, &targets[i]->value.s));
    }
  }
  Str alias = text(get(v, "sessionId"));
  if (alias.n && !r->parent_session.p) {
    bool seen = false;
    for (size_t i = 0; i < r->aliases.count; i++)
      seen |= str_equal(alias, r->aliases.items[i]);
    if (!seen) {
      Str s;
      TRY(copy(&r->arena, alias, &s));
      TRY(corpus_strings_add(&r->arena, &r->aliases, s));
    }
  }
  Str request = {0}, kind = STR_LIT("text");
  uint64_t images = 0;
  bool prompt = false;
  if (str_equal(type, STR_LIT("user")) && !yyjson_is_true(get(v, "isMeta")) &&
      !yyjson_is_true(get(v, "isCompactSummary"))) {
    yyjson_val *first = yyjson_arr_get_first(body);
    Str first_type = text(get(first, "type"));
    if (yyjson_is_str(body) || str_equal(first_type, STR_LIT("text")) ||
        str_equal(first_type, STR_LIT("image"))) {
      TRY(content(&r->arena, body, &request, &images));
      Str leading = str_trim(request, true);
      if (prefix(leading, "[Request interrupted by user"))
        p->interrupted = true;
      else if (!prefix(leading, "<task-notification>") &&
               !prefix(leading, "<local-command-stdout>") &&
               !prefix(leading, "<system-reminder>")) {
        prompt = true;
        if (prefix(leading, "<command-name>") ||
            prefix(leading, "<command-message>") ||
            prefix(leading, "<bash-input>"))
          kind = STR_LIT("command");
      }
    }
  }
  if (prompt) {
    finish(p);
    p->interrupted = p->api_error = p->completed = false;
    if (r->turn_count == p->capacity) {
      size_t n = p->capacity ? p->capacity * 2 : 8;
      void *next;
#define GROW(field, type)                                                      \
  do {                                                                         \
    TRY(alloc(&r->arena, n, sizeof *r->field, alignof(type), &next));          \
    if (r->turn_count)                                                         \
      memcpy(next, r->field, r->turn_count * sizeof *r->field);                \
    r->field = next;                                                           \
  } while (0)
      GROW(turns, TurnFact *);
      GROW(requests, Request);
      GROW(answers, Str);
      GROW(answer_ms, MaybeMs);
      GROW(tools, CorpusTools);
      p->capacity = n;
#undef GROW
    }
    size_t i = r->turn_count;
    TurnFact *t;
    if (cp_fault("claude_turn_alloc"))
      return err_make(ERR_NOMEM, "Claude turn allocation failed");
    TRY(alloc(&r->arena, 1, sizeof *t, alignof(TurnFact), (void **)&t));
    char id[48];
    int n = snprintf(id, sizeof id, "claude-turn-%zu", i + 1);
    TRY(copy(&r->arena, (Str){id, (uint32_t)n}, &t->key));
    TRY(copy(&r->arena, text(get(v, "uuid")), &t->turn_id));
    t->start_ms = at;
    t->has_start_rec = true;
    t->start_rec = row->rec;
    r->requests[i] =
        (Request){.at_ms = at, .text = request, .kind = kind, .images = images};
    r->turns[i] = t;
    r->turn_count++;
  }
  if (!r->turn_count)
    return ERR_SUCCESS;
  size_t turn = r->turn_count - 1;
  TurnFact *t = r->turns[turn];
  if (at.present)
    t->last_ms = at;
  p->api_error = str_equal(type, STR_LIT("system")) &&
                 str_equal(text(get(v, "subtype")), STR_LIT("api_error"));
  if (str_equal(type, STR_LIT("assistant"))) {
    yyjson_val *stop = get(message, "stop_reason");
    p->completed = stop && !yyjson_is_null(stop) &&
                   !str_equal(text(stop), STR_LIT("tool_use"));
    uint64_t ignored;
    Str answer;
    TRY(content(&r->arena, body, &answer, &ignored));
    if (answer.n) {
      r->answers[turn] = answer;
      r->answer_ms[turn] = at;
    }
  }
  size_t i, max;
  yyjson_val *q;
  yyjson_arr_foreach(body, i, max, q) {
    Str block = text(get(q, "type"));
    if (str_equal(block, STR_LIT("tool_use"))) {
      Str name = text(get(q, "name")), id = text(get(q, "id"));
      if (metadata_text(id)) {
        Str owned, *key;
        TRY(copy(&r->arena, id, &owned));
        TRY(alloc(&r->arena, 1, sizeof *key, alignof(Str), (void **)&key));
        *key = t->key;
        TRY(omap_put(&r->tool_turns, owned, key));
      }
      ClaudeToolFact fact = {.turn = t->key, .identified = metadata_text(id)};
      TRY(copy(&r->arena, name, &fact.name));
      if (fact.identified) TRY(copy(&r->arena, id, &fact.id));
      else {
        /* Anonymous blocks match by record identity, or timestamp/name/block
         * occurrence when the source supplies no identity. */
        Str event = text(get(v, "uuid"));
        if (!event.n) event = text(get(message, "id"));
        JsonWriter w = {0};
        jsonw_raw(&w, "["); jsonw_string(&w, event.n ? event : stamp);
        jsonw_raw(&w, ","); jsonw_string(&w, name);
        jsonw_raw(&w, ","); jsonw_i64(&w, (int64_t)i); jsonw_raw(&w, "]");
        if (!event.n && !w.error.code) {
          size_t occurrence = 0, base = w.length;
          for (size_t k = 0; k < r->tool_count; k++) {
            const ClaudeToolFact *old = &r->tool_facts[k];
            if (!old->identified && str_equal(old->turn, t->key) &&
                old->id.n > base && !memcmp(old->id.p, w.data, base) && old->id.p[base] == ':')
              occurrence++;
          }
          jsonw_raw(&w, ":"); jsonw_i64(&w, (int64_t)occurrence);
        }
        Err e = w.error;
        if (!e.code) e = copy(&r->arena, (Str){w.data, (uint32_t)w.length}, &fact.id);
        jsonw_free(&w); TRY(e);
      }
      TRY(record_append(&r->arena, (void **)&r->tool_facts, &r->tool_count,
                        &r->tool_capacity, sizeof fact, &fact));
      TRY(claude_tool_count(&r->arena, &r->tools[turn], name, false));
      if (str_equal(name, STR_LIT("Bash"))) {
        if (id.n)
          TRY(omap_put(&p->shell_ids, id, (void *)(uintptr_t)(turn + 1)));
      }
    } else if (str_equal(block, STR_LIT("tool_result")) &&
               yyjson_is_true(get(q, "is_error"))) {
      size_t owner = (size_t)(uintptr_t)omap_get(&p->shell_ids,
                                                 text(get(q, "tool_use_id")));
      if (owner) {
        r->tools[owner - 1].shell_failed++;
        Str failed_id = text(get(q, "tool_use_id"));
        for (size_t k = 0; k < r->tool_count; k++)
          if (r->tool_facts[k].identified && str_equal(r->tool_facts[k].id, failed_id))
            r->tool_facts[k].failed = true;
        TRY(omap_put(&p->shell_ids, text(get(q, "tool_use_id")), NULL));
      }
    }
  }
  return ERR_SUCCESS;
}
static Err on_raw(void *context, const ReaderRawLine *line) {
  Parse *p=context;
  Str turn=p->r->turn_count?p->r->turns[p->r->turn_count-1]->key:(Str){0};
  return claude_usage_line(p->r,line,turn);
}
Err claude_parse(const DiscoveredLog *key, Str root, Str config,
                 ClaudeRecord *out) {
  *out = (ClaudeRecord){.key = *key, .reader_facts = true};
  TRY(copy(&out->arena, key->path, &out->key.path));
  TRY(copy(&out->arena, root, &out->search_root));
  TRY(copy(&out->arena, config, &out->config_dir));
  Str id = title_path_name(key->path, true);
  const char *base = id.p;
  if (prefix(id, "agent-") && base > key->path.p) {
    Str parent = {key->path.p, (uint32_t)(base - key->path.p - 1)};
    Str dirname = title_path_name(parent, false);
    if (str_equal(dirname, STR_LIT("subagents")) && parent.n > dirname.n) {
      parent.n -= dirname.n + 1;
      Str session = title_path_name(parent, false);
      TRY(copy(&out->arena, session, &out->parent_session));
      out->config_dir = (Str){0};
      char *combined;
      TRY(arena_alloc(&out->arena, (size_t)session.n + id.n + 2, 1,
                      (void **)&combined));
      memcpy(combined, session.p, session.n);
      combined[session.n] = '/';
      memcpy(combined + session.n + 1, id.p, id.n);
      combined[session.n + id.n + 1] = 0;
      id = (Str){combined, session.n + id.n + 1};
    }
  }
  TRY(copy(&out->arena, id, &out->id));
  TRY(claude_sidecar_load(out));
  Parse p = {.r = out};
  ReaderCallbacks cb = {
      .context = &p, .known_type = claude_known_type, .record = on_record,
      .raw_line = on_raw};
  Err e = reader_read_log(&out->key, &cb, &out->reader);
  if (!e.code)
    finish(&p);
  omap_destroy(&p.shell_ids);
  return e;
}
void claude_record_destroy(ClaudeRecord *r) {
  omap_destroy(&r->tool_turns);
  omap_destroy(&r->canonical_turns);
  omap_destroy(&r->rows_dropped);
  for (size_t i = 0; r->tools && i < r->turn_count; i++) {
    omap_destroy(&r->tools[i].mcp);
    omap_destroy(&r->tools[i].other);
  }
  reader_result_destroy(&r->reader);
  arena_destroy(&r->arena);
  *r = (ClaudeRecord){0};
}
static Err add_records(ClaudeRecord *records, size_t count, int64_t snapshot,
                       Corpus *c,
                       const Omap *codex_ids) {
  for (size_t i = 0; i < count; i++) {
    ClaudeRecord *r = &records[i];
    SessionModel *s = omap_get(&c->sessions, r->id);
    if (omap_get(codex_ids, r->id) || (s && s->provider == PROVIDER_CODEX)) {
      continue;
    }
    if (s) {
      if(!r->retained)s->flags &= ~F_RETAINED;
      if (r->config_dir.p && !r->parent_session.p && (!r->retained || (s->flags & F_RETAINED)) &&
          (!s->resume_config_dir.p ||
           str_compare(r->config_dir, s->resume_config_dir) < 0))
        s->resume_config_dir = r->config_dir;
      continue; /* Same stem copies share one session; rows remain available to
                   the usage composer. */
    }
    TRY(alloc(&c->arena, 1, sizeof *s, alignof(SessionModel), (void **)&s));
    *s = (SessionModel){.provider = PROVIDER_CLAUDE,
                        .id = r->id,
                        .key = r->id,
                        .identity = r->id,
                        .log_path = r->key.path,
                        .meta = r->meta,
                        .kind = STR_LIT("session"),
                        .is_subagent = r->parent_session.p != NULL,
                        .has_link = r->parent_session.p != NULL,
                        .resume_config_dir = r->config_dir,
                        .start_ms = r->first_ms,
                        .end_ms = r->last_ms};
    if(r->retained)s->flags|=F_RETAINED;
    int64_t mtime = r->key.mtime_ns / 1000000;
    TRY(turn_models(&c->arena, r->turns, r->turn_count, false, mtime, snapshot,
                    &s->turns));
    s->turn_count = r->turn_count;
    s->requests = r->requests;
    s->request_count = r->turn_count;
    TRY(alloc(&c->arena, r->turn_count, sizeof *s->ordered_requests,
              alignof(Request *), (void **)&s->ordered_requests));
    for (size_t j = 0; j < r->turn_count; j++) {
      TurnModel *t = &s->turns[j];
      size_t k = 0;
      while (k < r->turn_count && !str_equal(r->turns[k]->key, t->id))
        k++;
      if (k == r->turn_count)
        return err_make(ERR_INVALID, "Claude turn identity missing");
      t->request_count = 1;
      TRY(alloc(&c->arena, 1, sizeof *t->requests, alignof(Request *),
                (void **)&t->requests));
      t->requests[0] = &r->requests[k];
      t->final_answer = r->answers[k];
      s->ordered_requests[j] = t->requests[0];
      TRY(corpus_turn_tools_adopt(&c->arena, s, t, &r->tools[k]));
      corpus_status_flags(s, t->status);
    }
    s->title_full = r->turn_count ? r->requests[0].text : r->id;
    s->title_source =
        r->turn_count ? STR_LIT("first_request") : STR_LIT("filename");
    if (metadata_text(r->ai_title)) {
      s->title_full = r->ai_title;
      s->title_source = STR_LIT("ai_title");
    }
    if (metadata_text(r->custom_title)) {
      s->title_full = r->custom_title;
      s->title_source = STR_LIT("custom_title");
    }
    TRY(title_display(&c->arena, s->title_full, &s->title));
    TRY(corpus_session_idle(&c->arena, s));
    TRY(omap_put(&c->sessions, s->id, s));
  }
  return ERR_SUCCESS;
}
static Err link_records(ClaudeRecord *records, size_t count, Corpus *c) {
  Omap identified = {0}, origins = {0};
  Err e = ERR_SUCCESS;
  for (size_t i = 0; i < count; i++) {
    ClaudeRecord *r = &records[i];
    SessionModel *s = omap_get(&c->sessions, r->id);
    if (!s || s->provider != PROVIDER_CLAUDE || omap_get(&identified, s->id))
      continue;
    e = omap_put(&identified, s->id, s);
    if (e.code)
      goto done;
    e = omap_put(&origins, s->id, r);
    if (e.code)
      goto done;
    if (!s->is_subagent) {
      s->has_depth = true;
      s->depth = 0;
      continue;
    }
    s->parent_id = r->parent_session;
    if (r->parent_agent.p) {
      char *p;
      size_t n = r->parent_session.n + r->parent_agent.n + 8;
      e = arena_alloc(&c->arena, n, 1, (void **)&p);
      if (e.code)
        goto done;
      snprintf(p, n, "%s/agent-%s", r->parent_session.p, r->parent_agent.p);
      s->parent_id = (Str){p, (uint32_t)strlen(p)};
    }
    s->agent_label = r->description;
    if (r->agent_type.p)
      s->meta.agent_nickname =
          (JScalar){.kind = JS_STRING, .value.s = r->agent_type};
    s->has_depth = r->has_spawn_depth;
    s->depth = r->spawn_depth;
    s->kind = STR_LIT("subagent");
  }
  e = corpus_graph_break_cycles(&c->arena, &identified);
  if (e.code)
    goto done;
  for (OmapEntry *q = identified.first; q; q = q->next) {
    SessionModel *s = q->value;
    if (!s->is_subagent)
      continue;
    SessionModel *parent = omap_get(&identified, s->parent_id);
    if (!parent) {
      s->kind = STR_LIT("orphan");
      s->flags |= F_ORPHAN;
      e = corpus_strings_add(&c->arena, &c->claude_orphaned_subagents, s->id);
    } else {
      e = corpus_strings_add(&c->arena, &parent->children, s->id);
      ClaudeRecord *r = omap_get(&origins, s->id),
                   *p = omap_get(&origins, parent->id);
      Str *spawn = r->tool_use_id.p ? omap_get(&p->tool_turns, r->tool_use_id) : NULL;
      if (spawn) {
        s->spawn_turn = *spawn;
        s->link_method = STR_LIT("tool_use");
        for (size_t j = 0; j < parent->turn_count; j++)
          if (str_equal(parent->turns[j].id, *spawn)) {
            if (!e.code)
              e = corpus_strings_add(&c->arena, &parent->turns[j].spawned, s->id);
            break;
          }
      }
    }
    if (e.code)
      goto done;
    if (!s->has_depth) {
      SessionModel *p = s;
      size_t steps = 0;
      while (p && !p->has_depth && steps <= identified.size) {
        steps++;
        p = omap_get(&identified, p->parent_id);
      }
      if (p && p->has_depth) {
        s->has_depth = true;
        s->depth = p->depth + steps;
      }
    }
  }
  for (OmapEntry *q = identified.first; q; q = q->next) {
    e = corpus_children_order(q->value, &identified);
    if (e.code)
      break;
  }
done:
  omap_destroy(&identified);
  omap_destroy(&origins);
  return e;
}
Err claude_corpus_add(ClaudeRecord *records, size_t count, int64_t snapshot,
                      Corpus *c, CorpusStrings *collisions) {
  Omap codex_ids = {0};
  ClaudeRecord *views = NULL;
  size_t view_count = 0;
  Err e = ERR_SUCCESS;
  for (OmapEntry *q = c->sessions.first; q; q = q->next) {
    SessionModel *s = q->value;
    if (s->provider != PROVIDER_CODEX)
      continue;
    e = omap_put(&codex_ids, s->id, s);
    if (e.code)
      break;
  }
  for (size_t i = 0; i < count && !e.code; i++)
    if (omap_get(&codex_ids, records[i].id))
      e = corpus_strings_add(&c->arena, collisions, records[i].id);
  if (!e.code) e = claude_reader_reconcile(records, count, c, &views, &view_count);
  if (!e.code) e = add_records(views, view_count, snapshot, c, &codex_ids);
  if (!e.code) e = link_records(views, view_count, c);
  claude_reader_views_destroy(views, view_count);
  omap_destroy(&codex_ids);
  return e;
}
