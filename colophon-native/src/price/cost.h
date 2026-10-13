#ifndef CP_PRICE_COST_H
#define CP_PRICE_COST_H
#include "util/pynum.h"
#include "yyjson.h"
typedef struct { PyNum input, cached_input, cache_write, output; } PriceRates;
typedef struct {
    PriceRates standard, extended;
    bool has_extended;
    int64_t threshold;
} PriceEntry;
typedef struct { bool present, capped; int64_t cap; PyNum multiplier; } PricePriority;
bool price_entry_decode(yyjson_val *value, PriceEntry *out);
bool price_priority_decode(yyjson_val *value, PricePriority *out);
bool price_entry_equal(const PriceEntry *left,const PriceEntry *right);
double cost_usd(const PriceEntry *entry, __int128 input, __int128 cached, __int128 output);
bool priority_cost_usd(const PriceEntry *entry, const PricePriority *priority,
                       __int128 input, __int128 cached, __int128 output, double *out);
#endif
