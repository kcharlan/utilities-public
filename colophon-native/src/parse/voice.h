#ifndef CP_VOICE_H
#define CP_VOICE_H
#include "turns.h"
Err voice_segment(LogRecord *record, yyjson_val *payload, Str kind, VoiceSegment *out,
                  bool *present);
Err voice_build(LogRecord *record, RecordFact *facts, size_t count, const TurnBuilder *builder);
#endif
