#ifndef CP_ANTIGRAVITY_MODEL_H
#define CP_ANTIGRAVITY_MODEL_H
#include "corpus.h"
Err antigravity_model(Arena *arena,Str response,Str usage,Str step_metadata,Str previous,const Omap *numbers,Str *raw,Str *normalized);
Err antigravity_model_typed(AgMismatches *m,Arena *arena,Str response,Str usage,Str step_metadata,Str previous,const Omap *numbers,Str *raw,Str *normalized);
Err antigravity_normalize_model(Arena *arena,Str raw,Str *out);
#endif
