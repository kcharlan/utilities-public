#ifndef CP_PRICING_H
#define CP_PRICING_H
#include "compose.h"
#include "ledger.h"
typedef struct {
    const HistoryEntry *history;
    PriceEntry rates;
    PricePriority priority;
    bool claude;
    double fast_multiplier;
} PricingPeriod;
typedef struct {Str key;PricingPeriod **items;size_t count,capacity;} PricingPeriods;
typedef struct {
    Arena arena;
    Omap periods,unpriced,history_begins,priority_without_multiplier,unrecorded,untimed;
    Omap claude_resolutions;
    yyjson_doc *claude_seed;
} PricingReport;
/* Report period metadata borrows the independent PriceHistory owner until
 * rendering. Transient rates/policy and all keys/counts are report-owned.
 * Units keep original borrowed record/priority strings and acquire report keys. */
Err pricing_report_init(const PriceHistory *history,PricingReport *out);
Err price_usage_units(UsageUnit *units,size_t count,const PriceHistory *history,
                      ModelsDevIndex *index,bool costs_available,PricingReport *report);
Err price_units(Corpus *corpus,const PriceHistory *history,ModelsDevIndex *index,
                bool costs_available,PricingReport *report);
Err pricing_claude_period(PricingReport *report,Str key,const PriceEntry *rates,
                         double fast_multiplier,PricePeriod *out);
Err pricing_note_unpriced(PricingReport *report,Str key,__int128 tokens);
void pricing_report_note_sums(const PricingReport *report);
void pricing_report_json(JsonWriter *writer,const PricingReport *report);
void pricing_models_json(JsonWriter *writer,const PricingReport *report);
void pricing_diagnostic_json(JsonWriter *writer,const Omap *map,const char *field,bool clock,bool keys_only);
void pricing_report_destroy(PricingReport *report);
Err pricing_recording_models(const Corpus *corpus,const PriorityTurns *priority,
                             ModelsDevIndex *index,yyjson_doc **out);
#endif
