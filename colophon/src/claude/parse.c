#define _DARWIN_C_SOURCE
#include "parse.h"
#include "corpus/subagents.h"
#include "corpus/titles.h"
#include "corpus/turnstatus.h"
#include "util/time.h"
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
static Err on_record(void *context, const ReaderRecord *row) {
  Parse *p = context;
  ClaudeRecord *r = p->r;
  yyjson_val *v = row->record, *message = get(v, "message"),
             *body = get(message, "content");
  Str type = text(get(v, "type"));
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
      GROW(tools, CorpusTools);
      p->capacity = n;
#undef GROW
    }
    size_t i = r->turn_count++;
    TurnFact *t;
    TRY(alloc(&r->arena, 1, sizeof *t, alignof(TurnFact), (void **)&t));
    r->turns[i] = t;
    char id[48];
    int n = snprintf(id, sizeof id, "claude-turn-%zu", i + 1);
    TRY(copy(&r->arena, (Str){id, (uint32_t)n}, &t->key));
    t->start_ms = at;
    t->has_start_rec = true;
    t->start_rec = row->rec;
    r->requests[i] =
        (Request){.at_ms = at, .text = request, .kind = kind, .images = images};
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
    if (answer.n)
      r->answers[turn] = answer;
  }
  size_t i, max;
  yyjson_val *q;
  yyjson_arr_foreach(body, i, max, q) {
    Str block = text(get(q, "type"));
    if (str_equal(block, STR_LIT("tool_use"))) {
      Str name = text(get(q, "name")), id = text(get(q, "id"));
      CorpusTools *tools = &r->tools[turn];
      if (str_equal(name, STR_LIT("Bash"))) {
        tools->shell++;
        if (id.n)
          TRY(omap_put(&p->shell_ids, id, (void *)(uintptr_t)(turn + 1)));
      } else if (str_equal(name, STR_LIT("Edit")) ||
                 str_equal(name, STR_LIT("Write")) ||
                 str_equal(name, STR_LIT("MultiEdit")) ||
                 str_equal(name, STR_LIT("NotebookEdit")))
        tools->file_edits++;
      else if (str_equal(name, STR_LIT("WebFetch")) ||
               str_equal(name, STR_LIT("WebSearch")))
        tools->web++;
      else if (prefix(name, "mcp__")) {
        Str server = {name.p + 5, name.n - 5};
        const char *end = memmem(server.p, server.n, "__", 2);
        if (end && end > server.p) {
          server.n = (uint32_t)(end - server.p);
          TRY(count(&r->arena, &tools->mcp, server));
        } else
          TRY(count(&r->arena, &tools->other, name));
      } else
        TRY(count(&r->arena, &tools->other, name));
    } else if (str_equal(block, STR_LIT("tool_result")) &&
               yyjson_is_true(get(q, "is_error"))) {
      size_t owner = (size_t)(uintptr_t)omap_get(&p->shell_ids,
                                                 text(get(q, "tool_use_id")));
      if (owner) {
        r->tools[owner - 1].shell_failed++;
        TRY(omap_put(&p->shell_ids, text(get(q, "tool_use_id")), NULL));
      }
    }
  }
  return ERR_SUCCESS;
}
Err claude_parse(const DiscoveredLog *key, Str root, Str config,
                 ClaudeRecord *out) {
  *out = (ClaudeRecord){.key = *key};
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
  Parse p = {.r = out};
  ReaderCallbacks cb = {
      .context = &p, .known_type = claude_known_type, .record = on_record};
  Err e = reader_read_log(&out->key, &cb, &out->reader);
  finish(&p);
  omap_destroy(&p.shell_ids);
  return e;
}
void claude_record_destroy(ClaudeRecord *r) {
  for (size_t i = 0; i < r->turn_count; i++) {
    omap_destroy(&r->tools[i].mcp);
    omap_destroy(&r->tools[i].other);
  }
  reader_result_destroy(&r->reader);
  arena_destroy(&r->arena);
  *r = (ClaudeRecord){0};
}
static Err add_records(ClaudeRecord *records, size_t count, int64_t snapshot,
                       Corpus *c, CorpusStrings *collisions,
                       const Omap *codex_ids) {
  for (size_t i = 0; i < count; i++) {
    ClaudeRecord *r = &records[i];
    SessionModel *s = omap_get(&c->sessions, r->id);
    if (omap_get(codex_ids, r->id) || (s && s->provider == PROVIDER_CODEX)) {
      TRY(corpus_strings_add(&c->arena, collisions, r->id));
      continue;
    }
    if (s) {
      if (r->config_dir.p && !r->parent_session.p &&
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
                        .resume_config_dir = r->config_dir,
                        .start_ms = r->first_ms,
                        .end_ms = r->last_ms};
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
      /* Copy wide tool maps into corpus ownership; record maps remain
       * separately owned. */
      CorpusTools *src = &r->tools[k];
      t->tools.shell = src->shell;
      t->tools.shell_failed = src->shell_failed;
      t->tools.file_edits = src->file_edits;
      t->tools.web = src->web;
      s->tools.shell += src->shell;
      s->tools.shell_failed += src->shell_failed;
      s->tools.file_edits += src->file_edits;
      s->tools.web += src->web;
      Omap *from[] = {&src->mcp, &src->other},
           *dest[] = {&t->tools.mcp, &t->tools.other},
           *total[] = {&s->tools.mcp, &s->tools.other};
      for (size_t m = 0; m < 2; m++)
        for (OmapEntry *q = from[m]->first; q; q = q->next) {
          __int128 *v;
          TRY(alloc(&c->arena, 1, sizeof *v, alignof(__int128), (void **)&v));
          *v = *(__int128 *)q->value;
          TRY(omap_put(dest[m], q->key, v));
          __int128 *sum = omap_get(total[m], q->key);
          if (sum)
            *sum += *v;
          else {
            TRY(alloc(&c->arena, 1, sizeof *sum, alignof(__int128),
                      (void **)&sum));
            *sum = *v;
            TRY(omap_put(total[m], q->key, sum));
          }
        }
      if (str_equal(t->status, STR_LIT("running")))
        s->flags |= F_LIVE;
      else if (str_equal(t->status, STR_LIT("abandoned")))
        s->flags |= F_ABANDONED;
      else if (str_equal(t->status, STR_LIT("aborted")))
        s->flags |= F_ABORTED;
      else if (str_equal(t->status, STR_LIT("interrupted")))
        s->flags |= F_INTERRUPTED;
    }
    s->title_full = r->turn_count ? r->requests[0].text : r->id;
    s->title_source =
        r->turn_count ? STR_LIT("first_request") : STR_LIT("filename");
    TRY(title_display(&c->arena, s->title_full, &s->title));
    if (s->start_ms.present && s->end_ms.present) {
      MaybeNum active;
      TRY(active_interval_union(&c->arena, s->turns, s->turn_count, &active));
      if (active.present)
        s->idle_ms = (MaybeNum){
            true, {.i = s->end_ms.value - s->start_ms.value - active.value.i}};
    }
    TRY(omap_put(&c->sessions, s->id, s));
  }
  return ERR_SUCCESS;
}
Err claude_corpus_add(ClaudeRecord *records, size_t count, int64_t snapshot,
                      Corpus *c, CorpusStrings *collisions) {
  Omap codex_ids = {0};
  Err e = ERR_SUCCESS;
  for (OmapEntry *q = c->sessions.first; q; q = q->next) {
    SessionModel *s = q->value;
    if (s->provider != PROVIDER_CODEX)
      continue;
    e = omap_put(&codex_ids, s->id, s);
    if (e.code)
      break;
  }
  if (!e.code)
    e = add_records(records, count, snapshot, c, collisions, &codex_ids);
  omap_destroy(&codex_ids);
  return e;
}
