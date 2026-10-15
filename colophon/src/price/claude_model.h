#ifndef CP_CLAUDE_MODEL_H
#define CP_CLAUDE_MODEL_H
#include "catalog.h"
Err normalize_claude_model(Arena *arena, Str raw, Str *out);
typedef struct { CatalogLookup catalog; Str provider; } ClaudeLookup;
Err claude_models_dev_lookup(Arena *arena, ModelsDevIndex *index, Str raw, ClaudeLookup *out);
Err claude_fast_multiplier(Str model, double *out);
#endif
