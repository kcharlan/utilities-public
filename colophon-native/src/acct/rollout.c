#include "rollout.h"
#include <string.h>
#define TRY(x)                                                                 \
  do {                                                                         \
    Err e_ = (x);                                                              \
    if (e_.code)                                                               \
      return e_;                                                               \
  } while (0)

Str accounting_evidence(Str value) {
  value = token_model_trim(value);
  return value.n ? value : (Str){0};
}
static Err identity(Arena *a, Str s, Str *out) {
  return str_nfc(a, s, "accounting.session_id", out);
}
Err accounting_same_id(Arena *a, Str x, Str y, bool *same) {
  x = accounting_evidence(x);
  y = accounting_evidence(y);
  *same = false;
  if (!x.p || !y.p)
    return ERR_SUCCESS;
  Str nx, ny;
  TRY(identity(a, x, &nx));
  TRY(identity(a, y, &ny));
  *same = str_equal(nx, ny);
  return ERR_SUCCESS;
}
Totals accounting_totals(TokenTotals t) {
  return (Totals){t.input, t.cached, t.output, {t.has_reasoning, t.reasoning}};
}
bool accounting_contains(Totals t) { return t.input || t.cached || t.output; }
Err rollout_ids(Arena *a, Str leaf, const Str *ids, size_t n,
                RolloutShape *out) {
  *out = (RolloutShape){.semantics = COUNTER_INDEPENDENT};
  Str lid, distinct = {0};
  size_t kinds = 0;
  TRY(identity(a, accounting_evidence(leaf), &lid));
  for (size_t i = 0; i < n; i++) {
    Str id = accounting_evidence(ids[i]), normalized;
    TRY(identity(a, id, &normalized));
    if (!str_equal(normalized, lid)) {
      out->semantics = COUNTER_COPIED;
      if (id.p && (!kinds || !str_equal(normalized, distinct))) {
        if (!kinds) {
          distinct = normalized;
          out->inferred_parent = id;
        }
        kinds++;
      }
    }
  }
  if (!lid.n && n > 1)
    out->semantics = COUNTER_COPIED;
  if (kinds != 1)
    out->inferred_parent = (Str){0};
  return ERR_SUCCESS;
}
Err rollout_classify(Arena *a, Str leaf, const TokenObservation *obs, size_t n,
                     bool has_parent, RolloutShape *out) {
  Str *ids = NULL;
  size_t count = 0;
  TRY(arena_alloc(a, n * sizeof *ids, _Alignof(Str), (void **)&ids));
  for (size_t i = 0; i < n; i++)
    if (obs[i].tag == TOKEN_M)
      ids[count++] = obs[i].meta.session_id;
  TRY(rollout_ids(a, leaf, ids, count, out));
  bool propose = out->semantics == COUNTER_INDEPENDENT && has_parent;
  if (out->semantics != COUNTER_COPIED && !propose)
    return ERR_SUCCESS;
  Str lid;
  TRY(identity(a, accounting_evidence(leaf), &lid));
  Totals raw = {0}, pending = {0}, parent = {0};
  bool has_raw = false, has_pending = false, has_parent_boundary = false;
  bool confirmed = false, inspected = false, seen_meta = false,
       seen_context = false, opening = false;
  uint64_t pending_line = 0;
  OwnedSuffix owned = {0};
  for (size_t i = 0; i < n; i++) {
    const TokenObservation *o = &obs[i];
    if (o->tag == TOKEN_M) {
      Str id;
      TRY(identity(a, accounting_evidence(o->meta.session_id), &id));
      bool embedded = seen_meta && (!lid.n || !str_equal(id, lid));
      seen_meta = true;
      if (embedded) {
        owned = (OwnedSuffix){0};
        has_parent_boundary = false;
        confirmed = false;
        inspected = false;
      }
      has_pending = false;
    } else if (o->tag == TOKEN_C || o->tag == TOKEN_XC) {
      bool first = !seen_context;
      seen_context = true;
      has_pending =
          (out->semantics == COUNTER_COPIED || (propose && first)) && has_raw;
      pending_line = o->uidx;
      pending = raw;
      if (opening && first && has_pending) {
        owned = (OwnedSuffix){
            .present = true, .start = pending_line, .baseline = pending};
        inspected = false;
      }
    } else if (o->tag == TOKEN_I) {
      if (!owned.present && o->trigger && has_pending &&
          o->uidx == pending_line + 1 &&
          (out->semantics == COUNTER_COPIED || accounting_contains(pending))) {
        owned = (OwnedSuffix){
            .present = true, .start = pending_line, .baseline = pending};
        parent = pending;
        has_parent_boundary = true;
        confirmed = false;
        inspected = false;
      }
      has_pending = false;
    } else if (o->tag == TOKEN_T) {
      Totals total = accounting_totals(o->total),
             last = accounting_totals(o->last);
      if (!has_raw && propose && !seen_context && o->total.present &&
          o->last.present && accounting_contains(total) &&
          !accounting_contains(last)) {
        opening = true;
        owned =
            (OwnedSuffix){.present = true, .start = o->uidx, .baseline = total};
        parent = total;
        has_parent_boundary = true;
        confirmed = true;
      }
      if (opening && !seen_context && o->total.present && o->last.present &&
          accounting_contains(last) &&
          !totals_equal(&total, has_raw ? &raw : NULL)) {
        opening = false;
        owned = (OwnedSuffix){.present = true,
                              .start = o->uidx,
                              .baseline = has_raw ? raw : total};
        inspected = false;
      }
      if (!inspected && owned.present && o->total.present &&
          !totals_equal(&total, &owned.baseline)) {
        inspected = true;
        if (o->last.present) {
          bool copied = accounting_contains(owned.baseline) &&
                        totals_equal(&total, &last) &&
                        totals_at_least(total, owned.baseline);
          owned.baseline = copied ? total : totals_delta(&last, total);
          owned.first_token = o->uidx;
          owned.has_first_token = true;
          inspected = !copied;
          confirmed = true;
        }
      }
      if (o->total.present) {
        raw = total;
        has_raw = true;
      }
      has_pending = false;
    }
  }
  if (out->semantics == COUNTER_COPIED)
    out->owned = owned;
  else if (owned.present && has_parent_boundary) {
    out->candidate = owned;
    out->parent_boundary = parent;
    out->locally_confirmed = confirmed;
  }
  return ERR_SUCCESS;
}
