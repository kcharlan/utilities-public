#include "parser.h"
#include "price/model.h"
#include "resolver.h"
#include "tracker.h"
#include "util/time.h"
#include <limits.h>
#include <string.h>
#define TRY(x)                                                                 \
  do {                                                                         \
    Err e_ = (x);                                                              \
    if (e_.code)                                                               \
      return e_;                                                               \
  } while (0)
typedef struct {
  AccountingResult *r;
  InheritedResolver *resolver;
  Arena scratch;
  Omap normalizations;
  Str model, turn, last_timestamp;
  TokenMeta meta;
  Totals previous, raw, inherited, remaining;
  bool has_previous, has_raw, has_inherited, has_remaining, divergent;
  TotalsTracker tracker;
  bool captured, subagent, baseline_resolved, pending, suppress, local,
      candidate_dependency;
  CounterSemantics semantics;
  TokenObservation *lines;
  TokenObservation *buffered;
  const TokenObservation **buffered_sources;
  size_t line_count;
} Parser;
static void assign(Totals *dst, bool *has, Totals value, const char *site) {
  *dst = value;
  *has = true;
  totals_note_state(value, site);
}
static Err configure(Parser *p) {
  if (!p->r->forked_from_id.p ||
      (p->subagent && p->semantics == COUNTER_UNKNOWN))
    return ERR_SUCCESS;
  if (p->semantics == COUNTER_INDEPENDENT || p->local) {
    p->baseline_resolved = true;
    p->has_inherited = p->has_remaining = false;
    p->r->unresolved = false;
    return ERR_SUCCESS;
  }
  if (p->baseline_resolved || !p->resolver)
    return ERR_SUCCESS;
  p->baseline_resolved = true;
  ForkBaseline b;
  TRY(resolver_inherited(p->resolver, p->r->forked_from_id, p->meta.fork_ts,
                         &b));
  p->r->unresolved = !b.resolved;
  if (b.resolved && b.present) {
    assign(&p->inherited, &p->has_inherited, b.totals,
           "accounting.parser.inherited_totals");
    assign(&p->remaining, &p->has_remaining, b.totals,
           "accounting.parser.remaining_inherited_totals");
  }
  return ERR_SUCCESS;
}
static Err metadata(Parser *p, TokenMeta m) {
  if (p->captured) {
    bool same;
    TRY(accounting_same_id(&p->scratch, m.session_id, p->r->session_id, &same));
    if (!same)
      return ERR_SUCCESS;
    if (!p->r->forked_from_id.p && m.forked_from_id.p) {
      p->r->forked_from_id = m.forked_from_id;
      if (m.fork_ts.p)
        p->meta.fork_ts = m.fork_ts;
      TRY(configure(p));
    }
    if (!p->meta.project_path.p)
      p->meta.project_path = m.project_path;
    if (!p->meta.history_start_ordinal.present)
      p->meta.history_start_ordinal = m.history_start_ordinal;
    if (!p->meta.history_base_thread_id.p)
      p->meta.history_base_thread_id = m.history_base_thread_id;
  } else {
    p->captured = true;
    p->meta = m;
    p->r->session_id = m.session_id;
    p->r->forked_from_id = m.forked_from_id;
    p->subagent = m.is_subagent;
    TRY(configure(p));
  }
  return ERR_SUCCESS;
}
static Err row(Parser *p, const TokenObservation *o, Str ts, Str model,
               Str turn, Totals t, bool bare) {
  AccountingRow r = {.file = -1,
                     .line = o->line,
                     .event_index = p->r->row_count,
                     .turn_id = turn,
                     .timestamp = ts,
                     .model_raw = model,
                     .bare = bare};
  TRY(normalize_codex_model_memo(&p->r->arena,&p->normalizations,model,&r.model));
  int64_t dayms;
  if (!time_day_key(ts, "accounting.timestamp", r.day, &dayms) &&
      !time_day_key_iso(ts, "accounting.timestamp", r.day, &dayms))
    return ERR_SUCCESS;
  r.timestamp_ms.present =
      time_codex_timestamp(ts, "accounting.timestamp", &r.timestamp_ms.value);
  r.at_ms = r.timestamp_ms.present ? r.timestamp_ms.value : dayms;
  r.tokens = (TokenTotals){true,
                           t.reasoning.present,
                           (int64_t)t.input,
                           (int64_t)t.cached,
                           (int64_t)t.output,
                           (int64_t)t.reasoning.value};
  p->r->rows[p->r->row_count++] = r;
  return ERR_SUCCESS;
}
static Totals adjusted_last(Parser *p, Totals last) {
  if (!p->has_remaining)
    return last;
  Totals adjusted = totals_delta(&p->remaining, last),
         remaining = totals_delta(&last, p->remaining);
  p->has_remaining = accounting_contains(remaining);
  if (p->has_remaining)
    assign(&p->remaining, &p->has_remaining, remaining,
           "accounting.parser.remaining_inherited_totals");
  return adjusted;
}
static Totals derived(Parser *p, const Totals *water, Totals current) {
  const Totals *prev = p->has_previous ? &p->previous : NULL;
  return p->tracker.saw_interleaved
             ? totals_contained_delta(water, prev, current)
         : p->divergent ? totals_divergent_delta(water, prev, current)
                        : totals_delta(water, current);
}
static void commit(Parser *p, Totals delta, Totals raw, bool divergence) {
  Totals base = p->has_previous
                    ? p->previous
                    : (Totals){.reasoning = {delta.reasoning.present, 0}};
  assign(&p->previous, &p->has_previous, totals_add(base, delta),
         "accounting.parser.previous_totals");
  assign(&p->raw, &p->has_raw, raw, "accounting.parser.raw_totals_baseline");
  if (divergence && !totals_equal(&p->raw, &p->previous))
    p->divergent = true;
}
static Err token(Parser *p, const TokenObservation *o) {
  char day[11];
  int64_t ms;
  if (!time_day_key(o->timestamp, "accounting.timestamp", day, &ms) &&
      !time_day_key_iso(o->timestamp, "accounting.timestamp", day, &ms))
    return ERR_SUCCESS;
  if (p->suppress || p->r->unresolved)
    return ERR_SUCCESS;
  Totals total = accounting_totals(o->total), last = accounting_totals(o->last),
         delta = {0};
  if (o->total.present && o->last.present && !p->has_previous &&
      p->has_inherited && p->meta.history_base_thread_id.p) {
    bool same;
    TRY(accounting_same_id(&p->scratch, p->meta.history_base_thread_id,
                           p->r->forked_from_id, &same));
    if (!same && totals_at_least(total, last)) {
      Totals local = totals_delta(&last, total);
      if (accounting_contains(local) && totals_at_least(local, p->inherited) &&
          !totals_equal(&local, &p->inherited)) {
        assign(&p->inherited, &p->has_inherited, local,
               "accounting.parser.inherited_totals");
        assign(&p->remaining, &p->has_remaining, local,
               "accounting.parser.remaining_inherited_totals");
      }
    }
  }
  if (o->total.present && p->has_inherited)
    total = totals_delta(&p->inherited, total);
  const Totals *water = p->tracker.has_watermark ? &p->tracker.watermark
                        : p->has_raw             ? &p->raw
                                                 : NULL;
  if (o->total.present) {
    if (tracker_seen(&p->tracker, total) ||
        (water && totals_stale_regression(
                      total, *water, o->last.present ? last : (Totals){0})))
      return ERR_SUCCESS;
    tracker_latch(&p->tracker, total);
  }
  /* Capture the immutable watermark value before any later tracker mutation. */
  Totals saved;
  if (water) {
    saved = *water;
    water = &saved;
  }
  if (o->total.present && p->r->forked_from_id.p) {
    if (p->tracker.saw_interleaved) {
      Totals adjusted;
      if (o->last.present)
        adjusted = adjusted_last(p, last);
      delta =
          totals_post_latch_delta(water, p->has_previous ? &p->previous : NULL,
                                  total, o->last.present ? &adjusted : NULL);
    } else
      delta = derived(p, water, total);
    commit(p, delta, total, true);
    p->has_remaining = false;
  } else if (o->last.present) {
    bool had = p->has_remaining;
    delta = adjusted_last(p, last);
    if (o->total.present) {
      if (p->tracker.saw_interleaved) {
        delta = totals_post_latch_delta(
            water, p->has_previous ? &p->previous : NULL, total, &delta);
        p->has_remaining = false;
      } else {
        Totals td = totals_delta(water, total);
        if (!had && totals_prefer_delta(water, total, td, last, p->divergent)) {
          delta = td;
          p->has_remaining = false;
        }
      }
      commit(p, delta, total, true);
    } else {
      Totals base = p->has_previous
                        ? p->previous
                        : (Totals){.reasoning = {delta.reasoning.present, 0}};
      Totals counted = totals_add(base, delta);
      commit(p, delta, counted, false);
      tracker_raise(&p->tracker, counted);
    }
  } else if (o->total.present) {
    delta = derived(p, water, total);
    commit(p, delta, total, true);
    p->has_remaining = false;
  } else
    return ERR_SUCCESS;
  Err error = ERR_SUCCESS;
  if (accounting_contains(delta)) {
    Str model = accounting_evidence(p->model);
    if (!model.p)
      model = accounting_evidence(o->model);
    if (!model.p)
      model = STR_LIT("unknown");
    error = row(p, o, o->timestamp, model, o->turn_id.p ? o->turn_id : p->turn,
                delta, false);
  }
  if (o->total.present)
    tracker_commit(&p->tracker, total);
  return error;
}
static Err process(Parser *p, const TokenObservation *o) {
  if (o->tag == TOKEN_M)
    return metadata(p, o->meta);
  if (o->tag == TOKEN_C && o->model_state.kind != MODEL_UNCHANGED) {
    p->model =
        o->model_state.kind == MODEL_SET ? o->model_state.model : (Str){0};
    p->r->timeline[p->r->timeline_count++] =
        (ModelTimeline){(double)o->line, p->model};
  } else if (o->tag == TOKEN_S)
    p->turn = o->turn_id;
  else if (o->tag == TOKEN_T)
    return token(p, o);
  return ERR_SUCCESS;
}
static OwnedSuffix explicit_suffix(Parser *p) {
  TokenInteger start = p->meta.history_start_ordinal;
  OwnedSuffix suffix = {0};
  if (!start.present || start.value < 0)
    return suffix;
  size_t first = p->line_count;
  for (size_t i = 0; i < p->line_count; i++)
    if (p->lines[i].ordinal.present &&
        p->lines[i].ordinal.value >= start.value) {
      first = i;
      break;
    }
  if (first == p->line_count)
    return suffix;
  Totals inherited = {0};
  bool has = false;
  for (size_t i = 0; i < first; i++)
    if (p->lines[i].tag == TOKEN_T && p->lines[i].total.present) {
      inherited = accounting_totals(p->lines[i].total);
      has = true;
    }
  const TokenObservation *tok = NULL;
  for (size_t i = 0; i < p->line_count; i++) {
    const TokenObservation *o = &p->lines[i];
    if (o->tag != TOKEN_T || !o->ordinal.present ||
        o->ordinal.value < start.value)
      continue;
    Totals total = accounting_totals(o->total),
           last = accounting_totals(o->last);
    if (o->total.present && has &&
        (totals_equal(&total, &inherited) ||
         (accounting_contains(inherited) && o->last.present &&
          totals_equal(&total, &last) && totals_at_least(total, inherited)))) {
      inherited = total;
      continue;
    }
    if (o->total.present || o->last.present) {
      tok = o;
      break;
    }
  }
  if (tok && tok->last.present) {
    inherited = tok->total.present
                    ? totals_delta(&(Totals){tok->last.input,
                                             tok->last.cached,
                                             tok->last.output,
                                             {tok->last.has_reasoning,
                                              tok->last.reasoning}},
                                   accounting_totals(tok->total))
                    : (Totals){0};
    has = true;
  }
  if (has)
    suffix = (OwnedSuffix){true, true, p->lines[first].uidx,
                           tok ? tok->uidx : INT64_MAX, inherited};
  return suffix;
}
static Err replay(Parser *p) {
  for (size_t i = 0; i < p->line_count; i++)
    if (p->lines[i].tag == TOKEN_M) {
      TokenMeta m = p->lines[i].meta;
      bool same;
      TRY(accounting_same_id(&p->scratch, m.session_id, p->r->session_id,
                             &same));
      if (!same)
        continue;
      if (!p->r->forked_from_id.p && m.forked_from_id.p) {
        p->r->forked_from_id = m.forked_from_id;
        if (m.fork_ts.p)
          p->meta.fork_ts = m.fork_ts;
      }
      if (!p->meta.project_path.p)
        p->meta.project_path = m.project_path;
      if (!p->meta.history_start_ordinal.present)
        p->meta.history_start_ordinal = m.history_start_ordinal;
    }
  RolloutShape shape;
  TRY(rollout_classify(&p->scratch, p->r->session_id, p->lines, p->line_count,
                       p->r->forked_from_id.p != NULL, &shape));
  p->semantics = shape.semantics;
  if (!p->r->forked_from_id.p)
    p->r->forked_from_id = shape.inferred_parent;
  bool explicit = p->meta.history_start_ordinal.present &&
                  p->meta.history_start_ordinal.value >= 0;
  OwnedSuffix owned = explicit ? explicit_suffix(p) : shape.owned;
  if (explicit)
    p->semantics = COUNTER_COPIED;
  else if (shape.candidate.present) {
    if (shape.locally_confirmed) {
      p->semantics = COUNTER_COPIED;
      owned = shape.candidate;
    } else if (p->r->forked_from_id.p) {
      p->candidate_dependency = true;
      if (p->resolver) {
        ForkBaseline b;
        TRY(resolver_inherited(p->resolver, p->r->forked_from_id,
                               p->meta.fork_ts, &b));
        if (b.resolved && b.present &&
            totals_equal(&b.totals, &shape.parent_boundary)) {
          p->semantics = COUNTER_COPIED;
          owned = shape.candidate;
        }
      }
    }
  }
  p->local = explicit || owned.present;
  p->suppress = p->semantics == COUNTER_COPIED && !owned.present &&
                (explicit || !p->r->forked_from_id.p);
  if (owned.present) {
    p->has_previous = false;
    p->divergent = false;
    assign(&p->raw, &p->has_raw, owned.baseline,
           "accounting.parser.raw_totals_baseline");
    p->tracker = (TotalsTracker){0};
    tracker_raise(&p->tracker, owned.baseline);
    p->model = p->turn = (Str){0};
    p->r->timeline_count = 0;
    for (size_t i = 0; i < p->line_count; i++)
      if (p->lines[i].uidx == owned.start) {
        p->r->timeline[p->r->timeline_count++] =
            (ModelTimeline){(double)p->lines[i].line - 0.5, {0}};
        break;
      }
  }
  TRY(configure(p));
  for (size_t i = 0; i < p->line_count; i++) {
    const TokenObservation *o = &p->lines[i];
    if (owned.present &&
        (o->uidx < owned.start || (o->tag == TOKEN_T && owned.has_first_token &&
                                   o->uidx < owned.first_token)))
      continue;
    TRY(process(p, o));
  }
  return ERR_SUCCESS;
}
static Err array(Arena *arena,size_t count,size_t size,size_t alignment,void **out) {
  *out=NULL;
  if(count>SIZE_MAX/size)return err_make(ERR_NOMEM,"accounting array capacity overflow");
  return count?arena_alloc(arena,count*size,alignment,out):ERR_SUCCESS;
}
static Err parse(Parser *p, const TokenStream *stream) {
  AccountingResult *r = p->r;
  if(stream->count>SIZE_MAX/sizeof(TokenObservation))
    return err_make(ERR_NOMEM,"accounting observation capacity overflow");
  size_t rows=0,snapshots=0,timeline=stream->has_prepass && stream->prepass.is_subagent?1:0;
  /* Each B/T emits at most one row, T at most one snapshot, C/XC at most
   * one model transition. Pending replay replaces normal processing, never
   * repeats it; its owned suffix adds at most one timeline reset. Buffered
   * provenance and pending lines each have at most stream->count entries. */
  for(size_t i=0;i<stream->count;i++){
    TokenTag tag=stream->observations[i].tag;
    rows+=tag==TOKEN_B || tag==TOKEN_T;
    snapshots+=tag==TOKEN_T;
    timeline+=tag==TOKEN_C || tag==TOKEN_XC;
  }
  TRY(array(&r->arena, rows, sizeof *r->rows, _Alignof(AccountingRow),
                  (void **)&r->rows));
  TRY(array(&r->arena, snapshots, sizeof *r->snapshots, _Alignof(TokenSnapshot),
                  (void **)&r->snapshots));
  TRY(array(&r->arena, timeline, sizeof *r->timeline, _Alignof(ModelTimeline),
                  (void **)&r->timeline));
  TRY(array(&p->scratch, stream->count, sizeof *p->buffered,
                  _Alignof(TokenObservation), (void **)&p->buffered));
  TRY(array(&p->scratch, stream->count, sizeof *p->buffered_sources,
                  _Alignof(TokenObservation *), (void **)&p->buffered_sources));
  TRY(array(&p->scratch, stream->count, sizeof *p->lines, _Alignof(TokenObservation),
                  (void **)&p->lines));
  if (stream->has_prepass) {
    TRY(metadata(p, stream->prepass));
    p->pending = p->subagent;
  }
  for (size_t i = 0; i < stream->count; i++) {
    TokenObservation o = stream->observations[i];
    if (o.tag == TOKEN_B) {
      Str ts = o.timestamp.p ? o.timestamp : p->last_timestamp;
      size_t before = r->row_count;
      Str model = accounting_evidence(o.model);
      if (!model.p)
        model = accounting_evidence(p->model);
      if (!model.p)
        model = STR_LIT("unknown");
      TRY(row(p, &o, ts, model, p->turn, accounting_totals(o.last), true));
      if (r->row_count != before)
        p->last_timestamp = ts;
      continue;
    }
    if (o.tag == TOKEN_XC) {
      o.tag = TOKEN_C;
      o.ordinal = (TokenInteger){0};
      o.timestamp = (Str){0};
    }
    if (o.tag == TOKEN_XM) {
      if (!p->pending)
        continue;
      o.tag = TOKEN_M;
      o.ordinal = (TokenInteger){0};
    }
    if (o.tag == TOKEN_T && (o.last.present || o.total.present))
      r->snapshots[r->snapshot_count++] =
          (TokenSnapshot){o.timestamp, o.last, o.total};
    if (p->pending)
      p->lines[p->line_count++] = o;
    else {
      TRY(process(p, &o));
      if (r->unresolved) {
        p->buffered_sources[r->buffered_count] = &stream->observations[i];
        p->buffered[r->buffered_count++] = o;
      }
    }
  }
  if (p->pending && !stream->unconsumed_tail)
    TRY(replay(p));
  r->buffered_retained =
      p->line_count && (stream->unconsumed_tail || r->unresolved);
  if (r->session_id.p && r->forked_from_id.p && !p->subagent &&
      p->baseline_resolved && !r->unresolved) {
    r->has_fork_state = true;
    r->fork_metadata =
        (TokenMeta){.session_id = r->session_id,
                    .forked_from_id = r->forked_from_id,
                    .fork_ts = p->meta.fork_ts,
                    .history_base_thread_id = p->meta.history_base_thread_id};
    r->has_inherited = p->has_inherited;
    r->inherited = p->inherited;
    r->has_remaining = p->has_remaining;
    r->remaining = p->remaining;
  }
  r->depends_on_parent = r->forked_from_id.p &&
                         (p->candidate_dependency ||
                          (p->semantics != COUNTER_INDEPENDENT && !p->local));
  if (!r->unresolved)
    r->buffered_count = 0;
  TRY(array(&r->arena,r->buffered_count,sizeof *r->buffered,_Alignof(TokenObservation),(void **)&r->buffered));
  TRY(array(&r->arena,r->buffered_count,sizeof *r->buffered_sources,_Alignof(TokenObservation *),(void **)&r->buffered_sources));
  if(r->buffered_count){
    memcpy(r->buffered,p->buffered,r->buffered_count*sizeof *r->buffered);
    memcpy(r->buffered_sources,p->buffered_sources,r->buffered_count*sizeof *r->buffered_sources);
  }
  return ERR_SUCCESS;
}
Err accounting_parse(const TokenStream *s, InheritedResolver *resolver,
                     AccountingResult *out) {
  Parser p = {.r = out, .resolver = resolver};
  Err e = parse(&p, s);
  omap_destroy(&p.normalizations);
  arena_destroy(&p.scratch);
  return e;
}
void accounting_result_destroy(AccountingResult *r) {
  arena_destroy(&r->arena);
  memset(r, 0, sizeof *r);
}
