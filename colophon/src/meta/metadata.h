#ifndef CP_METADATA_H
#define CP_METADATA_H
#include "util/omap.h"
#include <stdint.h>

typedef enum {
  META_ID,
  META_NAME,
  META_TITLE,
  META_CWD,
  META_GIT_BRANCH,
  META_GIT_ORIGIN_URL,
  META_GIT_SHA,
  META_SOURCE,
  META_ORIGINATOR,
  META_ARCHIVED,
  META_FIRST_USER_MESSAGE,
  META_AGENT_NICKNAME,
  META_AGENT_ROLE,
  META_AGENT_PATH,
  META_ROLLOUT_PATH,
  META_COLUMNS
} MetadataColumn;
extern const char *const metadata_columns[META_COLUMNS];
/* META_NULL is an explicit direct-input null; the real SQL loader omits NULL.
 */
typedef enum {
  META_ABSENT,
  META_TEXT,
  META_INTEGER,
  META_REAL,
  META_BLOB,
  META_NULL
} MetadataKind;
typedef struct {
  MetadataKind kind;
  /* TEXT bytes are strict UTF-8; BLOB is an arbitrary byte slice (including
   * empty/NUL/invalid UTF-8), and must never enter Unicode operations. */
  union {
    Str bytes;
    int64_t integer;
    double real;
  } value;
} MetadataValue;
typedef struct {
  MetadataValue values[META_COLUMNS];
  /* Direct typed inputs preserve first-key insertion order. The real SQL
   * loader leaves this empty and uses canonical selected-column order. */
  MetadataColumn order[META_COLUMNS];
  size_t order_count;
} MetadataThread;
MetadataColumn metadata_thread_column(const MetadataThread *row,
                                      size_t position);
typedef struct MetadataError {
  Str text;
  struct MetadataError *next;
} MetadataError;
typedef struct {
  Arena arena, database_arena;
  /* Values: MetadataThread* for threads; Str* for every other map.
   * All keys/maps and referenced values remain valid until destroy. */
  Omap threads, index_titles, desktop_titles, spawn_parents, rollout_paths;
  MetadataError *errors, *last_error;
} CodexMetadata;

bool metadata_text(Str value);
/* Readonly absolute percent-encoded URI; caller frees *uri on success. */
Err metadata_database_uri(const char *path, char **uri);
/* Zero-initialize output, destroy even on failure. Optional source failures
 * become ordered errors; allocation failure is returned to the run owner. */
Err metadata_load(const char *codex_home, CodexMetadata *out);
void metadata_destroy(CodexMetadata *metadata);
#endif
