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
typedef enum { PAIR_BOUNDARY, PAIR_RESTART, PAIR_SNAPSHOT, PAIR_LEDGER } PairKind;
typedef struct { PairKind kind; uint64_t line; size_t index; } PairEvent;
typedef struct {
  Str turn; /* canonical mirror turn; empty when unknown */
  RequestTotals usage; /* absent reasoning represented by zero */
  bool has_total; /* ledger always has its thread total */
  RequestTotals total;
  bool has_turn_total; /* ledger only */
  RequestTotals turn_total;
  Str timestamp; /* original text */
  MaybeMs ms;
  bool replay; /* response appeared earlier in this file */
  Str response_id; /* ledger-only canonical identity; empty means distinct side */
  bool observation_key; /* snapshot without raw last usage also aliases empty usage */
} PairSide;
Err request_mirror_key(Arena *arena, Str session, const PairSide *side, bool with_usage, Str *out);
Err request_record_mirror_keys(Arena *arena, Str session, const PairSide *side, Str keys[3], size_t *count);
/* Sorted chronological events with valid indexes, one event per side. Each ledger
 * claims at most one snapshot. Already-owned duplicate aliases stay unmatched. */
Err request_pair_file(const PairSide *snapshots, size_t snapshot_count, const PairSide *ledgers,
                      size_t ledger_count, const PairEvent *events, size_t event_count, bool *matched);
#endif
