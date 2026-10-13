#include "request_ledger.h"
#include "parse/tokenstream.h"
#include "util/time.h"
#include <math.h>
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
