#ifndef CP_RECORD_H
#define CP_RECORD_H
#include "model/logrecord.h"
typedef struct {
    Str role, kind, text, family;
    uint64_t images;
} MessageCandidate;
typedef struct {
    Str role, text;
} VoiceSegment;
typedef struct {
    bool present, structured;
    ToolCounts counts;
} ToolCandidate;
typedef enum {
    LINK_NONE,
    LINK_ACTIVITY,
    LINK_RECEIVERS,
    LINK_SPAWN,
    LINK_TARGET,
    LINK_OUTPUT
} LinkKind;
typedef struct {
    LinkKind kind;
    Str first, second, third;
    Str *receivers;
    size_t count;
} LinkCandidate;
typedef struct {
    uint64_t rec, line;
    Str kind, ts_src, turn_id, thread_id, meta_id, turn_key;
    MaybeMs at_ms, wrapper_ms;
    MaybeNum started_at, reported_ms, ttft_ms;
    bool item_message, has_message, has_voice, inherited;
    MessageCandidate message;
    VoiceSegment voice;
    ToolCandidate tool;
    LinkCandidate link;
} RecordFact;
/* Initialize output to zero and always destroy, even after errors. Intern owner
 * is borrowed; optional observer receives raw/original-decode/record callbacks.
 * The record owns its token stream; an ERR_INVALID token metadata failure is
 * fatal (source ValueError), not an unreadable-file result or a cacheable miss.
 * No source JSON pointer survives the decoded callback. */
Err record_parse(const DiscoveredLog *snapshot, Intern *identifiers,
                 const ReaderCallbacks *raw_owner, LogRecord *out);
void record_destroy(LogRecord *record);
yyjson_val *record_get(yyjson_val *obj, const char *key);
Str record_string(yyjson_val *value);
Str record_trim(Str value, bool right);
bool record_prefix(Str value, const char *prefix);
bool record_identifier(Str value, bool history);
Err record_intern(LogRecord *record, Str value, Str *out);
Err record_scalar(LogRecord *record, yyjson_val *value, const char *site, JScalar *out);
bool record_scalar_truthy(JScalar value);
MaybeNum record_number(yyjson_val *value, bool nonnegative, const char *site);
MaybeMs record_event_time(yyjson_val *root, yyjson_val *payload, Str *source);
/* Arena vector append; old storage remains owned by arena until destroy. */
Err record_append(Arena *arena, void **data, size_t *count, size_t *capacity, size_t element_size,
                  const void *value);
#endif
