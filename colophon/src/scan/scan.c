#define _DARWIN_C_SOURCE
#include "scan.h"
#include "parse/record.h"
#include "testing/hooks.h"
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <time.h>
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

typedef struct { LogRecord *record; Err error; bool hit, ready, miss; } Slot;
typedef struct {
    ScanResult *scan;
    Cache *cache;
    const size_t *order, *jobs;
    size_t count, next;
    Slot *slots;
    bool parse;
    atomic_bool cancelled;
    pthread_mutex_t mutex;
    pthread_cond_t changed;
#ifdef COLOPHON_TESTING
    size_t engaged;
#endif
} Pool;
static Err cancelled_chunk(void *context) {
    Pool *pool = context;
    return atomic_load_explicit(&pool->cancelled, memory_order_relaxed)
        ? err_make(ERR_IO, "interrupted") : ERR_SUCCESS;
}
static Err cancelled_line(void *context, const ReaderRawLine *line) {
    (void)line;
    return cancelled_chunk(context);
}
static void *worker(void *context) {
    Pool *pool = context;
#ifdef COLOPHON_TESTING
    bool engaged = false;
#endif
    /* Workers inherit SIGINT blocked; the main thread handles cancellation. */
    for (;;) {
        pthread_mutex_lock(&pool->mutex);
        if (pool->next == pool->count || atomic_load(&pool->cancelled)) {
            pthread_mutex_unlock(&pool->mutex); return NULL;
        }
        size_t index = pool->jobs[pool->next++];
#ifdef COLOPHON_TESTING
        if (!engaged) { pool->engaged++; engaged = true; }
#endif
        pthread_mutex_unlock(&pool->mutex);
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
        pthread_mutex_lock(&pool->mutex);
        slot->ready = true;
        pthread_cond_broadcast(&pool->changed);
        pthread_mutex_unlock(&pool->mutex);
    }
}
static Err phase(Pool *pool, size_t workers, volatile sig_atomic_t *flag,
                 ScanProgress progress, void *context, uint64_t total) {
    if (!pool->count) return ERR_SUCCESS;
    pthread_t threads[16];
    size_t started = 0;
    Err e = ERR_SUCCESS;
    atomic_init(&pool->cancelled, false);
    pool->next = 0;
#ifdef COLOPHON_TESTING
    pool->engaged = 0;
#endif
    if (pthread_mutex_init(&pool->mutex, NULL)) return err_make(ERR_NOMEM, "scan mutex failed");
    if (pthread_cond_init(&pool->changed, NULL)) {
        pthread_mutex_destroy(&pool->mutex); return err_make(ERR_NOMEM, "scan condition failed");
    }
    sigset_t blocked, previous;
    sigemptyset(&blocked); sigaddset(&blocked, SIGINT);
    if (pthread_sigmask(SIG_BLOCK, &blocked, &previous)) {
        e = err_make(ERR_IO, "scan signal mask failed"); goto cleanup;
    }
    for (; started < workers && started < pool->count; started++)
        if (pthread_create(&threads[started], NULL, worker, pool)) {
            e = err_make(ERR_NOMEM, "scan worker creation failed"); break;
        }
    pthread_sigmask(SIG_SETMASK, &previous, NULL);
    for (size_t j = 0; !e.code && j < pool->count; j++) {
        size_t index = pool->jobs[j];
        Slot *slot = &pool->slots[index];
        pthread_mutex_lock(&pool->mutex);
        while (!slot->ready && !(flag && *flag)) {
            struct timespec until;
            timespec_get(&until, TIME_UTC); until.tv_nsec += 10000000;
            if (until.tv_nsec >= 1000000000) { until.tv_sec++; until.tv_nsec -= 1000000000; }
            pthread_cond_timedwait(&pool->changed, &pool->mutex, &until);
        }
        pthread_mutex_unlock(&pool->mutex);
        if (flag && *flag) { e = err_make(ERR_IO, "interrupted"); break; }
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
                if (progress) e = progress(pool->scan->bytes_parsed, total, context);
            }
        }
    }
    if (e.code) atomic_store(&pool->cancelled, true);
    for (size_t i = 0; i < started; i++) pthread_join(threads[i], NULL);
#ifdef COLOPHON_TESTING
    if (pool->parse) pool->scan->parse_workers = pool->engaged;
    else pool->scan->lookup_workers = pool->engaged;
#endif
cleanup:
    pthread_cond_destroy(&pool->changed); pthread_mutex_destroy(&pool->mutex);
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
            slots[i].ready = false;
            jobs[pool.count++] = i;
            total += (uint64_t)out->discovery.logs[order[i]].size;
#ifdef COLOPHON_TESTING
            const char *failure = getenv("COLOPHON_TEST_FAIL_AT");
            if (failure && strtoull(failure, NULL, 10) == pool.count)
                slots[i].error = err_make(ERR_INVALID, "synthetic injected parse failure");
            else if (cp_fault("parse_log")) slots[i].error = err_make(ERR_IO, "synthetic injected parse_log");
            const char *selected=getenv("COLOPHON_TEST_FAIL_PATH");
            if(selected && !strcmp(selected,out->discovery.logs[order[i]].path.p) && cp_fault("parse_selected"))
                slots[i].error=err_make(ERR_IO,"Synthetic unreadable log");
#endif
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
