#ifndef CP_PRICE_MODEL_H
#define CP_PRICE_MODEL_H
#include "util/str.h"
#include "util/omap.h"
/* Borrows a slice of raw or returns a static alias. Raw owner must outlive it.
 */
Str normalize_codex_model(Str raw);
/* Raw-key identity is exact; values own a durable copy in arena. Caller owns
 * and destroys both map and arena; map destruction does not invalidate values. */
Err normalize_codex_model_memo(Arena *arena,Omap *memo,Str raw,Str *out);
bool price_character_extend(uint32_t codepoint);
bool price_character_prepend(uint32_t codepoint);
size_t price_literal_parts(Str haystack, Str needle, Str suffix, bool last);
typedef struct { Str *items; size_t count; } ModelCandidates;
Err models_dev_candidates(Arena *arena, Str raw, ModelCandidates *out);
double codex_api_fast_multiplier(Str model);
#endif
