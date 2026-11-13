#ifndef CP_PRICE_RULES_H
#define CP_PRICE_RULES_H
#include "util/json_read.h"
/* Both documents and their string slices remain owned until destruction. */
typedef struct { yyjson_doc *defaults,*user; bool user_invalid; } PricingRules;
Err pricing_rules_load(const char *path,PricingRules *out);
void pricing_rules_destroy(PricingRules *rules);
Str rules_alias(const PricingRules *rules,const char *scope,Str name);
double rules_codex_fast(const PricingRules *rules,Str name);
bool rules_codex_cutoff(const PricingRules *rules,Str name,int64_t *ms);
int64_t rules_codex_cap(const PricingRules *rules);
bool rules_codex_uncapped(const PricingRules *rules,Str name);
const char *rules_claude_provider(const PricingRules *rules,Str lower);
Str rules_claude_catalog_alias(const PricingRules *rules,Str name);
yyjson_val *rules_section(const PricingRules *rules,const char *section,bool user);
#endif
