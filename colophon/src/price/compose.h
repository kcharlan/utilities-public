#ifndef CP_COMPOSE_H
#define CP_COMPOSE_H
#include "acct/resolver.h"
#include "corpus/assemble.h"
#include "priority.h"
enum { PRIORITY_THREAD=1, PRIORITY_MODEL=2, PRIORITY_TIMESTAMP=4,
       PRIORITY_FIRST_SEEN=8, PRIORITY_FULL=15 };
typedef struct { bool present; Str model; size_t index; } PricePeriod;
typedef struct UsageUnit {
  Str session_id, turn_id, display_turn, model_raw, model, source;
  size_t file;
  uint64_t line;
  MaybeMs at_ms, timestamp_ms;
  const PriorityEntry *priority;
  uint8_t priority_fields;
  bool priority_tier, priority_first_seen_null;
  bool has_cost;
  double cost_usd;
  PricePeriod period, priority_period;
  PricePeriod fast_period;
  __int128 input, cached, cache_write, output;
  __int128 cache_write_1h;
  bool fast;
  /* Claude extraction-time estimate. Persist with raw Claude rows so a later
   * unknown catalog can use the recorded nanocost, including an exact zero. */
  bool claude_price_snapshot, claude_cost_priced;
  int64_t claude_cost_nanos;
  OptionalTokens reasoning;
} UsageUnit;
typedef struct UsageSummary {
  __int128 input, cached, cache_write, output, reasoning;
  size_t count;
  bool has_cost;
  double cost_usd;
  __int128 unpriced_tokens;
  struct PricedBy *priced_by;
  size_t priced_count, priced_capacity;
} UsageSummary;
typedef struct PricedBy { PricePeriod period; bool priority, fast; } PricedBy;
typedef struct UsageBucket {
  MaybeMs bucket;
  Str model;
  bool priority;
  UsageSummary usage;
} UsageBucket;
/* Compose retains raw record/Intern and PriorityTurns strings. Its arena and
 * diagnostics are owned separately, and reset on every recomposition. */
Err compose_usage(Corpus *corpus, const PriorityTurns *priority);
Err compose_refresh_costs(Corpus *corpus, bool costs_available);
/* Aggregate an authored or freshly composed unit sequence into the same
 * owned session/turn/bucket summaries. Called once before cost refresh. */
Err compose_aggregate_session(Corpus *corpus, SessionModel *session);
void compose_destroy(Corpus *corpus);
Err compose_row_key(Arena *arena, Str session_id, Str file,
                    const AccountingRow *row, Str *out);
void compose_duplicate_ids_json(JsonWriter *writer, const Corpus *corpus);
void compose_summary_json(JsonWriter *writer, const UsageSummary *usage);
void compose_buckets_json(JsonWriter *writer, const SessionModel *session);
#endif
