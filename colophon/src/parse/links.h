#ifndef CP_LINKS_H
#define CP_LINKS_H
#include "record.h"
Err link_candidate(LogRecord *record, yyjson_val *payload, Str kind, LinkCandidate *out);
Err links_build(LogRecord *record, RecordFact *facts, size_t count);
#endif
