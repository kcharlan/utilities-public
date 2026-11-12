#ifndef CP_JOBPOOL_H
#define CP_JOBPOOL_H
#include "err.h"
#include <signal.h>
#include <stdbool.h>
#include <stddef.h>
typedef Err (*JobWork)(size_t, void *);
typedef Err (*JobCollect)(size_t, Err, void *);
typedef struct { size_t engaged; } JobStats;
Err jobpool_run(size_t count, size_t workers, volatile sig_atomic_t *flag,
                JobWork work, JobCollect collect, void *context, JobStats *stats);
bool jobpool_cancelled(void);
#endif
