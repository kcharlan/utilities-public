#include "jobpool.h"
#include <pthread.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <time.h>
typedef struct { Err result; bool ready; } Slot;
typedef struct {
    size_t count, next, engaged;
    Slot *slots;
    JobWork work;
    void *context;
    atomic_bool cancelled;
    pthread_mutex_t mutex;
    pthread_cond_t changed;
} Pool;
static _Thread_local Pool *current;
bool jobpool_cancelled(void) { return current && atomic_load(&current->cancelled); }
static void *worker(void *arg) {
    Pool *p = arg; bool engaged = false; current = p;
    for (;;) {
        pthread_mutex_lock(&p->mutex);
        if (p->next == p->count || atomic_load(&p->cancelled)) {
            pthread_mutex_unlock(&p->mutex); current = NULL; return NULL;
        }
        size_t i = p->next++;
        if (!engaged) { p->engaged++; engaged = true; }
        pthread_mutex_unlock(&p->mutex);
        Err result = p->work(i, p->context);
        pthread_mutex_lock(&p->mutex);
        p->slots[i] = (Slot){result, true};
        pthread_cond_broadcast(&p->changed);
        pthread_mutex_unlock(&p->mutex);
    }
}
Err jobpool_run(size_t count, size_t workers, volatile sig_atomic_t *flag,
                JobWork work, JobCollect collect, void *context, JobStats *stats) {
    if (stats) *stats = (JobStats){0};
    if (!count) return ERR_SUCCESS;
    Pool p = {.count=count, .work=work, .context=context};
    p.slots = calloc(count, sizeof *p.slots);
    if (!p.slots) return err_make(ERR_NOMEM, "scan allocation failed");
    atomic_init(&p.cancelled, false);
    if (pthread_mutex_init(&p.mutex, NULL)) { free(p.slots); return err_make(ERR_NOMEM, "scan mutex failed"); }
    if (pthread_cond_init(&p.changed, NULL)) { pthread_mutex_destroy(&p.mutex); free(p.slots); return err_make(ERR_NOMEM, "scan condition failed"); }
    pthread_t threads[16]; size_t started = 0; Err e = ERR_SUCCESS;
    sigset_t blocked, previous;
    sigemptyset(&blocked); sigaddset(&blocked, SIGINT);
    if (pthread_sigmask(SIG_BLOCK, &blocked, &previous)) { e=err_make(ERR_IO, "scan signal mask failed"); goto cleanup; }
    if (!workers) workers = 1;
    for (; started < workers && started < count && started < 16; started++)
        if (pthread_create(&threads[started], NULL, worker, &p)) { e=err_make(ERR_NOMEM, "scan worker creation failed"); break; }
    pthread_sigmask(SIG_SETMASK, &previous, NULL);
    for (size_t i=0; !e.code && i<count; i++) {
        pthread_mutex_lock(&p.mutex);
        while (!p.slots[i].ready && !(flag && *flag)) {
            struct timespec until; timespec_get(&until, TIME_UTC); until.tv_nsec += 10000000;
            if (until.tv_nsec >= 1000000000) { until.tv_sec++; until.tv_nsec -= 1000000000; }
            pthread_cond_timedwait(&p.changed, &p.mutex, &until);
        }
        pthread_mutex_unlock(&p.mutex);
        if (flag && *flag) { e=err_make(ERR_IO, "interrupted"); break; }
        e=collect(i, p.slots[i].result, context);
    }
    if (e.code) atomic_store(&p.cancelled, true);
    for (size_t i=0; i<started; i++) pthread_join(threads[i], NULL);
    if (stats) stats->engaged = p.engaged;
cleanup:
    pthread_cond_destroy(&p.changed); pthread_mutex_destroy(&p.mutex); free(p.slots);
    return e;
}
