#include "assemble.h"
#include "provider.h"
#include "price/compose.h"
#include "parse/record.h"
#include "parse/tools.h"
#include "titles.h"
#include "workspaces.h"
#include "turnstatus.h"
#include "util/events.h"
#include "util/sort.h"
#include <stdalign.h>
#include <string.h>
#define TRY(expr)                                                              \
  do {                                                                         \
    Err err_ = (expr);                                                         \
    if (err_.code)                                                             \
      return err_;                                                             \
  } while (0)
static Err allocate(Corpus *c, size_t count, size_t size, void **out) {
  *out = NULL;
  if (!count)
    return ERR_SUCCESS;
  if (count > SIZE_MAX / size)
    return err_make(ERR_NOMEM, "assembly allocation overflow");
  Err e = arena_alloc(&c->arena, count * size, alignof(max_align_t), out);
  if (!e.code)
    memset(*out, 0, count * size);
  return e;
}
static Str rawtext(JScalar v) {
  return v.kind == JS_STRING ? v.value.s : (Str){0};
}
AssemblyRecord assembly_record(const LogRecord *r) {
  return (AssemblyRecord){.record=r,
    .meta_id={.kind=r->meta.id.p?JS_STRING:JS_NULL,.value.s=r->meta.id}};
}
static Str dbtext(const MetadataThread *row, MetadataColumn column) {
  return row && row->values[column].kind == META_TEXT
             ? row->values[column].value.bytes
             : (Str){0};
}
static Err count_merge(Arena *arena, Omap *out, const Omap *source, bool wide) {
  for (OmapEntry *p = source->first; p; p = p->next) {
    __int128 amount = wide ? *(__int128 *)p->value : *(uint64_t *)p->value;
    __int128 *value = omap_get(out, p->key);
    if (value)
      *value += amount;
    else {
      TRY(arena_alloc(arena, sizeof *value, alignof(__int128),
                      (void **)&value));
      *value = amount;
      TRY(omap_put(out, p->key, value));
    }
  }
  return ERR_SUCCESS;
}
static void note_payload_sum(__int128 value, const char *site) {
  if (value < INT64_MIN || value > INT64_MAX)
    event_note("int128_payload_sum", site, 1);
}
static void note_count_sums(const Omap *counts, const char *site) {
  for (OmapEntry *p = counts->first; p; p = p->next)
    note_payload_sum(*(__int128 *)p->value, site);
}
static void note_tools_sums(const CorpusTools *tools, bool turn) {
  static const char *const sites[2][7] = {
      {"session.tools.shell", "session.tools.shell_failed",
       "session.tools.file_edits", "session.tools.web", "session.tools.image",
       "session.tools.mcp.*", "session.tools.other.*"},
      {"turn.tools.shell", "turn.tools.shell_failed", "turn.tools.file_edits",
       "turn.tools.web", "turn.tools.image", "turn.tools.mcp.*",
       "turn.tools.other.*"}};
  const __int128 values[] = {tools->shell, tools->shell_failed,
                             tools->file_edits, tools->web, tools->image};
  for (size_t i = 0; i < 5; i++)
    note_payload_sum(values[i], sites[turn][i]);
  note_count_sums(&tools->mcp, sites[turn][5]);
  note_count_sums(&tools->other, sites[turn][6]);
}
/* Completed semantic sums are noted once here, before any page/stage rendering.
 * Dynamic map keys and session/turn identities never enter event sites. */
static void note_completed_sums(const Corpus *corpus) {
  note_payload_sum(corpus->malformed.total,
                   "diagnostics.malformed_lines.total");
  note_payload_sum(corpus->recovered.total,
                   "diagnostics.recovered_lines.total");
  note_payload_sum(corpus->truncated.total,
                   "diagnostics.truncated_lines.total");
  note_count_sums(&corpus->unknown_types, "diagnostics.unknown_record_types.*");
  for (OmapEntry *p = corpus->sessions.first; p; p = p->next) {
    const SessionModel *session = p->value;
    for (size_t i = 0; i < session->turn_count; i++)
      note_tools_sums(&session->turns[i].tools, true);
    note_tools_sums(&session->tools, false);
  }
}
Err corpus_tool_merge(Arena *arena, CorpusTools *out,
                      const ToolCounts *source) {
  out->shell += source->shell;
  out->shell_failed += source->shell_failed;
  out->file_edits += source->file_edits;
  out->web += source->web;
  out->image += source->image;
  TRY(count_merge(arena, &out->mcp, &source->mcp, false));
  return count_merge(arena, &out->other, &source->other, false);
}
static Err aggregate_tools(Arena *arena, CorpusTools *out,
                           const CorpusTools *source) {
  out->shell += source->shell;
  out->shell_failed += source->shell_failed;
  out->file_edits += source->file_edits;
  out->web += source->web;
  out->image += source->image;
  TRY(count_merge(arena, &out->mcp, &source->mcp, true));
  return count_merge(arena, &out->other, &source->other, true);
}
Err corpus_turn_tools_adopt(Arena *arena, SessionModel *session,
                           TurnModel *turn, const CorpusTools *source) {
  TRY(aggregate_tools(arena, &turn->tools, source));
  return aggregate_tools(arena, &session->tools, source);
}
static int record_order(const void *a, const void *b, void *ctx) {
  (void)ctx;
  const AssemblyRecord *x = a, *y = b;
  int64_t xm, ym;
  floordiv_i64(x->record->key.mtime_ns, 1000000, &xm);
  floordiv_i64(y->record->key.mtime_ns, 1000000, &ym);
  if (xm != ym)
    return xm > ym ? -1 : 1;
  if (x->record->key.size != y->record->key.size)
    return x->record->key.size < y->record->key.size ? -1 : 1;
  return str_compare(x->record->key.path, y->record->key.path);
}
static int request_order(const void *a, const void *b, void *ctx) {
  const Request *x = *(Request *const *)a, *y = *(Request *const *)b;
  if (ctx && x->before_turn != y->before_turn)
    return x->before_turn ? -1 : 1;
  if (x->at_ms.present != y->at_ms.present)
    return x->at_ms.present ? -1 : 1;
  return x->at_ms.present ? (x->at_ms.value > y->at_ms.value) -
                                (x->at_ms.value < y->at_ms.value)
                          : 0;
}
static Err diagnose(Corpus *c, FileDiagnostic *diag, Str path, uint64_t count) {
  (void)c;
  if (count) {
    diag->total += count;
    diag->files[diag->count++] = (DiagnosticFile){path, count};
  }
  return ERR_SUCCESS;
}
static Err assemble(Corpus *c, SessionModel *s, const CodexMetadata *metadata,
                    int64_t snapshot) {
  const LogRecord *r = s->record;
  bool collapsed = r->wrapper_count > 1 && r->wrapper_distinct == 1;
  bool unresolved = str_equal(r->history.method, STR_LIT("unresolved"));
  s->flags = (!r->has_meta ? F_NO_META : 0) | (collapsed ? F_COLLAPSED : 0) |
             (unresolved ? F_HISTORY : 0);
  s->db_info = s->identity.p ? omap_get(&metadata->threads, s->identity) : NULL;
  size_t max = r->message_count + r->request_count;
  Omap turns = {0};
  Err e = ERR_SUCCESS;
  if (!unresolved) {
    int64_t mtime;
    floordiv_i64(r->key.mtime_ns, 1000000, &mtime);
    e = turn_models(&c->arena, r->turns, r->turn_count, collapsed, mtime,
                    snapshot, &s->turns);
    if (e.code)
      goto done;
    s->turn_count = r->turn_count;
    e = allocate(c, max, sizeof *s->requests, (void **)&s->requests);
    if (e.code)
      goto done;
    e = allocate(c, max, sizeof *s->ordered_requests,
                 (void **)&s->ordered_requests);
    if (e.code)
      goto done;
    e = allocate(c, r->request_count, sizeof *s->voice_requests,
                 (void **)&s->voice_requests);
    if (e.code)
      goto done;
    e = allocate(c, r->request_count + r->reply_count, sizeof *s->voice_replies,
                 (void **)&s->voice_replies);
    if (e.code)
      goto done;
    /* Count requests by key once before allocating per-turn arrays. */
    for (size_t i = 0; i < s->turn_count; i++) {
      e = omap_put(&turns, s->turns[i].id, &s->turns[i]);
      if (e.code)
        goto done;
    }
    for (size_t i = 0; i < r->message_count; i++) {
      const MessageFact *m = &r->messages[i];
      if (!str_equal(m->role, STR_LIT("user")))
        continue;
      Request *q = &s->requests[s->request_count];
      *q = (Request){.at_ms = m->at_ms,
                     .text = m->text,
                     .kind = m->kind,
                     .images = m->images,
                     .time_unreliable =
                         collapsed &&
                         str_equal(m->ts_src, STR_LIT("record_timestamp"))};
      s->ordered_requests[s->request_count++] = q;
      TurnModel *t = omap_get(&turns, m->turn_key);
      if (t)
        t->request_count++;
    }
    for (size_t i = 0; i < r->request_count; i++) {
      const VoiceRequest *v = &r->requests[i];
      Request *q = &s->requests[s->request_count];
      *q = (Request){.at_ms = v->at_ms,
                     .text = v->text,
                     .kind = STR_LIT("voice"),
                     .before_turn = v->before_turn,
                     .time_unreliable = collapsed,
                     .voice = v};
      s->ordered_requests[s->request_count++] = q;
      TurnModel *t = omap_get(&turns, v->turn_key);
      if (t) {
        t->request_count++;
        if (!v->before_turn && v->reply.p) {
          t->final_answer = v->reply;
          t->final_voice = true;
        }
      } else {
        s->voice_requests[s->voice_request_count++] = q;
        if (v->reply.p)
          s->voice_replies[s->voice_reply_count++] =
              (VoiceReply){.text = v->reply};
      }
    }
    for (size_t i = 0; i < r->reply_count; i++)
      if (!r->replies[i].turn_key.p)
        s->voice_replies[s->voice_reply_count++] = r->replies[i];
    for (size_t i = 0; i < r->reply_count; i++) {
      TurnModel *t = omap_get(&turns, r->replies[i].turn_key);
      if (t)
        t->voice_reply_count++;
    }
    for (size_t i = 0; i < r->message_count; i++) {
      const MessageFact *m = &r->messages[i];
      TurnModel *t = omap_get(&turns, m->turn_key);
      if (t && str_equal(m->kind, STR_LIT("final"))) {
        t->final_answer = m->text;
        t->final_voice = false;
      }
    }
    for (size_t i = 0; i < s->turn_count; i++) {
      TurnModel *t = &s->turns[i];
      e = allocate(c, t->request_count, sizeof *t->requests,
                   (void **)&t->requests);
      if (e.code)
        goto done;
      t->request_count = 0;
      e = allocate(c, t->voice_reply_count, sizeof *t->voice_replies,
                   (void **)&t->voice_replies);
      if (e.code)
        goto done;
      t->voice_reply_count = 0;
    }
    for (size_t i = 0; i < r->reply_count; i++) {
      TurnModel *t = omap_get(&turns, r->replies[i].turn_key);
      if (t)
        t->voice_replies[t->voice_reply_count++] = r->replies[i];
    }
    size_t request = 0;
    for (size_t i = 0; i < r->message_count; i++)
      if (str_equal(r->messages[i].role, STR_LIT("user"))) {
        TurnModel *t = omap_get(&turns, r->messages[i].turn_key);
        if (t)
          t->requests[t->request_count++] = &s->requests[request];
        request++;
      }
    for (size_t i = 0; i < r->request_count; i++) {
      TurnModel *t = omap_get(&turns, r->requests[i].turn_key);
      if (t)
        t->requests[t->request_count++] = &s->requests[request];
      request++;
    }
    for (size_t i = 0; i < s->turn_count; i++) {
      TurnModel *t = &s->turns[i];
      e = stable_sort(t->requests, t->request_count, sizeof *t->requests,
                      request_order, (void *)1);
      if (e.code)
        goto done;
      ToolTally *tally = omap_get(&r->tools, t->id);
      if (tally) {
        e = corpus_tool_merge(&c->arena, &t->tools,
                              tally->has_structured ? &tally->structured
                                                    : &tally->raw);
        if (e.code)
          goto done;
      }
      e = aggregate_tools(&c->arena, &s->tools, &t->tools);
      if (e.code)
        goto done;
      if (str_equal(t->status, STR_LIT("running")))
        s->flags |= F_LIVE;
      else if (str_equal(t->status, STR_LIT("aborted")))
        s->flags |= F_ABORTED;
      else if (str_equal(t->status, STR_LIT("interrupted")))
        s->flags |= F_INTERRUPTED;
      else if (str_equal(t->status, STR_LIT("abandoned")))
        s->flags |= F_ABANDONED;
      if (t->flags & (F_UNKNOWN | F_COLLAPSED))
        s->flags |= F_UNCERTAIN;
    }
    for (size_t i = 0; i < s->request_count; i++)
      if (s->requests[i].time_unreliable)
        s->flags |= F_UNCERTAIN;
    e = stable_sort(s->ordered_requests, s->request_count,
                    sizeof *s->ordered_requests, request_order, NULL);
    if (e.code)
      goto done;
    e = stable_sort(s->voice_requests, s->voice_request_count,
                    sizeof *s->voice_requests, request_order, NULL);
    if (e.code)
      goto done;
    s->start_ms = r->first_ms;
    s->end_ms = r->last_ms;
    if (s->start_ms.present && s->end_ms.present) {
      MaybeNum active;
      PyNum span;
      e = active_interval_union(&c->arena, s->turns, s->turn_count, &active);
      if (e.code)
        goto done;
      if (active.present &&
          pynum_sub((PyNum){.i = s->end_ms.value},
                    (PyNum){.i = s->start_ms.value}, "session.idle", &span))
        s->idle_ms.present =
            pynum_sub(span, active.value, "session.idle", &s->idle_ms.value);
    }
    bool reliable = s->request_count >= 2;
    for (size_t i = 0; i < s->request_count; i++)
      if (s->requests[i].time_unreliable || !s->requests[i].at_ms.present)
        reliable = false;
    if (reliable) {
      PyNum span;
      if (pynum_sub(
              (PyNum){
                  .i = s->ordered_requests[s->request_count - 1]->at_ms.value},
              (PyNum){.i = s->ordered_requests[0]->at_ms.value},
              "session.user_span", &span))
        s->user_span_ms = (MaybeMs){true, span.i};
    }
  }
  if (r->meta.is_subagent) {
    s->title_source = STR_LIT("agent_path");
    e = title_subagent(&c->arena, rawtext(r->meta.agent_path),
                       rawtext(r->meta.agent_nickname), &s->title_full);
  } else {
    Str *index = omap_get(&metadata->index_titles, s->identity),
        *desktop = omap_get(&metadata->desktop_titles, s->identity);
    Str candidates[] = {dbtext(s->db_info, META_NAME),
                        index ? *index : (Str){0},
                        desktop ? *desktop : (Str){0},
                        rawtext(r->meta.rollout_title),
                        dbtext(s->db_info, META_TITLE),
                        s->request_count ? s->ordered_requests[0]->text
                                         : (Str){0},
                        dbtext(s->db_info, META_FIRST_USER_MESSAGE)};
    Str cwd = record_scalar_truthy(r->meta.cwd) ? rawtext(r->meta.cwd)
                                                : dbtext(s->db_info, META_CWD);
    title_select(candidates, cwd, s->id, r->key.path, &s->title_full,
                 &s->title_source);
  }
  if (!e.code)
    e = title_display(&c->arena, s->title_full, &s->title);
done:
  omap_destroy(&turns);
  return e;
}
static bool uuid_tail(Str stem, Str *id) {
  if (stem.n && stem.p[stem.n - 1] == '\n')
    stem.n--;
  if (stem.n < 36)
    return false;
  Str tail = {stem.p + stem.n - 36, 36};
  for (size_t i = 0; i < 36; i++) {
    char ch = tail.p[i];
    if (i == 8 || i == 13 || i == 18 || i == 23) {
      if (ch != '-')
        return false;
    } else if (!((ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f') ||
                 (ch >= 'A' && ch <= 'F')))
      return false;
  }
  *id = tail;
  return true;
}
static Err file_key(Arena *arena, Str path, Str *out) {
  char *p;
  TRY(arena_alloc(arena, path.n + 6, 1, (void **)&p));
  memcpy(p, "file:", 5);
  memcpy(p + 5, path.p, path.n);
  p[path.n + 5] = 0;
  *out = (Str){p, path.n + 5};
  return ERR_SUCCESS;
}
static int file_order(const void *a, const void *b, void *ctx) {
  (void)ctx;
  const SessionModel *x = *(SessionModel *const *)a,
                     *y = *(SessionModel *const *)b;
  return str_compare(x->record->key.path, y->record->key.path);
}
Err corpus_build(const AssemblyRecord *records, size_t count,
                 const CodexMetadata *metadata, int64_t snapshot,
                 Intern *intern, Corpus *c) {
  c->diagnostic_order_count=4;for(size_t i=0;i<4;i++)c->diagnostic_order[i]=(unsigned char)i;
  AssemblyRecord *ordered;
  TRY(allocate(c, count, sizeof *ordered, (void **)&ordered));
  if (count)
    memcpy(ordered, records, count * sizeof *ordered);
  c->inputs = ordered;
  c->input_count = count;
  TRY(stable_sort(ordered, count, sizeof *ordered, record_order, NULL));
  TRY(allocate(c, count, sizeof *c->skipped, (void **)&c->skipped));
  TRY(allocate(c,count,sizeof *c->skipped_files,(void **)&c->skipped_files));
  TRY(allocate(c, count, sizeof *c->malformed.files,
               (void **)&c->malformed.files));
  TRY(allocate(c, count, sizeof *c->truncated.files,
               (void **)&c->truncated.files));
  TRY(allocate(c, count, sizeof *c->recovered.files,
               (void **)&c->recovered.files));
  Omap known = {0}, allocated = {0}, groups = {0}, displays = {0};
  SessionModel **files = NULL;
  size_t file_count = 0;
  Err e = ERR_SUCCESS;
  for (size_t i = 0; i < count; i++) {
    Str id = rawtext(records[i].meta_id);
    if (metadata_text(id)) {
      e = omap_put(&known, id, (void *)1);
      if (e.code)
        goto done;
    }
  }
  for (OmapEntry *p = known.first; p; p = p->next) {
    e = omap_put(&allocated, p->key, (void *)1);
    if (e.code)
      goto done;
  }
  for (OmapEntry *p = metadata->threads.first; p; p = p->next)
    if (!omap_get(&known, p->key))
      c->db_threads_without_logs++;
  e = allocate(c, count, sizeof *files, (void **)&files);
  if (e.code)
    goto done;
  for (size_t i = 0; i < count; i++) {
    const LogRecord *r = ordered[i].record;
    if (ordered[i].typed_clocks &&
        (ordered[i].spawn_clock_count != r->spawn_count ||
         (r->spawn_count && !ordered[i].spawn_clocks))) {
      e = err_make(ERR_INVALID, "assembly spawn clock count mismatch");
      goto done;
    }
    int64_t mtime;
    floordiv_i64(r->key.mtime_ns, 1000000, &mtime);
    diagnose(c, &c->malformed, r->key.path, r->reader.malformed);
    diagnose(c, &c->recovered, r->key.path, r->reader.recovered);
    diagnose(c, &c->truncated, r->key.path,
             r->reader.partial_final_line && corpus_quiet(snapshot, mtime));
    e = count_merge(&c->arena, &c->unknown_types, &r->reader.unknown_types,
                    false);
    if (e.code)
      goto done;
    if (!str_equal(r->status, STR_LIT("ok"))) {
      c->skipped[c->skipped_count++] = r;
      continue;
    }
    Str identity = rawtext(ordered[i].meta_id);
    if (!metadata_text(identity))
      identity = (Str){0};
    Str group = identity;
    /* Disjoint internal namespaces retain exact raw identity spellings. */
    char *g;
    e = arena_alloc(&c->arena, (identity.p ? identity.n : r->key.path.n) + 2, 1,
                    (void **)&g);
    if (e.code)
      goto done;
    g[0] = identity.p ? 'S' : 'F';
    Str suffix = identity.p ? identity : r->key.path;
    memcpy(g + 1, suffix.p, suffix.n);
    group = (Str){g, suffix.n + 1};
    SessionModel *s = omap_get(&groups, group);
    if (!s) {
      e = arena_alloc(&c->arena, sizeof *s, alignof(SessionModel), (void **)&s);
      if (e.code)
        goto done;
      *s = (SessionModel){
          .identity = identity, .record = r, .meta_id = ordered[i].meta_id,
          .input=&ordered[i]};
      if (identity.p) {
        e = intern_get(intern, identity, &s->id);
        if (e.code)
          goto done;
        s->key = s->id;
      } else {
        s->id = title_path_name(r->key.path, true);
        uuid_tail(s->id, &s->id);
        files[file_count++] = s;
        uint64_t *n = omap_get(&displays, s->id);
        if (n)
          (*n)++;
        else {
          e = allocate(c, 1, sizeof *n, (void **)&n);
          if (e.code)
            goto done;
          *n = 1;
          e = omap_put(&displays, s->id, n);
          if (e.code)
            goto done;
        }
      }
      e = omap_put(&groups, group, s);
      if (e.code)
        goto done;
    }
    e = record_append(&c->arena, (void **)&s->records, &s->record_count,
                      &s->record_capacity, sizeof *s->records, &r);
    if (e.code)
      goto done;
    if (r->key.mtime_ns > s->record->key.mtime_ns ||
        (r->key.mtime_ns == s->record->key.mtime_ns &&
         str_compare(r->key.path, s->record->key.path) < 0)) {
      s->record = r;
      s->meta_id = ordered[i].meta_id;
      s->input = &ordered[i];
    }
  }
  e = stable_sort(files, file_count, sizeof *files, file_order, NULL);
  if (e.code)
    goto done;
  for (size_t i = 0; i < file_count; i++) {
    SessionModel *s = files[i];
    e = file_key(&c->arena, s->record->key.path, &s->key);
    if (e.code)
      goto done;
    while (omap_get(&allocated, s->key)) {
      Str next;
      e = file_key(&c->arena, s->key, &next);
      if (e.code)
        goto done;
      s->key = next;
    }
    e = omap_put(&allocated, s->key, (void *)1);
    if (e.code)
      goto done;
    uint64_t *n = omap_get(&displays, s->id);
    if (omap_get(&known, s->id) || (n && *n > 1))
      s->id = s->key;
  }
  for (OmapEntry *p = groups.first; p; p = p->next) {
    SessionModel *s = p->value;
    s->archived=s->record->key.archived;s->log_path=s->record->key.path;
    s->has_meta=s->record->has_meta;s->meta=s->record->meta;
    s->is_subagent=s->meta.is_subagent;s->meta_input=*s->input;
    e = omap_put(&c->sessions, s->key, s);
    if (e.code)
      goto done;
    e = assemble(c, s, metadata, snapshot);
    if (e.code)
      goto done;
  }
done:
  if (!e.code){
    for(size_t i=0;i<c->skipped_count;i++)c->skipped_files[c->skipped_file_count++]=(SkippedFile){c->skipped[i]->key.path,c->skipped[i]->status};
    note_completed_sums(c);
  }
  omap_destroy(&known);
  omap_destroy(&allocated);
  omap_destroy(&groups);
  omap_destroy(&displays);
  return e;
}
void corpus_destroy(Corpus *c) {
  compose_destroy(c);
  corpus_workspaces_destroy(c);
  for (OmapEntry *p = c->sessions.first; p; p = p->next) {
    SessionModel *s = p->value;
    omap_destroy(&s->tools.mcp);
    omap_destroy(&s->tools.other);
    for (size_t i = 0; i < s->turn_count; i++) {
      omap_destroy(&s->turns[i].tools.mcp);
      omap_destroy(&s->turns[i].tools.other);
    }
  }
  omap_destroy(&c->sessions);
  omap_destroy(&c->unknown_types);
  arena_destroy(&c->arena);
  *c = (Corpus){0};
}
