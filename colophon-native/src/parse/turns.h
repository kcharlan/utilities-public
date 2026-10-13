#ifndef CP_TURNS_H
#define CP_TURNS_H
#include "record.h"
typedef struct {
    MaybeNum start_ms, duration_ms;
    Str flags[2];
    size_t flag_count;
} TurnTiming;
/* Source bookkeeping is shared by key, even when distinct turns collide. */
typedef struct {
    Str key, last_src;
    bool has_span, has_span_end, has_completion;
    uint64_t span_start, span_end, completion_rec;
} TurnKeyState;
typedef struct {
    /* Zero-initialize; caller destroys map entries after voice_build.
     * Values live in the record arena, never in cached TurnFact objects. */
    Omap keyed;
} TurnBuilder;
Err turns_build(LogRecord *record, RecordFact *facts, size_t count, TurnBuilder *builder);
TurnTiming turn_timing(const TurnFact *turn, bool collapsed);
#endif
