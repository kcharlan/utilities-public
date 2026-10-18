#ifndef CP_OPENCODE_DB_H
#define CP_OPENCODE_DB_H
#include "model/logrecord.h"
#include "util/omap.h"
#include <signal.h>
#include <sqlite3.h>

typedef enum { OC_DB_OK, OC_DB_ABSENT, OC_DB_UNREADABLE, OC_DB_UNSUPPORTED, OC_DB_SKIPPED } OpencodeDatabaseStatus;
typedef struct {
    Str path, reason, latest_migration;
    bool primary, untested;
    OpencodeDatabaseStatus status;
    size_t accepted_sessions, accepted_messages;
    Arena arena; /* Successful database facts; private staging until COMMIT. */
} OpencodeDatabase;
typedef struct { __int128 input, output, reasoning, cache_read, cache_write; } OpencodeTokens;
typedef struct {
    Str id, name, child_session_id;
    bool failed;
    MaybeMs created_ms, ran_ms, completed_ms;
} OpencodeTool;
typedef enum {
    OC_MSG_AGENT, OC_MSG_MODEL, OC_MSG_LOCATION, OC_MSG_USER, OC_MSG_SYNTHETIC,
    OC_MSG_SYSTEM, OC_MSG_SKILL, OC_MSG_SHELL, OC_MSG_ASSISTANT, OC_MSG_COMPACTION, OC_MSG_IDLE
} OpencodeMessageKind;
typedef struct {
    OpencodeMessageKind kind;
    Str id, type, text, model_id, provider_id, agent, finish, error, outcome, status;
    int64_t seq;
    MaybeMs row_created_ms, created_ms, streamed_ms, completed_ms;
    size_t images;
    bool tokens_present, tokens_valid, cost_present, cost_valid;
    OpencodeTokens tokens;
    double cost;
    OpencodeTool *tools;
    size_t tool_count, tool_capacity;
    Str turn; /* Corpus-populated, never the copied payload id. */
    bool inherited;
} OpencodeMessage;
typedef struct {
    Str id, database, parent_id, fork_session_id, project_id, directory, title;
    Str agent, model_id, provider_id, version, idle_outcome;
    size_t database_index;
    bool primary, archived, project_archived, provenance_complete;
    MaybeMs created_ms, updated_ms, idle_ms;
    bool tokens_present, tokens_valid, cost_present, cost_valid;
    OpencodeTokens tokens;
    double cost;
    OpencodeMessage *messages;
    size_t message_count, message_capacity;
    uint64_t malformed_messages, invalid_numbers;
    Omap unknown_message_types, unknown_content_types; /* arena uint64_t values */
} OpencodeSession;
typedef struct OpencodeUsageReport OpencodeUsageReport;
typedef struct {
    Arena arena;
    bool discovered, discovery_complete;
    OpencodeDatabase *databases;
    size_t database_count, database_capacity;
    OpencodeSession **sessions;
    size_t session_count, session_capacity;
    Omap session_ids; /* Borrowed session pointers; owns its map nodes. */
    Omap unknown_message_types, unknown_content_types; /* arena uint64_t values */
    uint64_t malformed_messages, invalid_numbers, duplicate_sessions;
    OpencodeUsageReport *usage; /* Usage module owns nested report resources. */
} OpencodeStore;
/* Zero-initialize store; call read once; destroy on every result. Database paths
 * are owned absolute lexical paths. Precedence is add order, after successful
 * snapshot commit. No credential table or arbitrary kv values are read. */
Err opencode_store_add_database(OpencodeStore *store, Str path, bool primary);
Err opencode_db_open(const char *path, sqlite3 **out);
Err opencode_store_read(OpencodeStore *store, volatile sig_atomic_t *interrupted);
void opencode_store_destroy(OpencodeStore *store);
#endif
