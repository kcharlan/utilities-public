#ifndef CP_TURNSTATUS_H
#define CP_TURNSTATUS_H
#include "assemble.h"
Err turn_models(Arena *arena, TurnFact *const *facts, size_t count,
                bool collapsed, int64_t mtime_ms, int64_t snapshot_ms,
                TurnModel **out);
Err active_interval_union(Arena *arena, const TurnModel *turns, size_t count,
                          MaybeNum *out);
int corpus_number_compare(PyNum left, PyNum right);
#endif
