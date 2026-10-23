#ifndef CP_ANTIGRAVITY_WIRE_H
#define CP_ANTIGRAVITY_WIRE_H
#include "util/str.h"
/* Zero-copy, allocation-free wire views. Owners must outlive these slices.
 * Limits apply per blob, never to the enclosing SQLite database. */
#define AG_WIRE_MAX_BYTES (64u*1024u*1024u)
#define AG_WIRE_MAX_FIELDS 100000u
#define AG_WIRE_MAX_DEPTH 32u
typedef enum { AG_ABSENT, AG_FOUND, AG_MALFORMED } AgResult;
typedef struct { uint32_t number; unsigned wire; uint64_t integer; Str bytes; } AgField;
typedef struct { Str input, packed; size_t offset, packed_offset, fields; } AgCursor;
typedef enum {
    AG_OPAQUE, AG_TRAJECTORY, AG_WORKSPACE, AG_STEP_METADATA, AG_STEP,
    AG_GENERATOR, AG_CHAT_MODEL, AG_RETRY, AG_USAGE, AG_MODEL_INFO,
    AG_TOOL_CALL, AG_USER_INPUT, AG_PLANNER, AG_TEXT_ITEM, AG_MEDIA,
    AG_TIMESTAMP, AG_DURATION, AG_ANNOTATIONS, AG_SUMMARY
} AgMessageType;
AgResult ag_wire_next(AgCursor *cursor, AgField *field);
/* Last raw occurrence; scans the complete message so malformed tails cannot
 * masquerade as found. Singular message fields require merging occurrences,
 * rather than treating the last occurrence as a complete message replacement. */
AgResult ag_wire_last(Str input, uint32_t number, AgField *field);
AgResult ag_wire_integer_next(AgCursor *cursor, uint32_t number, uint64_t *value);
AgResult ag_wire_validate(Str input, AgMessageType type);
const char *ag_wire_type_name(AgMessageType type);
#endif
