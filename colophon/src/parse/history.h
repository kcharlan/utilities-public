#ifndef CP_HISTORY_H
#define CP_HISTORY_H
#include "record.h"
Err history_build(LogRecord *record, RecordFact *facts, size_t count);
bool is_inherited(const LogRecord *record, uint64_t rec);
#endif
