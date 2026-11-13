#ifndef CP_ANTIGRAVITY_MODEL_H
#define CP_ANTIGRAVITY_MODEL_H
#include "corpus.h"
#include "price/rules.h"
Err antigravity_model(const PricingRules *rules,Arena *arena,Str response,Str usage,Str step_metadata,Str previous,const Omap *numbers,Str *raw,Str *normalized);
Err antigravity_model_typed(const PricingRules *rules,AgMismatches *m,Arena *arena,Str response,Str usage,Str step_metadata,Str previous,const Omap *numbers,Str *raw,Str *normalized);
Err antigravity_normalize_model(const PricingRules *rules,Arena *arena,Str raw,Str *out);
Err antigravity_strip_routing(const PricingRules *rules,Arena *arena,Str raw,Str *out);
#endif
