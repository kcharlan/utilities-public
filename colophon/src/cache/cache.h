#ifndef CP_CACHE_H
#define CP_CACHE_H
#include "codec.h"
#include <signal.h>
typedef struct {
    char *home, *installed, *directory;
    bool rebuild, read_enabled, finished, committed, stage_owned;
    Omap buffer; /* Borrowed successful records; caller outlives commit/abort. */
    Err abort_cleanup_error;
} Cache;
Err cache_open(const char *home, bool rebuild, Cache *out);
/* Successful miss leaves hit=false; log tail IO errors propagate ERR_IO. */
Err cache_get(Cache *cache, const DiscoveredLog *key, Intern *ids, LogRecord *out, bool *hit);
Err cache_put(Cache *cache, LogRecord *record);
Err cache_commit(Cache *cache, const Omap *live, volatile sig_atomic_t *interrupted);
Err cache_abort(Cache *cache);
void cache_destroy(Cache *cache);
void cache_entry_name(Str path, char name[69]);
#endif
