#ifndef CP_MESSAGES_H
#define CP_MESSAGES_H
#include "record.h"
Err classify_user_part(Arena *arena, Str text, Str *kind, Str *accepted, bool *present);
Err message_candidate(LogRecord *record, yyjson_val *payload, Str kind, MessageCandidate *out,
                      bool *present);
Err messages_build(LogRecord *record, RecordFact *facts, size_t count);
/* Result is borrowed from this record. A false result leaves outputs unset. */
bool select_final_answer(const LogRecord *record, Str turn_key, Str *text, bool *voice);
#endif
