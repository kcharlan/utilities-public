#ifndef CP_OPENCODE_COMPOSE_H
#define CP_OPENCODE_COMPOSE_H
#include "db.h"
#include "price/compose.h"
/* All report storage belongs to store->arena; only missing_by_provider owns
 * heap map nodes. Session/message references are borrowed from the store.
 * Integration serializes these typed facts into contextual diagnostics. */
typedef struct {
    const OpencodeSession *session;
    OpencodeTokens tokens;
    bool has_cost;
    double cost;
    MaybeMs date; /* Display convention only: date_basis=session_start. */
} OpencodeUsageDifference;
typedef enum {
    OC_USAGE_ROLLUP_TOKENS, OC_USAGE_ROLLUP_COST,
    OC_USAGE_MESSAGE_TOKEN_SUM, OC_USAGE_MESSAGE_COST_SUM,
    OC_USAGE_RESIDUAL_COST
} OpencodeUsageInvalidContext;
typedef struct {
    const OpencodeSession *session;
    OpencodeUsageInvalidContext context;
} OpencodeUsageInvalid;
struct OpencodeUsageReport {
    uint64_t requests, missing_usage, inherited, cost_only;
    Omap missing_by_provider; /* uint64_t*, store-arena owned values */
    OpencodeUsageDifference *residuals, *shortfalls;
    size_t residual_count, residual_capacity, shortfall_count, shortfall_capacity;
    OpencodeUsageInvalid *invalid;
    size_t invalid_count, invalid_capacity;
};
/* Call once after corpus projection and Codex/Claude composition, then refresh
 * costs after all providers have authored units. Accepted sessions only. */
Err opencode_compose(OpencodeStore *store, Corpus *corpus);
void opencode_usage_destroy(OpencodeStore *store);
#endif
