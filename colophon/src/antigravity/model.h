#ifndef CP_ANTIGRAVITY_MODEL_H
#define CP_ANTIGRAVITY_MODEL_H
#include "corpus.h"
/* Generic/unknown enum labels return empty, allowing meaningful fallback. */
Str antigravity_model_enum(int64_t model);
Err antigravity_model(Arena *arena,Str response,Str usage,Str step_metadata,Str previous,Str *raw,Str *normalized);
Err antigravity_normalize_model(Arena *arena,Str raw,Str *out);
#endif
