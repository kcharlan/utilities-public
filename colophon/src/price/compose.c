#include "compose.h"
#include "model.h"
#include "request_ledger.h"
#include "parse/record.h"
#include "util/events.h"
#include "util/pynum.h"
#include "util/sort.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define TRY(x)                                                                 \
  do {                                                                         \
    Err e_ = (x);                                                              \
    if (e_.code)                                                               \
      return e_;                                                               \
  } while (0)
static Err alloc(Arena *a, size_t n, size_t width, size_t align, void **out) {
  if (n && width > SIZE_MAX / n)
    return err_make(ERR_NOMEM, "composition allocation overflow");
  TRY(arena_alloc(a, n * width, align, out));
  if (n)
    memset(*out, 0, n * width);
  return ERR_SUCCESS;
}
static Err canon(Arena *a, Str value, Str *out) {
  return str_nfc(a, value, "composition.identity", out);
}
static Err strings(Arena *a, CorpusStrings *out, Str value) {
  return record_append(a, (void **)&out->items, &out->count, &out->capacity,
                       sizeof value, &value);
}
void compose_destroy(Corpus *c) {
  omap_destroy(&c->duplicate_ids);
  arena_destroy(&c->usage_arena);
  c->trace_messages = (CorpusStrings){0};
  c->fork_baselines = (CorpusStrings){0};
  c->composed = false;
  c->duplicate_order = (CorpusStrings){0};
  for (OmapEntry *p = c->sessions.first; p; p = p->next) {
    SessionModel *s = p->value;
    s->units = NULL;
    s->unit_count = s->unit_capacity = 0;
    s->own_usage = s->outside_usage = NULL;
    s->buckets = NULL;
    s->bucket_count = 0;
    for (size_t i = 0; i < s->turn_count; i++)
      s->turns[i].usage = NULL;
  }
}
Err compose_row_key(Arena *a, Str session, Str file, const AccountingRow *r,
                    Str *out) {
  JsonWriter w = {0};
  jsonw_raw(&w, session.p ? "session:" : "file:");
  Str prefix = session.p ? session : file;
  jsonw_bytes(&w, prefix.p, prefix.n);
  jsonw_raw(&w, "\x1f");
  jsonw_bytes(&w, r->turn_id.p, r->turn_id.n);
  jsonw_raw(&w, "\x1f");
  if (!r->event_index_absent)
    jsonw_i64(&w, (int64_t)r->event_index);
  jsonw_raw(&w, "\x1f");
  jsonw_bytes(&w, r->day, strlen(r->day));
  jsonw_raw(&w, "\x1f");
  jsonw_bytes(&w, r->model.p, r->model.n);
  jsonw_raw(&w, "\x1f");
  jsonw_i64(&w, r->tokens.input);
  jsonw_raw(&w, "\x1f");
  jsonw_i64(&w, r->tokens.cached);
  jsonw_raw(&w, "\x1f");
  jsonw_i64(&w, r->tokens.output);
  jsonw_raw(&w, "\x1f");
  if (r->timestamp_ms.present)
    jsonw_i64(&w, r->timestamp_ms.value);
  Err e = w.error;
  if (!e.code)
    e = canon(a, (Str){w.data, (uint32_t)w.length}, out);
  jsonw_free(&w);
  return e;
}
/* JScalar is already decoded using the shared Foundation numeric contract.
 * Direct stage floats use NSNumber.intValue's finite saturation semantics. */
static OptionalTokens number(JScalar v) {
  if (v.kind == JS_INT)
    return (OptionalTokens){true, v.value.i};
  if (v.kind == JS_BOOL)
    return (OptionalTokens){true, v.value.b};
  if (v.kind != JS_FLOAT || !isfinite(v.value.f))
    return (OptionalTokens){0};
  if (v.value.f >= 0x1p63)
    return (OptionalTokens){true, INT64_MAX};
  if (v.value.f < -0x1p63)
    return (OptionalTokens){true, INT64_MIN};
  return (OptionalTokens){true, (int64_t)v.value.f};
}
static __int128 positive(JScalar v) {
  OptionalTokens n = number(v);
  return n.present && n.value > 0 ? n.value : 0;
}
typedef struct { uint64_t line; bool on; } PriorityStart;
typedef struct { PriorityStart *items; size_t count, capacity; } PriorityStarts;
/* CodexBar v0.74.1 processFastLine: settings persist until replaced; each
 * task_started records priority for its turn id (empty when absent). */
static Err thread_priority_starts(Arena *a, const LogRecord *r, Omap *out) {
  bool on = false;
  for (size_t i = 0; i < r->token_stream.count; i++) {
    const TokenObservation *o = &r->token_stream.observations[i];
    if (o->tag == TOKEN_P) { on = o->priority; continue; }
    if (o->tag != TOKEN_S) continue;
    Str key = STR_LIT("");
    if (o->turn_id.n) TRY(canon(a, o->turn_id, &key));
    PriorityStarts *starts = omap_get(out, key);
    if (!starts) {
      TRY(alloc(a, 1, sizeof *starts, _Alignof(PriorityStarts), (void **)&starts));
      TRY(omap_put(out, key, starts));
    }
    PriorityStart start = {o->line, on};
    TRY(record_append(a, (void **)&starts->items, &starts->count,
                      &starts->capacity, sizeof start, &start));
  }
  return ERR_SUCCESS;
}
/* priorityTurnIDs.contains(turnID ?? "") when each row is appended. */
static bool thread_priority_at(const Omap *by_turn, Str key, uint64_t line) {
  const PriorityStarts *starts = omap_get(by_turn, key);
  bool on = false;
  for (size_t i = 0; starts && i < starts->count && starts->items[i].line < line; i++)
    on = starts->items[i].on;
  return on;
}
static Err append(Corpus *c, SessionModel *s, const Omap *display,
                  const Omap *priority, const Omap *thread_priority,
                  Omap *normalizations, UsageUnit u) {
  Str identity = {0};
  if (u.turn_id.p)
    TRY(canon(&c->usage_arena, u.turn_id, &identity));
  const LogRecord *r = s->records[u.file];
  bool inherited = false;
  for (size_t i = 0; i < r->history.line_count; i++)
    if (r->history.inherited_lines[i].start <= u.line &&
        u.line < r->history.inherited_lines[i].end) {
      inherited = true;
      break;
    }
  Str *shown = inherited || !u.turn_id.p ? NULL : omap_get(display, identity);
  u.display_turn = shown ? *shown : (Str){0};
  u.session_id = s->id;
  u.priority = u.turn_id.p ? omap_get(priority, identity) : NULL;
  u.priority_fields = u.priority ? PRIORITY_FULL : 0;
  u.priority_tier = u.priority != NULL;
  if (!u.priority && thread_priority_at(thread_priority, identity.n ? identity : STR_LIT(""), u.line))
    u.priority_tier = true;
  TRY(normalize_codex_model_memo(&c->usage_arena,normalizations,u.model_raw,&u.model));
  if (s->unit_count == s->unit_capacity) {
    size_t capacity = s->unit_capacity ? s->unit_capacity * 2 : 8;
    if (capacity < s->unit_capacity)
      return err_make(ERR_NOMEM, "composition unit capacity overflow");
    UsageUnit *units;
    TRY(alloc(&c->usage_arena, capacity, sizeof *units, _Alignof(UsageUnit),
              (void **)&units));
    if (s->unit_count)
      memcpy(units, s->units, s->unit_count * sizeof *units);
    s->units = units;
    s->unit_capacity = capacity;
  }
  s->units[s->unit_count++] = u;
  return ERR_SUCCESS;
}
static int usage_order(const void *a, const void *b, void *ctx) {
  (void)ctx;
  const UsageRecord *x = *(const UsageRecord *const *)a,
                    *y = *(const UsageRecord *const *)b;
  return (x->line > y->line) - (x->line < y->line);
}
static Str model_at(const LogRecord *r, const AccountingResult *result,
                    uint64_t line) {
  Str model = {0};
  if (result->timeline_count || !r->token_stream.unconsumed_tail) {
    for (size_t i = 0; i < result->timeline_count; i++) {
      if (pynum_compare(
              (PyNum){.is_float = true, .f = result->timeline[i].position},
              (PyNum){.i = (int64_t)line}) >= 0)
        break;
      model = result->timeline[i].model;
    }
  } else
    for (size_t i = 0; i < r->token_stream.count; i++) {
      const TokenObservation *o = &r->token_stream.observations[i];
      if ((o->tag == TOKEN_C || o->tag == TOKEN_XC) &&
          o->model_state.kind != MODEL_UNCHANGED && o->line < line)
        model =
            o->model_state.kind == MODEL_SET ? o->model_state.model : (Str){0};
    }
  return model.n ? model : STR_LIT("unknown");
}
typedef struct {
  Str id;
  CorpusStrings paths;
  Omap displays;
} Duplicate;
static Err diagnostic_path(Corpus *c, Str id, Str path) {
  CorpusStrings *paths = omap_get(&c->duplicate_ids, id);
  if (!paths) {
    TRY(alloc(&c->usage_arena, 1, sizeof *paths, _Alignof(CorpusStrings),
              (void **)&paths));
    TRY(omap_put(&c->duplicate_ids, id, paths));
  }
  for (size_t i = 0; i < paths->count; i++)
    if (str_equal(paths->items[i], path))
      return ERR_SUCCESS;
  return strings(&c->usage_arena, paths, path);
}
static int text_order(const void *a, const void *b, void *ctx) {
  (void)ctx;
  return str_compare(*(const Str *)a, *(const Str *)b);
}
static void sum_unit(UsageSummary *s, const UsageUnit *u) {
  s->input += u->input;
  s->cached += u->cached;
  s->cache_write += u->cache_write;
  s->output += u->output;
  if (u->reasoning.present)
    s->reasoning += u->reasoning.value;
  s->count++;
}
static void note_sum(const UsageSummary *s, const char *site) {
  const char *names[] = {"input", "cached_input", "cache_write", "output",
                         "reasoning"};
  __int128 values[] = {s->input, s->cached, s->cache_write, s->output,
                       s->reasoning};
  for (size_t i = 0; i < 5; i++)
    if (values[i] < INT64_MIN || values[i] > INT64_MAX) {
      char path[128];
      snprintf(path, sizeof path, "%s.%s", site, names[i]);
      event_note("int128_payload_sum", path, 1);
    }
}
static int bucket_order(const void *a, const void *b, void *context) {
  (void)context;
  const UsageBucket *x = a, *y = b;
  if (x->bucket.present != y->bucket.present)
    return x->bucket.present ? -1 : 1;
  if (x->bucket.value != y->bucket.value)
    return (x->bucket.value > y->bucket.value) -
           (x->bucket.value < y->bucket.value);
  int cmp = str_compare(x->model, y->model);
  if (cmp)
    return cmp;
  return x->priority == y->priority ? 0 : x->priority ? -1 : 1;
}
static Err bucket_key(JsonWriter *key, MaybeMs bucket, Str model, bool priority) {
  jsonw_raw(key, "[");
  if (bucket.present) jsonw_i64(key, bucket.value); else jsonw_raw(key, "null");
  jsonw_raw(key, ",");jsonw_string(key, model);
  jsonw_raw(key, priority ? ",true]" : ",false]");
  return key->error;
}
Err compose_aggregate_session(Corpus *c, SessionModel *s) {
  TRY(alloc(&c->usage_arena, 1, sizeof *s->own_usage, _Alignof(UsageSummary),
            (void **)&s->own_usage));
  TRY(alloc(&c->usage_arena, 1, sizeof *s->outside_usage,
            _Alignof(UsageSummary), (void **)&s->outside_usage));
  TRY(alloc(&c->usage_arena, s->unit_count, sizeof *s->buckets,
            _Alignof(UsageBucket), (void **)&s->buckets));
  s->own_usage->has_cost = s->unit_count == 0;
  s->outside_usage->has_cost = true;
  Omap groups = {0}, turns = {0};
  Err error = ERR_SUCCESS;
  for (size_t i = 0; i < s->turn_count; i++) {
    error = alloc(&c->usage_arena, 1, sizeof *s->turns[i].usage,
                  _Alignof(UsageSummary), (void **)&s->turns[i].usage);
    if (error.code)
      goto done;
    s->turns[i].usage->has_cost = true;
    error = omap_put(&turns, s->turns[i].id, s->turns[i].usage);
    if (error.code)
      goto done;
  }
  for (size_t i = 0; i < s->unit_count; i++) {
    const UsageUnit *u = &s->units[i];
    sum_unit(s->own_usage, u);
    UsageSummary *turn =
        u->display_turn.p ? omap_get(&turns, u->display_turn) : NULL;
    if (turn)
      sum_unit(turn, u);
    else if (!u->display_turn.p)
      sum_unit(s->outside_usage, u);
    if (turn) turn->has_cost = false;
    else if (!u->display_turn.p) s->outside_usage->has_cost = false;
    MaybeMs bucket = {.present = u->at_ms.present};
    if (bucket.present)
      floordiv_i64(u->at_ms.value, 900000, &bucket.value);
    JsonWriter key = {0};
    error = bucket_key(&key, bucket, u->model, u->priority_tier);
    if (error.code) {
      jsonw_free(&key);
      goto done;
    }
    Str identity = {key.data, (uint32_t)key.length};
    UsageBucket *b = omap_get(&groups, identity);
    if (!b) {
      b = &s->buckets[s->bucket_count++];
      b->bucket = bucket;
      b->model = u->model;
      b->priority = u->priority_tier;
      error = omap_put(&groups, identity, b);
    }
    jsonw_free(&key);
    if (error.code)
      goto done;
    sum_unit(&b->usage, u);
  }
  error = stable_sort(s->buckets, s->bucket_count, sizeof *s->buckets,
                      bucket_order, NULL);
  if (error.code)
    goto done;
  note_sum(s->own_usage, "session.own_usage");
  note_sum(s->outside_usage, "session.outside_usage");
  for (size_t i = 0; i < s->turn_count; i++)
    note_sum(s->turns[i].usage, "turn.usage");
  for (size_t i = 0; i < s->bucket_count; i++)
    note_sum(&s->buckets[i].usage, "session.buckets.*");
done:
  omap_destroy(&groups);
  omap_destroy(&turns);
  return error;
}
static int priced_order(const void *a,const void *b,void *unused) {
  (void)unused;const PricedBy *x=a,*y=b;int c=str_compare(x->period.model,y->period.model);
  if(c)return c;
  if(x->period.index!=y->period.index)return x->period.index<y->period.index?-1:1;
  return x->priority==y->priority?0:x->priority?-1:1;
}
static void reset_cost(UsageSummary *s,bool available) {
  s->has_cost=available;s->cost_usd=0.0;s->unpriced_tokens=0;s->priced_count=0;
}
static Err add_period(Arena *arena,UsageSummary *s,PricePeriod period,bool priority) {
  if(!period.present)return ERR_SUCCESS;
  PricedBy value={period,priority};
  for(size_t i=0;i<s->priced_count;i++)if(!priced_order(&s->priced_by[i],&value,NULL))return ERR_SUCCESS;
  return record_append(arena,(void **)&s->priced_by,&s->priced_count,&s->priced_capacity,sizeof value,&value);
}
static Err sum_cost(Arena *arena,UsageSummary *s,const UsageUnit *unit,bool available) {
  if(unit->has_cost)s->cost_usd+=unit->cost_usd;
  else {s->has_cost=false;if(available)s->unpriced_tokens+=unit->input+unit->output;}
  TRY(add_period(arena,s,unit->period,false));return add_period(arena,s,unit->priority_period,true);
}
static Err finish_cost(UsageSummary *s,const char *site) {
  if(s->unpriced_tokens<INT64_MIN||s->unpriced_tokens>INT64_MAX)event_note("int128_payload_sum",site,1);
  return stable_sort(s->priced_by,s->priced_count,sizeof *s->priced_by,priced_order,NULL);
}
Err compose_refresh_costs(Corpus *corpus,bool available) {
  bool codex_available=available;
  for(OmapEntry *entry=corpus->sessions.first;entry;entry=entry->next) {
    SessionModel *s=entry->value;Omap turns={0},buckets={0};Err error=ERR_SUCCESS;
    available=s->provider==PROVIDER_CLAUDE?true:codex_available;
    reset_cost(s->own_usage,available);reset_cost(s->outside_usage,available);
    for(size_t i=0;i<s->turn_count;i++){reset_cost(s->turns[i].usage,available);error=omap_put(&turns,s->turns[i].id,s->turns[i].usage);if(error.code)goto done;}
    for(size_t i=0;i<s->bucket_count;i++) {
      UsageBucket *b=&s->buckets[i];reset_cost(&b->usage,available);JsonWriter key={0};
      error=bucket_key(&key,b->bucket,b->model,b->priority);
      if(!error.code)error=omap_put(&buckets,(Str){key.data,(uint32_t)key.length},&b->usage);
      jsonw_free(&key);if(error.code)goto done;
    }
    for(size_t i=0;i<s->unit_count;i++) {
      UsageUnit *u=&s->units[i];error=sum_cost(&corpus->usage_arena,s->own_usage,u,available);if(error.code)goto done;
      UsageSummary *turn=u->display_turn.p?omap_get(&turns,u->display_turn):s->outside_usage;
      if(turn){error=sum_cost(&corpus->usage_arena,turn,u,available);if(error.code)goto done;}
      MaybeMs bucket={.present=u->at_ms.present};if(bucket.present)floordiv_i64(u->at_ms.value,900000,&bucket.value);
      JsonWriter key={0};error=bucket_key(&key,bucket,u->model,u->priority_tier);
      UsageSummary *b=error.code?NULL:omap_get(&buckets,(Str){key.data,(uint32_t)key.length});jsonw_free(&key);
      if(error.code)goto done;
      if(!b){error=err_make(ERR_INVALID,"missing composed bucket");goto done;}
      error=sum_cost(&corpus->usage_arena,b,u,available);if(error.code)goto done;
    }
    error=finish_cost(s->own_usage,"session.own_usage.unpriced_tokens");if(error.code)goto done;
    error=finish_cost(s->outside_usage,"session.outside_usage.unpriced_tokens");if(error.code)goto done;
    for(size_t i=0;i<s->turn_count;i++){error=finish_cost(s->turns[i].usage,"turn.usage.unpriced_tokens");if(error.code)goto done;}
    for(size_t i=0;i<s->bucket_count;i++){error=finish_cost(&s->buckets[i].usage,"session.buckets.*.unpriced_tokens");if(error.code)goto done;}
done:
    omap_destroy(&turns);omap_destroy(&buckets);if(error.code)return error;
  }
  return ERR_SUCCESS;
}
static Err duplicates(Corpus *c, LogRecord *const *records, size_t count) {
  Omap groups = {0};
  Err error = ERR_SUCCESS;
  for (size_t i = 0; i < count; i++) {
    LogRecord *r = records[i];
    if (!r->token_stream.has_prepass || !r->token_stream.prepass.session_id.p)
      continue;
    Str id = r->token_stream.prepass.session_id, key;
    error = canon(&c->usage_arena, id, &key);
    if (error.code)
      goto done;
    Duplicate *d = omap_get(&groups, key);
    if (!d) {
      error = alloc(&c->usage_arena, 1, sizeof *d, _Alignof(Duplicate),
                    (void **)&d);
      if (error.code)
        goto done;
      d->id = id;
      error = omap_put(&groups, key, d);
      if (error.code)
        goto done;
    }
    error = strings(&c->usage_arena, &d->paths, r->key.path);
    if (error.code)
      goto done;
    Str display = r->meta.id, display_key;
    if (!str_trim(display, true).n)
      display = (Str){0};
    if (display.p) {
      error = canon(&c->usage_arena, display, &display_key);
      if (error.code)
        goto done;
      if (!str_equal(display_key, key)) {
        CorpusStrings *paths = omap_get(&d->displays, display);
        if (!paths) {
          error = alloc(&c->usage_arena, 1, sizeof *paths,
                        _Alignof(CorpusStrings), (void **)&paths);
          if (error.code)
            goto done;
          error = omap_put(&d->displays, display, paths);
          if (error.code)
            goto done;
        }
        error = strings(&c->usage_arena, paths, r->key.path);
        if (error.code)
          goto done;
      }
    }
  }
  for (OmapEntry *p = groups.first; p; p = p->next) {
    Duplicate *d = p->value;
    if (d->paths.count <= 1)
      continue;
    for (size_t i = 0; i < d->paths.count; i++) {
      error = diagnostic_path(c, d->id, d->paths.items[i]);
      if (error.code)
        goto done;
    }
    for (OmapEntry *q = d->displays.first; q; q = q->next) {
      CorpusStrings *paths = q->value;
      for (size_t i = 0; i < paths->count; i++) {
        error = diagnostic_path(c, q->key, paths->items[i]);
        if (error.code)
          goto done;
      }
    }
  }
  for (OmapEntry *p = c->duplicate_ids.first; p; p = p->next) {
    CorpusStrings *paths = p->value;
    error =
        stable_sort(paths->items, paths->count, sizeof(Str), text_order, NULL);
    if (error.code)
      goto done;
  }
  for (OmapEntry *p = c->duplicate_ids.first; p; p = p->next) {
    error = strings(&c->usage_arena, &c->duplicate_order, p->key);
    if (error.code)
      goto done;
  }
  error = stable_sort(c->duplicate_order.items, c->duplicate_order.count,
                      sizeof(Str), text_order, NULL);
done:
  for (OmapEntry *p = groups.first; p; p = p->next)
    omap_destroy(&((Duplicate *)p->value)->displays);
  omap_destroy(&groups);
  return error;
}
/* Latest started turn and active context strictly before this record.
 * A started observation without a turn clears currentTurnID; truncated
 * contexts carry no turn and preserve activeTurnID. */
static void turns_before(const LogRecord *r, uint64_t line, Str *started, Str *context) {
  *started = *context = (Str){0};
  for (size_t i = 0; i < r->token_stream.count; i++) {
    const TokenObservation *o = &r->token_stream.observations[i];
    if (o->line >= line)
      break;
    if (o->tag == TOKEN_S)
      *started = o->turn_id;
    else if (o->tag == TOKEN_C && o->turn_id.n)
      *context = o->turn_id;
  }
}
static Str request_turn_at(const LogRecord *r, uint64_t line) {
  Str started, context;
  turns_before(r, line, &started, &context);
  return started.n ? started : context;
}
typedef struct {
  bool *matched;
  Str *keys, *observations;
} FileMirrors;
static RequestTotals raw_totals(TokenTotals t) {
  return (RequestTotals){t.input, t.cached, t.output, t.has_reasoning ? t.reasoning : 0};
}
static int pair_event_order(const void *left, const void *right, void *context) {
  (void)context;
  uint64_t a = ((const PairEvent *)left)->line, b = ((const PairEvent *)right)->line;
  return (a > b) - (a < b);
}
Err compose_usage(Corpus *c, const PriorityTurns *priority) {
  compose_destroy(c);
  size_t count = c->skipped_count;
  size_t rejected = 0;
  for (OmapEntry *p = c->sessions.first; p; p = p->next) {
    SessionModel *s = p->value;
    if (s->record_count > SIZE_MAX - count)
      return err_make(ERR_NOMEM, "composition record count overflow");
    count += s->record_count;
    s->flags &= ~F_FORK_BASELINE;
  }
  LogRecord **records = calloc(count ? count : 1, sizeof *records);
  AccountingResult *results = calloc(count ? count : 1, sizeof *results);
  InheritedResolver resolver = {0};
  Omap indexes = {0}, by_path = {0}, normalizations={0};
  Err error = ERR_SUCCESS;
  if (!records || !results) {
    error = err_make(ERR_NOMEM, "composition accounting allocation failed");
    goto done;
  }
  size_t offset = 0;
  for (OmapEntry *p = c->sessions.first; p; p = p->next) {
    SessionModel *s = p->value;
    for (size_t i = 0; i < s->record_count; i++)
      records[offset++] = (LogRecord *)s->records[i];
  }
  for (size_t i = 0; i < c->skipped_count; i++)
    records[offset++] = (LogRecord *)c->skipped[i];
  error = accounting_logs(records, count, &resolver, results);
  if (error.code)
    goto done;
  for (size_t i = 0; i < count; i++) {
    error = omap_put(&by_path, records[i]->key.path, &results[i]);
    if (error.code)
      goto done;
  }
  error = duplicates(c, records, count);
  if (error.code)
    goto done;
  for (PriorityMessage *m = priority->messages; m; m = m->next) {
    error = strings(&c->usage_arena, &c->trace_messages, m->text);
    if (error.code)
      goto done;
  }
  for (OmapEntry *p = priority->turns.first; p; p = p->next) {
    Str id;
    error = canon(&c->usage_arena, p->key, &id);
    if (error.code)
      goto done;
    error = omap_put(&indexes, id, p->value);
    if (error.code)
      goto done;
  }
  for (OmapEntry *p = c->sessions.first; p; p = p->next) {
    SessionModel *s = p->value;
    Omap display = {0}, responses = {0}, mirrored = {0}, seen = {0}, file_responses = {0};
    if (s->provider == PROVIDER_CLAUDE) {
      continue;
    }
    FileMirrors *files = NULL;
    Omap *thread_priority = NULL;
    error = alloc(&c->usage_arena, s->record_count, sizeof *files, _Alignof(FileMirrors), (void **)&files);
    if (error.code) goto session_done;
    error = alloc(&c->usage_arena, s->record_count, sizeof *thread_priority,
                  _Alignof(Omap), (void **)&thread_priority);
    if (error.code) goto session_done;
    Str session;
    error = canon(&c->usage_arena, s->id, &session);
    if (error.code)
      goto session_done;
    for (size_t i = 0; i < s->turn_count; i++) {
      Str id;
      error = canon(&c->usage_arena, s->turns[i].id, &id);
      if (error.code)
        goto session_done;
      error = omap_put(&display, id, &s->turns[i].id);
      if (error.code)
        goto session_done;
    }
    for (size_t file = 0; file < s->record_count; file++) {
      omap_destroy(&file_responses);
      const LogRecord *r = s->records[file];
      error = thread_priority_starts(&c->usage_arena, r, &thread_priority[file]);
      if (error.code) goto session_done;
      Str request_session = token_model_trim(r->meta.request_session_id);
      if (!request_session.n)
        request_session = s->id;
      error = canon(&c->usage_arena, request_session, &request_session);
      if (error.code)
        goto session_done;
      AccountingResult *result = omap_get(&by_path, r->key.path);
      if (result->unresolved)
        s->flags |= F_FORK_BASELINE;
      for (size_t i = 0; i < result->row_count; i++)
        result->rows[i].file = (int64_t)file;
      PairSide *ledgers = NULL, *snapshots = NULL;
      PairEvent *events = NULL;
      size_t *snapshot_rows = NULL;
      bool *matched = NULL;
      size_t event_count = 0, ledger_count = 0, snapshot_count = 0;
      if (r->usage_count > SIZE_MAX - result->row_count ||
          r->usage_count + result->row_count > SIZE_MAX - r->token_stream.count) {
        error = err_make(ERR_NOMEM, "request event count overflow"); goto session_done;
      }
#define PAIR_ALLOC(n, ptr, type) do { \
  error = alloc(&c->usage_arena, (n), sizeof(type), _Alignof(type), (void **)&(ptr)); \
  if (error.code) goto session_done; \
} while (0)
      PAIR_ALLOC(r->usage_count, ledgers, PairSide);
      PAIR_ALLOC(result->row_count, snapshots, PairSide);
      PAIR_ALLOC(result->row_count, snapshot_rows, size_t);
      PAIR_ALLOC(result->row_count, matched, bool);
      PAIR_ALLOC(r->usage_count + result->row_count + r->token_stream.count, events, PairEvent);
      PAIR_ALLOC(result->row_count, files[file].matched, bool);
      PAIR_ALLOC(result->row_count, files[file].keys, Str);
      PAIR_ALLOC(result->row_count, files[file].observations, Str);
#undef PAIR_ALLOC
      const UsageRecord **ordered = NULL;
      error = alloc(&c->usage_arena, r->usage_count, sizeof *ordered,
                    _Alignof(UsageRecord *), (void **)&ordered);
      if (error.code)
        goto session_done;
      for (size_t i = 0; i < r->usage_count; i++)
        ordered[i] = &r->usage_records[i];
      error = stable_sort(ordered, r->usage_count, sizeof *ordered, usage_order,
                          NULL);
      if (error.code)
        goto session_done;
      for (size_t i = 0; i < r->usage_count; i++) {
        const UsageRecord *u = ordered[i];
        LedgerRecord ledger;
        LedgerVerdict verdict;
        error = ledger_record_accept(&c->usage_arena, u, session, request_session, &ledger, &verdict);
        if (error.code)
          goto session_done;
        if (verdict == LEDGER_FOREIGN)
          continue;
        if (verdict == LEDGER_INVALID) {
          rejected++;
          continue;
        }
        Str turn = ledger.turn_id.n ? ledger.turn_id : request_turn_at(r, u->line), turn_key = {0};
        if (turn.p) {
          error = canon(&c->usage_arena, turn, &turn_key);
          if (error.code)
            goto session_done;
        }
        Str response;
        error = canon(&c->usage_arena, ledger.response_id, &response);
        if (error.code) goto session_done;
        PairSide side = {.turn = turn_key, .usage = ledger.usage, .has_total = true,
                         .total = ledger.thread_total, .has_turn_total = ledger.has_turn_total,
                         .turn_total = ledger.turn_total, .timestamp = ledger.timestamp, .ms = ledger.timestamp_ms,
                         .replay = omap_get(&file_responses, response) != NULL, .response_id = response};
        if (!side.replay) {
          error = omap_put(&file_responses, response, (void *)1);
          if (error.code) goto session_done;
        }
        ledgers[ledger_count] = side;
        events[event_count++] = (PairEvent){PAIR_LEDGER, u->line, ledger_count++};
        /* Each accepted record aliases its thread, absent and optional turn total. */
        if (!result->unresolved) {
          Str keys[3]; size_t key_count;
          error = request_record_mirror_keys(&c->usage_arena, session, &side, keys, &key_count);
          for (size_t k = 0; k < key_count && !error.code; k++)
            error = omap_put(&mirrored, keys[k], (void *)1);
        }
        if (error.code) goto session_done;
        if (omap_get(&responses, response)) continue;
        error = omap_put(&responses, response, (void *)1);
        if (error.code) goto session_done;
        UsageUnit unit = {.file = file,
                          .line = u->line,
                          .turn_id = turn,
                          .at_ms = u->at_ms,
                          .timestamp_ms = ledger.timestamp_ms,
                          .model_raw = model_at(r, result, u->line),
                          .input = ledger.usage.input,
                          .cached = ledger.usage.cached,
                          .cache_write = positive(u->cache_write),
                          .output = ledger.usage.output,
                          .reasoning = {ledger.has_reasoning, ledger.usage.reasoning},
                          .source = STR_LIT("record")};
        error = append(c, s, &display, &indexes, &thread_priority[file], &normalizations, unit);
        if (error.code)
          goto session_done;
      }
      for (size_t i = 0; i < result->row_count; i++) {
        AccountingRow *row = &result->rows[i];
        if (row->bare) {
          events[event_count++] = (PairEvent){PAIR_BOUNDARY, row->line, 0}; continue;
        }
        Str turn = row->turn_id;
        if (!turn.n) { Str started; turns_before(r, row->line, &started, &turn); }
        PairSide side = {.usage = raw_totals(row->raw_last.present ? row->raw_last : row->tokens),
                         .has_total = row->raw_total.present, .total = raw_totals(row->raw_total),
                         .timestamp = row->timestamp, .ms = row->timestamp_ms,
                         .observation_key = !row->raw_last.present};
        error = canon(&c->usage_arena, turn, &side.turn);
        if (!error.code) error = request_mirror_key(&c->usage_arena, session, &side, true, &files[file].keys[i]);
        if (!error.code && !row->raw_last.present)
          error = request_mirror_key(&c->usage_arena, session, &side, false, &files[file].observations[i]);
        if (error.code) goto session_done;
        snapshots[snapshot_count] = side;
        snapshot_rows[snapshot_count] = i;
        events[event_count++] = (PairEvent){PAIR_SNAPSHOT, row->line, snapshot_count++};
      }
      bool leaf_seen = false;
      for (size_t i = 0; i < r->token_stream.count; i++) {
        const TokenObservation *o = &r->token_stream.observations[i];
        if (o->tag == TOKEN_S || o->tag == TOKEN_C || o->tag == TOKEN_XC)
          events[event_count++] = (PairEvent){PAIR_BOUNDARY, o->line, 0};
        else if (o->tag == TOKEN_M) {
          Str id;
          error = canon(&c->usage_arena, o->meta.session_id, &id);
          if (error.code) goto session_done;
          if (str_equal(id, session)) {
            if (leaf_seen) events[event_count++] = (PairEvent){PAIR_RESTART, o->line, 0};
            leaf_seen = true;
          }
        }
      }
      error = stable_sort(events, event_count, sizeof *events, pair_event_order, NULL);
      if (!error.code) error = request_pair_file(snapshots, snapshot_count, ledgers, ledger_count, events, event_count, matched);
      if (error.code) goto session_done;
      for (size_t k = 0; k < snapshot_count; k++) {
        if (!matched[k]) continue;
        size_t i = snapshot_rows[k];
        files[file].matched[i] = true;
        if (result->unresolved) continue;
        error = omap_put(&mirrored, files[file].keys[i], (void *)1);
        if (!error.code && files[file].observations[i].n)
          error = omap_put(&mirrored, files[file].observations[i], (void *)1);
        if (error.code) goto session_done;
      }
    }
    if (s->flags & F_FORK_BASELINE) {
      error = strings(&c->usage_arena, &c->fork_baselines, s->id);
      if (error.code)
        goto session_done;
    }
    for (size_t file = 0; file < s->record_count; file++) {
      Omap accepted = {0};
      AccountingResult *result = omap_get(&by_path, s->records[file]->key.path);
      for (size_t i = 0; i < result->row_count; i++) {
        AccountingRow *row = &result->rows[i];
        Str key;
        if (!row->bare && (files[file].matched[i] || omap_get(&mirrored, files[file].keys[i]) ||
                           (files[file].observations[i].n && omap_get(&mirrored, files[file].observations[i]))))
          continue;
        error = compose_row_key(&c->usage_arena, result->session_id,
                                s->records[file]->key.path, row, &key);
        if (error.code)
          break;
        if (omap_get(&seen, key))
          continue;
        error = omap_put(&accepted, key, (void *)1);
        if (error.code)
          break;
        UsageUnit unit = {
            .file = (size_t)row->file,
            .line = row->line,
            .turn_id = row->turn_id,
            .at_ms = {true, row->at_ms},
            .timestamp_ms = row->timestamp_ms,
            .model_raw = row->model_raw,
            .input = row->tokens.input,
            .cached = row->tokens.cached,
            .output = row->tokens.output,
            .reasoning = {row->tokens.has_reasoning, row->tokens.reasoning},
            .source = row->bare ? STR_LIT("bare") : STR_LIT("token_count")};
        error = append(c, s, &display, &indexes, &thread_priority[file], &normalizations, unit);
        if (error.code)
          break;
      }
      if (!error.code)
        for (OmapEntry *q = accepted.first; q; q = q->next) {
          error = omap_put(&seen, q->key, (void *)1);
          if (error.code)
            break;
        }
      omap_destroy(&accepted);
      if (error.code)
        goto session_done;
    }
  session_done:
    if (thread_priority)
      for (size_t file = 0; file < s->record_count; file++)
        omap_destroy(&thread_priority[file]);
    if (!error.code)
      error = compose_aggregate_session(c, s);
    omap_destroy(&display);
    omap_destroy(&responses);
    omap_destroy(&mirrored);
    omap_destroy(&file_responses);
    omap_destroy(&seen);
    if (error.code)
      goto done;
  }
  if (rejected)
    event_note("usage_record_rejected", "compose.token_usage_record", rejected);
  for (unsigned char code = 4; code < 7; code++) {
    bool found = false;
    for (size_t i = 0; i < c->diagnostic_order_count; i++)
      if (c->diagnostic_order[i] == code)
        found = true;
    if (!found)
      c->diagnostic_order[c->diagnostic_order_count++] = code;
  }
  c->composed = true;
done:
  if (results)
    for (size_t i = 0; i < count; i++)
      accounting_result_destroy(&results[i]);
  resolver_destroy(&resolver);
  omap_destroy(&indexes);
  omap_destroy(&by_path);
  omap_destroy(&normalizations);
  free(results);
  free(records);
  return error;
}
void compose_summary_json(JsonWriter *w, const UsageSummary *value) {
  UsageSummary empty = {.has_cost=true};
  const UsageSummary *s = value ? value : &empty;
  jsonw_raw(w, "{\"input\":");
  jsonw_i128(w, s->input);
  jsonw_raw(w, ",\"cached_input\":");
  jsonw_i128(w, s->cached);
  jsonw_raw(w, ",\"cache_write\":");
  jsonw_i128(w, s->cache_write);
  jsonw_raw(w, ",\"output\":");
  jsonw_i128(w, s->output);
  jsonw_raw(w, ",\"reasoning\":");
  jsonw_i128(w, s->reasoning);
  jsonw_raw(w,",\"cost_usd\":");if(s->has_cost)jsonw_double(w,s->cost_usd);else jsonw_raw(w,"null");
  jsonw_raw(w,",\"unpriced_tokens\":");jsonw_i128(w,s->unpriced_tokens);jsonw_raw(w,",\"priced_by\":[");
  for(size_t i=0;i<s->priced_count;i++){const PricedBy *p=&s->priced_by[i];if(i)jsonw_raw(w,",");jsonw_raw(w,"[");jsonw_string(w,p->period.model);jsonw_raw(w,",");jsonw_i128(w,p->period.index);jsonw_raw(w,",");jsonw_string(w,p->priority?STR_LIT("priority"):STR_LIT("rates"));jsonw_raw(w,"]");}
  jsonw_raw(w,"]}");
}
void compose_buckets_json(JsonWriter *w, const SessionModel *s) {
  jsonw_raw(w, "[");
  for (size_t i = 0; i < s->bucket_count; i++) {
    const UsageBucket *b = &s->buckets[i];
    if (i)
      jsonw_raw(w, ",");
    jsonw_raw(w, "[");
    if (b->bucket.present)
      jsonw_i64(w, b->bucket.value);
    else
      jsonw_raw(w, "null");
    jsonw_raw(w, ",");
    jsonw_string(w, b->model);
    jsonw_raw(w, ",");
    jsonw_string(w, b->priority ? (s->provider==PROVIDER_CLAUDE?STR_LIT("fast"):STR_LIT("priority")) : STR_LIT("standard"));
    jsonw_raw(w, ",");
    jsonw_i128(w, b->usage.input);
    jsonw_raw(w, ",");
    jsonw_i128(w, b->usage.cached);
    jsonw_raw(w, ",");
    jsonw_i128(w, b->usage.cache_write);
    jsonw_raw(w, ",");
    jsonw_i128(w, b->usage.output);
    jsonw_raw(w, ",");
    jsonw_i128(w, b->usage.reasoning);
    jsonw_raw(w, ",");if(b->usage.has_cost)jsonw_double(w,b->usage.cost_usd);else jsonw_raw(w,"null");
    jsonw_raw(w,",");jsonw_string(w,s->provider==PROVIDER_CLAUDE?STR_LIT("claude"):STR_LIT("codex"));jsonw_raw(w,"]");
  }
  jsonw_raw(w, "]");
}
static void string(JsonWriter *w, Str s) {
  if (s.p)
    jsonw_string(w, s);
  else
    jsonw_raw(w, "null");
}
void compose_duplicate_ids_json(JsonWriter *w, const Corpus *c) {
  jsonw_raw(w, "[");
  /* Diagnostic source order is sorted raw ids; rendering is observational. */
  for (size_t i = 0; i < c->duplicate_order.count; i++) {
    Str id = c->duplicate_order.items[i];
    if (i)
      jsonw_raw(w, ",");
    jsonw_raw(w, "{\"id\":");
    string(w, id);
    jsonw_raw(w, ",\"paths\":[");
    CorpusStrings *paths = omap_get(&c->duplicate_ids, id);
    for (size_t j = 0; j < paths->count; j++) {
      if (j)
        jsonw_raw(w, ",");
      string(w, paths->items[j]);
    }
    jsonw_raw(w, "]}");
  }
  jsonw_raw(w, "]");
}
