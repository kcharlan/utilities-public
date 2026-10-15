#ifndef CP_DISCOVER_H
#define CP_DISCOVER_H
#include <stdbool.h>
/* Shared native hidden/package filtering; traversal must still use lstat. */
bool discovery_hidden(const char *path);
bool discovery_package(const char *path);
#include "util/intern.h"
#include <sys/types.h>
typedef struct {
    Str path;
    bool archived;
    int64_t size, mtime_ns;
    bool stat_ok;
    dev_t device;
    ino_t inode;
} DiscoveredLog;
typedef struct {
    const DiscoveredLog *logs;
    size_t count;
    Intern paths;
    bool paths_initialized;
} Discovery;
/* Zero-initialize output. Owns the array and interned paths until destroy.
 * Consumers treat logs as immutable: neither stat nor reads refresh this data. */
Err discover_logs(const char *codex_home, Discovery *out);
void discovery_destroy(Discovery *discovery);
/* Caller frees indices; sorted by descending floor(mtime_ns/1e6), size, path.
 * The discovery snapshot itself remains unchanged. */
Err discovery_processing_order(const Discovery *discovery, size_t **indices);
#endif
