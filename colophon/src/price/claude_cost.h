#ifndef CP_CLAUDE_COST_H
#define CP_CLAUDE_COST_H
#include "pricing.h"
#include "claude/scan.h"
double claude_cost_usd(const PriceEntry *rates,const UsageUnit *unit);
Err claude_price_usage_units(UsageUnit *units,size_t count,ModelsDevIndex *index,PricingReport *report);
Err catalog_price_usage_units(UsageUnit *units,size_t count,ModelsDevIndex *index,PricingReport *report,Str identity_prefix,bool key_by_model);
Err claude_price_units(Corpus *corpus,ModelsDevIndex *index,PricingReport *report);
Err claude_capture_prices(ClaudeScan *scan,ModelsDevIndex *index);
#endif
