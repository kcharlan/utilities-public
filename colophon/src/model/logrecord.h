#ifndef CP_LOGRECORD_H
#define CP_LOGRECORD_H
#include "parse/reader.h"
#include "parse/tokenstream.h"
#include "util/pynum.h"

typedef enum {
    JS_ABSENT,
    JS_NULL,
    JS_BOOL,
    JS_INT,
    JS_FLOAT,
    JS_STRING,
    JS_ARRAY,
    JS_OBJECT
} JKind;
typedef struct {
    JKind kind;
    bool empty;
    union {
        bool b;
        int64_t i;
        double f;
        Str s;
    } value;
} JScalar;
typedef struct {
    bool present;
    int64_t value;
} MaybeMs;
typedef struct {
    bool present;
    PyNum value;
} MaybeNum;
typedef struct {
    Str id, request_session_id, forked_from_id;
    MaybeMs created_at_ms;
    bool is_subagent;
    JScalar timestamp_raw, cwd, originator, cli_version, parent_thread_id, depth;
    JScalar agent_path, agent_nickname, agent_role, branch, origin_url, sha, rollout_title;
} SessionMeta;
typedef struct {
    uint64_t start, end;
} RecordRange;
typedef struct {
    Str path, method;
    bool has_boundary;
    uint64_t boundary_rec;
    RecordRange *inherited_recs, *inherited_lines;
    size_t rec_count, line_count;
} History;
typedef struct {
    Str key, turn_id, start_src, end_src, end_kind;
    MaybeMs start_ms, end_ms, last_ms;
    MaybeNum reported_ms, ttft_ms;
    bool has_start_rec;
    uint64_t start_rec;
} TurnFact;
typedef struct {
    Str role, kind, text, ts_src, turn_key;
    uint64_t images, rec;
    MaybeMs at_ms;
} MessageFact;
typedef struct {
    Str text, turn_key, reply;
    MaybeMs at_ms;
    bool before_turn, follow_up;
} VoiceRequest;
typedef struct {
    Str text, turn_key;
    MaybeMs at_ms;
} VoiceReply;
typedef struct {
    uint64_t shell, shell_failed, file_edits, web, image;
    Omap mcp, other;
} ToolCounts;
typedef struct {
    ToolCounts structured, raw;
    bool has_structured;
} ToolTally;
typedef struct {
    Str kind, child_id, agent_path, turn_key;
} ActivityLink;
typedef struct {
    Str task_name, turn_key;
    MaybeMs at_ms;
} SpawnLink;
typedef struct {
    Str target, turn_key;
} TargetLink;
typedef struct {
    Str child_id, turn_key;
} ReceiverLink;
typedef struct {
    JScalar input, cached_input, output, reasoning;
} UsageScalars;
typedef struct {
    uint64_t line, rec;
    JScalar response_id, thread_id, turn_id, root_turn_id, ts;
    MaybeMs at_ms, timestamp_unix_ms;
    JScalar input, cached_input, cache_read_input, cache_write, output, reasoning;
    JScalar session_id;
    UsageScalars thread_usage, turn_usage;
} UsageRecord;
typedef struct {
    Arena arena;         /* Owns every retained scalar/text/array except run intern IDs. */
    Intern *identifiers; /* Borrowed run owner, must outlive this record. */
    DiscoveredLog key;   /* path interned into identifiers; frozen size/mtime. */
    ReaderResult reader;
    TokenStream token_stream;
    Str status;
    bool has_meta;
    SessionMeta meta;
    uint64_t extra_meta_count, wrapper_count;
    size_t wrapper_distinct;
    History history;
    MaybeMs first_ms, last_ms;
    TurnFact **turns;
    size_t turn_count;
    MessageFact *messages;
    size_t message_count;
    VoiceRequest *requests;
    size_t request_count;
    VoiceReply *replies;
    size_t reply_count;
    Omap tools; /* key -> arena-owned ToolTally; owns map nodes/keys only */
    ActivityLink *activities;
    size_t activity_count;
    SpawnLink *spawns;
    size_t spawn_count;
    TargetLink *targets;
    size_t target_count;
    ReceiverLink *receivers;
    size_t receiver_count;
    UsageRecord *usage_records;
    size_t usage_count;
} LogRecord;
#endif
