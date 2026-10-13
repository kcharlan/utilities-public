#include "request_ledger.h"
#include "parse/tokenstream.h"
#include "util/time.h"
#include "out/jsonw.h"
#include <math.h>
#include "util/omap.h"
#include <stdlib.h>
#include <string.h>
#define TRY(x)                                                                 \
  do {                                                                         \
    Err e_ = (x);                                                              \
    if (e_.code)                                                               \
      return e_;                                                               \
  } while (0)
/* CodexBar v0.74.1 codexRequestUsage: NSNumber (not CFBoolean), finite, >= 0,
 * < Double(Int.max), integral. Absent optional keys default to zero; null is invalid. */
static bool request_integer(JScalar v, bool required, int64_t *out) {
  *out = 0;
  if (v.kind == JS_ABSENT) return !required;
  if (v.kind == JS_INT) { *out = v.value.i; return v.value.i >= 0 && (double)v.value.i < 0x1p63; }
  if (v.kind != JS_FLOAT) return false;
  double f = v.value.f;
  if (!isfinite(f) || f < 0 || f >= 0x1p63 || trunc(f) != f) return false;
  *out = (int64_t)f;
  return true;
}
bool request_totals_decode(const UsageScalars *s, RequestTotals *out) {
  int64_t sum;
  return request_integer(s->input, true, &out->input) && request_integer(s->output, true, &out->output) &&
         request_integer(s->cached_input, false, &out->cached) &&
         request_integer(s->reasoning, false, &out->reasoning) &&
         out->cached <= out->input && out->reasoning <= out->output &&
         !__builtin_add_overflow(out->input, out->output, &sum);
}
bool request_totals_at_least(RequestTotals t, RequestTotals u) {
  return t.input >= u.input && t.cached >= u.cached && t.output >= u.output;
}
static Str trimmed(JScalar v) { return v.kind == JS_STRING ? token_model_trim(v.value.s) : (Str){0}; }
Err ledger_record_accept(Arena *a, const UsageRecord *u, Str session, Str request_session,
                         LedgerRecord *out, LedgerVerdict *verdict) {
  *out = (LedgerRecord){0};
  *verdict = LEDGER_INVALID;
  Str thread = trimmed(u->thread_id), identity;
  if (!thread.n) return ERR_SUCCESS;
  TRY(str_nfc(a, thread, "ledger.thread", &identity));
  if (!str_equal(identity, session)) { *verdict = LEDGER_FOREIGN; return ERR_SUCCESS; }
  if (u->session_id.kind != JS_ABSENT) {
    Str sid = trimmed(u->session_id);
    if (!sid.n) return ERR_SUCCESS;
    TRY(str_nfc(a, sid, "ledger.session", &identity));
    if (!str_equal(identity, request_session)) { *verdict = LEDGER_FOREIGN; return ERR_SUCCESS; }
  }
  Str response = trimmed(u->response_id), ts = u->ts.kind == JS_STRING ? u->ts.value.s : (Str){0};
  char day[11];
  int64_t ms;
  if (!response.n || !ts.n ||
      (!time_day_key(ts, "ledger.timestamp", day, &ms) && !time_day_key_iso(ts, "ledger.timestamp", day, &ms)))
    return ERR_SUCCESS;
  UsageScalars usage = {u->input, u->cached_input, u->output, u->reasoning};
  if (!request_totals_decode(&usage, &out->usage) || !request_totals_decode(&u->thread_usage, &out->thread_total) ||
      !request_totals_at_least(out->thread_total, out->usage))
    return ERR_SUCCESS;
  out->has_turn_total = request_totals_decode(&u->turn_usage, &out->turn_total) &&
                        request_totals_at_least(out->turn_total, out->usage);
  out->response_id = response;
  out->timestamp = ts;
  out->timestamp_ms = u->timestamp_unix_ms;
  out->turn_id = u->turn_id.kind == JS_STRING && u->turn_id.value.s.n ? u->turn_id.value.s : (Str){0};
  out->has_reasoning = u->reasoning.kind != JS_ABSENT;
  *verdict = LEDGER_ACCEPTED;
  return ERR_SUCCESS;
}
enum { NEAR_WINDOW_MS = 5000 };
/* Shared canonical mirror identity for chronological ownership and cross-copy aliases. */
Err request_mirror_key(Arena *a, Str session, const PairSide *side, bool with_usage, Str *out) {
  JsonWriter w = {0};
  jsonw_bytes(&w, session.p, session.n);
  jsonw_raw(&w, "\x1f");
  jsonw_bytes(&w, side->turn.p, side->turn.n);
  const int64_t usage[] = {side->usage.input, side->usage.cached, side->usage.output, side->usage.reasoning};
  for (size_t i = 0; i < 4; i++) { jsonw_raw(&w, "\x1f"); if (with_usage) jsonw_i64(&w, usage[i]); }
  const int64_t total[] = {side->total.input, side->total.cached, side->total.output};
  for (size_t i = 0; i < 3; i++) { jsonw_raw(&w, "\x1f"); if (side->has_total) jsonw_i64(&w, total[i]); }
  jsonw_raw(&w, "\x1f");
  jsonw_bytes(&w, side->timestamp.p, side->timestamp.n);
  Err e = w.error;
  if (!e.code) e = str_nfc(a, (Str){w.data, (uint32_t)w.length}, "composition.identity", out);
  jsonw_free(&w);
  return e;
}
Err request_record_mirror_keys(Arena *a, Str session, const PairSide *side, Str keys[3], size_t *count) {
  *count = 0;
  PairSide alias = *side;
  TRY(request_mirror_key(a, session, &alias, true, &keys[(*count)++]));
  alias.has_total = false;
  TRY(request_mirror_key(a, session, &alias, true, &keys[(*count)++]));
  if (side->has_turn_total) {
    alias.has_total = true; alias.total = side->turn_total;
    TRY(request_mirror_key(a, session, &alias, true, &keys[(*count)++]));
  }
  return ERR_SUCCESS;
}
typedef enum { ADVANCE_UNKNOWN, ADVANCE_BOUNDED, ADVANCE_EXACT, ADVANCE_INTERVENING } Advance;
static bool same_counts(RequestTotals a, RequestTotals b) {
  return a.input == b.input && a.cached == b.cached && a.output == b.output;
}
/* nearMirror key: turn, input, cached, output (no reasoning). */
static bool same_near_key(const PairSide *a, const PairSide *b) {
  return str_equal(a->turn, b->turn) && same_counts(a->usage, b->usage);
}
/* mirrorKey usage: also reasoning (reasoning ?? 0). */
static bool same_mirror_usage(const PairSide *a, const PairSide *b) {
  return same_near_key(a, b) && a->usage.reasoning == b->usage.reasoning;
}
/* CodexNearMirror.CounterAdvance relative to the same kind's previous total. */
static Advance advance(bool has_previous, RequestTotals previous, const PairSide *side) {
  if (!has_previous || !side->has_total) return ADVANCE_UNKNOWN;
  int64_t step[3], own[3] = {side->usage.input, side->usage.cached, side->usage.output};
  if (__builtin_sub_overflow(side->total.input, previous.input, &step[0]) ||
      __builtin_sub_overflow(side->total.cached, previous.cached, &step[1]) ||
      __builtin_sub_overflow(side->total.output, previous.output, &step[2]))
    return ADVANCE_UNKNOWN;
  if (step[0] == own[0] && step[1] == own[1] && step[2] == own[2]) return ADVANCE_EXACT;
  for (size_t i = 0; i < 3; i++)
    if (step[i] > own[i]) return ADVANCE_INTERVENING;
  return ADVANCE_BOUNDED;
}
/* handleRequestLedger keys / legacyRowIndices: these carry the timestamp. */
static bool exact_mirror(const PairSide *t, const PairSide *l) {
  if (!same_mirror_usage(t, l) || !str_equal(t->timestamp, l->timestamp)) return false;
  return !t->has_total || same_counts(t->total, l->total) ||
         (l->has_turn_total && same_counts(t->total, l->turn_total));
}
/* adjacentMirrorKeys + CodexNearMirror.matches; only the later side's advance can veto. */
static bool adjacent_mirror(const PairSide *t, Advance ta, const PairSide *l, Advance la, bool snapshot_later) {
  if (same_mirror_usage(t, l) &&
      ((t->has_total && same_counts(t->total, l->total)) || str_equal(t->timestamp, l->timestamp)))
    return true;
  if (!same_near_key(t, l) || !t->turn.n || l->replay || !t->ms.present || !l->ms.present) return false;
  int64_t gap;
  if (__builtin_sub_overflow(t->ms.value, l->ms.value, &gap) || gap == INT64_MIN) return false;
  if (gap < 0) gap = -gap;
  if (gap <= NEAR_WINDOW_MS && (snapshot_later ? ta : la) != ADVANCE_INTERVENING) return true;
  return snapshot_later && t->ms.value >= l->ms.value && ta == ADVANCE_EXACT && la == ADVANCE_EXACT;
}
typedef struct { size_t head, tail; } PairChain;
/* Index only observed sides. Future exact candidates cannot reserve a request. */
static Err observe_side(Omap *times, PairChain *chains, size_t *next, size_t i, Str time) {
  PairChain *chain = omap_get(times, time);
  if (!chain) {
    chains[i] = (PairChain){i + 1, i + 1};
    return omap_put(times, time, &chains[i]);
  }
  next[chain->tail - 1] = i + 1;
  chain->tail = i + 1;
  return ERR_SUCCESS;
}
static bool same_response(const PairSide *ledgers, size_t left, size_t right) {
  return left == right || (ledgers[left].response_id.n && ledgers[right].response_id.n &&
                          str_equal(ledgers[left].response_id, ledgers[right].response_id));
}
static Err remember_snapshot(Arena *arena, Omap *owned, const PairSide *side, size_t ledger) {
  Str key;
  TRY(request_mirror_key(arena, (Str){0}, side, true, &key));
  TRY(omap_put(owned, key, (void *)(uintptr_t)(ledger + 1)));
  if (side->observation_key) {
    TRY(request_mirror_key(arena, (Str){0}, side, false, &key));
    TRY(omap_put(owned, key, (void *)(uintptr_t)(ledger + 1)));
  }
  return ERR_SUCCESS;
}
Err request_pair_file(const PairSide *snapshots, size_t snapshot_count, const PairSide *ledgers,
                      size_t ledger_count, const PairEvent *events, size_t event_count, bool *matched) {
  bool *claimed = calloc(ledger_count ? ledger_count : 1, sizeof *claimed);
  Advance *ta = calloc(snapshot_count ? snapshot_count : 1, sizeof *ta);
  Advance *la = calloc(ledger_count ? ledger_count : 1, sizeof *la);
  size_t *tnext = calloc(snapshot_count ? snapshot_count : 1, sizeof *tnext);
  size_t *lnext = calloc(ledger_count ? ledger_count : 1, sizeof *lnext);
  PairChain *tchains = calloc(snapshot_count ? snapshot_count : 1, sizeof *tchains);
  PairChain *lchains = calloc(ledger_count ? ledger_count : 1, sizeof *lchains);
  Omap observed_t = {0}, observed_l = {0}, owned = {0};
  Arena key_arena = {0};
  Err error = ERR_SUCCESS;
  if (!claimed || !ta || !la || !tnext || !lnext || !tchains || !lchains) {
    error = err_make(ERR_NOMEM, "request pairing allocation"); goto done;
  }
  if (snapshot_count) memset(matched, 0, snapshot_count * sizeof *matched);
  enum { NONE, SNAPSHOT, LEDGER } pending = NONE;
  size_t pending_index = 0;
  bool has_t = false, has_l = false;
  RequestTotals prev_t = {0}, prev_l = {0};
  for (size_t e = 0; e < event_count && !error.code; e++) {
    const PairEvent *ev = &events[e];
    if (ev->kind == PAIR_BOUNDARY || ev->kind == PAIR_RESTART) {
      pending = NONE;
      if (ev->kind == PAIR_RESTART) has_t = has_l = false;
    } else if (ev->kind == PAIR_SNAPSHOT) {
      size_t t = ev->index, partner = 0;
      Str key;
      error = request_mirror_key(&key_arena, (Str){0}, &snapshots[t], true, &key);
      if (error.code) break;
      size_t owner = (uintptr_t)omap_get(&owned, key);
      if (!owner && snapshots[t].observation_key) {
        error = request_mirror_key(&key_arena, (Str){0}, &snapshots[t], false, &key);
        if (error.code) break;
        owner = (uintptr_t)omap_get(&owned, key);
      }
      /* beginLegacyObservation: foreign-owned repeats do not consume pending evidence. */
      if (owner && ((pending == LEDGER && !same_response(ledgers, owner - 1, pending_index)) ||
                    (pending != LEDGER && claimed[owner - 1])))
        continue;
      bool after_original = pending == LEDGER && !ledgers[pending_index].replay;
      ta[t] = advance(has_t, prev_t, &snapshots[t]);
      PairChain *chain = omap_get(&observed_l, snapshots[t].timestamp);
      for (size_t n = chain ? chain->head : 0; n && !partner; n = lnext[n - 1])
        if (!claimed[n - 1] && exact_mirror(&snapshots[t], &ledgers[n - 1])) partner = n;
      if (!partner && pending == LEDGER && !claimed[pending_index] &&
          adjacent_mirror(&snapshots[t], ta[t], &ledgers[pending_index], la[pending_index], true))
        partner = pending_index + 1;
      if (partner) {
        matched[t] = claimed[partner - 1] = true;
        error = remember_snapshot(&key_arena, &owned, &snapshots[t], partner - 1);
        if (error.code) break;
      }
      /* Unpaired snapshots, or the immediately pending original, advance history. */
      if (snapshots[t].has_total && (!matched[t] || (after_original && partner == pending_index + 1))) {
        prev_t = snapshots[t].total; has_t = true;
      }
      error = observe_side(&observed_t, tchains, tnext, t, snapshots[t].timestamp);
      pending = matched[t] ? NONE : SNAPSHOT;
      pending_index = t;
    } else if (ev->kind == PAIR_LEDGER) {
      size_t l = ev->index, partner = 0;
      la[l] = ledgers[l].replay ? ADVANCE_UNKNOWN : advance(has_l, prev_l, &ledgers[l]);
      if (!ledgers[l].replay) { prev_l = ledgers[l].total; has_l = true; }
      PairChain *chain = omap_get(&observed_t, ledgers[l].timestamp);
      for (size_t n = chain ? chain->head : 0; n && !partner; n = tnext[n - 1])
        if (!matched[n - 1] && exact_mirror(&snapshots[n - 1], &ledgers[l])) partner = n;
      if (!partner && pending == SNAPSHOT && !matched[pending_index] &&
          adjacent_mirror(&snapshots[pending_index], ta[pending_index], &ledgers[l], la[l], false))
        partner = pending_index + 1;
      if (partner) {
        matched[partner - 1] = claimed[l] = true;
        error = remember_snapshot(&key_arena, &owned, &snapshots[partner - 1], l);
        if (error.code) break;
      }
      Str keys[3]; size_t key_count;
      error = request_record_mirror_keys(&key_arena, (Str){0}, &ledgers[l], keys, &key_count);
      for (size_t k = 0; k < key_count && !error.code; k++)
        error = omap_put(&owned, keys[k], (void *)(uintptr_t)(l + 1));
      if (error.code) break;
      error = observe_side(&observed_l, lchains, lnext, l, ledgers[l].timestamp);
      pending = claimed[l] ? NONE : LEDGER;
      pending_index = l;
    }
  }
done:
  omap_destroy(&observed_t); omap_destroy(&observed_l);
  omap_destroy(&owned); arena_destroy(&key_arena);
  free(claimed); free(ta); free(la); free(tnext); free(lnext); free(tchains); free(lchains);
  return error;
}
