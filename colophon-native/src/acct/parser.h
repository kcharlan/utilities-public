#ifndef CP_ACCOUNTING_PARSER_H
#define CP_ACCOUNTING_PARSER_H
#include "model/logrecord.h"
#include "rollout.h"
typedef struct InheritedResolver InheritedResolver;
typedef struct {
  int64_t file;
  uint64_t line, event_index;
  bool event_index_absent;
  Str turn_id, timestamp, model_raw, model;
  int64_t at_ms;
  MaybeMs timestamp_ms;
  char day[11];
  TokenTotals tokens;
  TokenTotals raw_last, raw_total;
  bool bare;
} AccountingRow;
typedef struct {
  Str timestamp;
  TokenTotals last, total;
} TokenSnapshot;
typedef struct {
  double position;
  Str model;
} ModelTimeline;
typedef struct {
  Arena arena; /* Owns result arrays and generated strings; stream remains
                  borrowed. */
  AccountingRow *rows;
  size_t row_count;
  TokenSnapshot *snapshots;
  size_t snapshot_count;
  ModelTimeline *timeline;
  size_t timeline_count;
  TokenObservation *buffered;
  size_t buffered_count;
  const TokenObservation *
      *buffered_sources; /* Borrowed immutable occurrence provenance. */
  Str session_id, forked_from_id;
  bool unresolved, buffered_retained, depends_on_parent, has_fork_state;
  TokenMeta fork_metadata;
  bool has_inherited, has_remaining;
  Totals inherited, remaining;
} AccountingResult;
/* Pass a zero-initialized result; destroy it even after an error. Strings and
 * buffered_sources borrow the stream/record/intern owners until result teardown. */
Err accounting_parse(const TokenStream *stream, InheritedResolver *resolver,
                     AccountingResult *out);
void accounting_result_destroy(AccountingResult *result);
#endif
