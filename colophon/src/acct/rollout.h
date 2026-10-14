#ifndef CP_ROLLOUT_H
#define CP_ROLLOUT_H
#include "parse/tokenstream.h"
#include "totals.h"
typedef enum {
  COUNTER_UNKNOWN,
  COUNTER_INDEPENDENT,
  COUNTER_COPIED
} CounterSemantics;
typedef struct {
  bool present, has_first_token;
  uint64_t start, first_token;
  Totals baseline;
} OwnedSuffix;
typedef struct {
  CounterSemantics semantics;
  OwnedSuffix owned, candidate;
  Totals parent_boundary;
  bool locally_confirmed;
  Str inferred_parent;
} RolloutShape;
/* Returned strings are borrowed slices; canonical comparison uses scratch. */
Str accounting_evidence(Str value);
Err accounting_same_id(Arena *scratch, Str a, Str b, bool *same);
Totals accounting_totals(TokenTotals value);
bool accounting_contains(Totals value);
Err rollout_ids(Arena *scratch, Str leaf, const Str *ids, size_t count,
                RolloutShape *out);
Err rollout_classify(Arena *scratch, Str leaf, const TokenObservation *obs,
                     size_t count, bool has_parent, RolloutShape *out);
#endif
