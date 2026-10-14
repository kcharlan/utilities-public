#ifndef CP_INTERN_H
#define CP_INTERN_H
#include "str.h"
#include <pthread.h>
#include <stdatomic.h>
typedef struct InternNode InternNode;
typedef struct {
    pthread_mutex_t mutex;
    _Atomic(InternNode *) buckets[4096];
} Intern;
Err intern_init(Intern *table);
Err intern_get(Intern *table, Str input, Str *output);
/* All workers must have joined before destroying. */
void intern_destroy(Intern *table);
#endif
