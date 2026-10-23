#ifndef CP_ANTIGRAVITY_DB_H
#define CP_ANTIGRAVITY_DB_H
#include "wire.h"
#include "util/omap.h"
#include <signal.h>
typedef enum { AG_DB_OK,AG_DB_ABSENT,AG_DB_UNREADABLE,AG_DB_UNSUPPORTED } AntigravityDatabaseStatus;
/* Value is meaningful only for INTEGER. Invalid optional enums retain their
 * independent record facts, and must never masquerade as absent/default. */
typedef enum { AG_SQL_ABSENT,AG_SQL_INTEGER,AG_SQL_INVALID } AntigravityIntegerState;
typedef struct { int64_t idx,step_type,status,step_format;AntigravityIntegerState step_type_state,status_state,step_format_state;Str metadata,payload; } AntigravityStep;
typedef struct { int64_t idx;bool has_idx;Str data; } AntigravityBlob;
typedef struct { Str trajectory_id,cascade_id;int64_t trajectory_type,source;AntigravityIntegerState trajectory_type_state,source_state; } AntigravityMeta;
typedef struct {
    Str id,database,surface,title,archive_reason;
    bool archived,annotation_valid,summary_valid,annotation_archived,summary_archived;
    Str annotation_title,summary_title,summary_blob;
    AntigravityMeta *meta;size_t meta_count,meta_capacity;
    AntigravityBlob *metadata;size_t metadata_count,metadata_capacity;
    AntigravityStep *steps;size_t step_count,step_capacity;
    AntigravityBlob *generators;size_t generator_count,generator_capacity;
} AntigravitySession;
typedef struct {
    Str path,id,surface,reason;
    AntigravityDatabaseStatus status;
    size_t accepted_sessions,accepted_steps;
    Arena arena; /* Snapshot staging; retained only after successful COMMIT. */
} AntigravityDatabase;
typedef struct { Str database,session,surface,context,reason;int64_t idx; } AntigravityDiagnostic;
typedef struct {
    Arena arena;
    bool discovered,disabled,present,discovery_complete;
    Str home;
    AntigravityDatabase *databases;size_t database_count,database_capacity;
    AntigravitySession **sessions;size_t session_count,session_capacity;
    Omap session_ids;
    AntigravityDiagnostic *diagnostics;size_t diagnostic_count,diagnostic_capacity;
    Str *ignored_environment;size_t ignored_environment_count,ignored_environment_capacity;
    uint64_t legacy_encrypted,duplicate_sessions,archive_disagreements,malformed_blobs,malformed_rows,annotation_errors;
} AntigravityStore;
Err antigravity_store_read(AntigravityStore *store,volatile sig_atomic_t *interrupted);
void antigravity_store_destroy(AntigravityStore *store);
Err antigravity_diagnostic(AntigravityStore *store,const AntigravityDatabase *db,const char *context,int64_t idx,const char *reason);
/* Root and descendants must be actual files/directories, never symlinks.
 * SQLite may coordinate only through ordinary admitted sidecars. */
bool antigravity_safe_path(Str root,const char *path);
const char *antigravity_database_status(AntigravityDatabaseStatus status);
#endif
