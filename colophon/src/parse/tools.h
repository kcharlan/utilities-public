#ifndef CP_TOOLS_H
#define CP_TOOLS_H
#include "record.h"
void tool_counts_destroy(ToolCounts *counts);
Err tool_candidate(LogRecord *record, yyjson_val *root, yyjson_val *payload, Str kind,
                   ToolCandidate *out);
Err tools_build(LogRecord *record, RecordFact *facts, size_t count);
#endif
