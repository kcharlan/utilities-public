#ifndef CP_SCAN_H
#define CP_SCAN_H
#include "cache/cache.h"
typedef struct {
    Str path;
    Err error;
} UnreadableLog;
typedef struct {
    Discovery discovery;
    Intern identifiers;
    bool identifiers_initialized;
    Omap live;
    LogRecord **records;
    size_t count, parsed, cached;
    uint64_t bytes_parsed;
    UnreadableLog *unreadable;
    size_t unreadable_count;
#ifdef COLOPHON_TESTING
    size_t lookup_workers, parse_workers;
#endif
} ScanResult;
typedef Err (*ScanProgress)(uint64_t done, uint64_t total, void *context);
/* Owns records, immutable discovery, and run Intern (destroyed in that order).
 * Cache borrows records; commit/abort before destroying the scan result.
 * Two-phase workers; hits looked up first, misses then parsed in frozen
 * processing order. Unreadable paths remain live for deferred pruning. */
Err scan_logs(const char *codex_home, Cache *cache, volatile sig_atomic_t *interrupted,
              ScanProgress progress, void *context, ScanResult *out);
void scan_destroy(ScanResult *result);
size_t scan_worker_count(void);
#endif
