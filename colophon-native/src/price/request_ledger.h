#ifndef CP_REQUEST_LEDGER_H
#define CP_REQUEST_LEDGER_H
#include "model/logrecord.h"
typedef struct { int64_t input, cached, output, reasoning; } RequestTotals;
typedef enum { LEDGER_ACCEPTED, LEDGER_FOREIGN, LEDGER_INVALID } LedgerVerdict;
typedef struct {
  Str response_id, turn_id, timestamp; /* response trimmed; turn as written (nonempty) or empty */
  MaybeMs timestamp_ms;
  RequestTotals usage, thread_total, turn_total;
  bool has_turn_total, has_reasoning;
} LedgerRecord;
bool request_totals_decode(const UsageScalars *scalars, RequestTotals *out);
bool request_totals_at_least(RequestTotals total, RequestTotals usage);
/* session and request_session are canonical (NFC) identities. */
Err ledger_record_accept(Arena *scratch, const UsageRecord *record, Str session,
                         Str request_session, LedgerRecord *out, LedgerVerdict *verdict);
#endif
