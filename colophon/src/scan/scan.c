#define _DARWIN_C_SOURCE
#include "scan.h"
#include "parse/record.h"
#include "testing/hooks.h"
#include "util/jobpool.h"
#include <errno.h>
#include <stdlib.h>
#include <sys/sysctl.h>

size_t scan_worker_count(void) {
    long count = 0;
#ifdef COLOPHON_WORKERS
    count = COLOPHON_WORKERS;
#else
    int physical = 1;
    size_t length = sizeof physical;
    if (sysctlbyname("hw.perflevel0.physicalcpu", &physical, &length, NULL, 0))
        physical = 1;
    count = physical;
#endif
#ifdef COLOPHON_TESTING
    const char *setting = getenv("COLOPHON_TEST_WORKERS");
    if (setting) {
        char *end;
        errno = 0;
        long override = strtol(setting, &end, 10);
        if (*setting && !*end && !errno && override > 0) count = override;
    }
#endif
    return count < 1 ? 1 : count > 16 ? 16 : (size_t)count;
}

typedef struct { LogRecord *record; Err error; bool hit, miss; } Slot;
typedef struct {
    ScanResult *scan;
    Cache *cache;
    const size_t *order, *jobs;
    size_t count;
    Slot *slots;
    bool parse;
    ScanProgress progress;
    void *progress_context;
    uint64_t total;
} Pool;
static Err cancelled_chunk(void *context) {
    (void)context;
    return jobpool_cancelled()
        ? err_make(ERR_IO, "interrupted") : ERR_SUCCESS;
}
static Err cancelled_line(void *context, const ReaderRawLine *line) {
    (void)line;
    return cancelled_chunk(context);
}
static Err worker(size_t job, void *context) {
    Pool *pool = context;
        size_t index = pool->jobs[job];
        Slot *slot = &pool->slots[index];
        const DiscoveredLog *key = &pool->scan->discovery.logs[pool->order[index]];
        if (!slot->error.code) {
            if (pool->parse) {
                ReaderCallbacks callbacks = {.context = pool, .chunk = cancelled_chunk,
                                             .raw_line = cancelled_line};
                slot->error = record_parse(key, &pool->scan->identifiers, &callbacks, slot->record);
            } else
                slot->error = cache_get(pool->cache, key, &pool->scan->identifiers,
                                        slot->record, &slot->hit);
        }
        return slot->error;
}
static Err collect(size_t j, Err result, void *context) {
        Pool *pool = context;
        Err e = ERR_SUCCESS;
        size_t index = pool->jobs[j];
        Slot *slot = &pool->slots[index];
        slot->error = result;
        const DiscoveredLog *key = &pool->scan->discovery.logs[pool->order[index]];
        if (slot->error.code == ERR_IO) {
            pool->scan->unreadable[pool->scan->unreadable_count++] = (UnreadableLog){key->path, slot->error};
            record_destroy(slot->record); free(slot->record); slot->record = NULL;
        } else if (slot->error.code) e = slot->error;
        else if (!pool->parse) {
            if (slot->hit) pool->scan->cached++;
            else slot->miss = true;
        } else {
            e = cache_put(pool->cache, slot->record);
            if (!e.code) {
                pool->scan->parsed++;
                pool->scan->bytes_parsed += (uint64_t)key->size;
                if (pool->progress) e = pool->progress(pool->scan->bytes_parsed, pool->total, pool->progress_context);
            }
        }
    return e;
}
static Err phase(Pool *pool, size_t workers, volatile sig_atomic_t *flag,
                 ScanProgress progress, void *context, uint64_t total) {
    pool->progress = progress; pool->progress_context = context; pool->total = total;
    JobStats stats = {0};
    Err e = jobpool_run(pool->count, workers, flag, worker, collect, pool, &stats);
#ifdef COLOPHON_TESTING
    if (pool->count) {
        if (pool->parse) pool->scan->parse_workers = stats.engaged;
        else pool->scan->lookup_workers = stats.engaged;
    }
#endif
    return e;
}
void scan_destroy(ScanResult *r) {
    for (size_t i = 0; i < r->count; i++) { record_destroy(r->records[i]); free(r->records[i]); }
    free(r->records); free(r->unreadable);
    omap_destroy(&r->live); discovery_destroy(&r->discovery);
    if (r->identifiers_initialized) intern_destroy(&r->identifiers);
    *r = (ScanResult){0};
}
static Err scan_impl(const char *codex, Cache *cache, volatile sig_atomic_t *flag,
                     ScanProgress progress, void *context, ScanResult *out) {
    tzset();
    Err e = intern_init(&out->identifiers);
    if (e.code) return e;
    out->identifiers_initialized = true;
    e = discover_logs(codex, &out->discovery);
    if (e.code) return e;
    size_t *order = NULL;
    e = discovery_processing_order(&out->discovery, &order);
    if (e.code) return e;
    size_t n = out->discovery.count;
    Slot *slots = calloc(n ? n : 1, sizeof *slots);
    size_t *jobs = calloc(n ? n : 1, sizeof *jobs);
    out->records = calloc(n ? n : 1, sizeof *out->records);
    out->unreadable = calloc(n ? n : 1, sizeof *out->unreadable);
    if (!slots || !jobs || !out->records || !out->unreadable) {
        e = err_make(ERR_NOMEM, "scan allocation failed"); goto done;
    }
    for (size_t i = 0; i < n; i++) {
        jobs[i] = i;
        e = omap_put(&out->live, out->discovery.logs[order[i]].path, out);
        if (e.code) goto done;
        slots[i].record = calloc(1, sizeof *slots[i].record);
        if (!slots[i].record) { e = err_make(ERR_NOMEM, "scan record allocation failed"); goto done; }
    }
    Pool pool = {.scan = out, .cache = cache, .order = order, .jobs = jobs, .count = n, .slots = slots};
    size_t workers = scan_worker_count();
    e = phase(&pool, workers, flag, NULL, NULL, 0);
    if (e.code) goto done;
    pool.count = 0;
    uint64_t total = 0;
    for (size_t i = 0; i < n; i++)
        if (slots[i].miss) {
            jobs[pool.count++] = i;
            total += (uint64_t)out->discovery.logs[order[i]].size;
        }
    pool.parse = true;
    e = phase(&pool, workers, flag, progress, context, total);
done:
    if (slots)
        for (size_t i = 0; i < n; i++)
            if (slots[i].record) {
                if (out->records) out->records[out->count++] = slots[i].record;
                else { record_destroy(slots[i].record); free(slots[i].record); }
            }
    free(slots); free(jobs); free(order);
    return e;
}
Err scan_logs(const char *codex, Cache *cache, volatile sig_atomic_t *flag, ScanProgress progress,
              void *context, ScanResult *out) {
    Err e = scan_impl(codex, cache, flag, progress, context, out);
    if (e.code) (void)cache_abort(cache);
    return e;
}
