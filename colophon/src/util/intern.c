#include "intern.h"
#include <stdlib.h>
#include <string.h>
struct InternNode {
    Str key;
    struct InternNode *next;
    char data[];
};
/* Nodes and next links are immutable after release publication. Buckets never
 * move; acquire lookup pairs with publication and needs no reader lock.
 * The insertion mutex serializes duplicate checks, so identity is unique. */
Err intern_init(Intern *t) {
    for (size_t i = 0; i < 4096; i++)
        atomic_init(&t->buckets[i], NULL);
    if (pthread_mutex_init(&t->mutex, NULL))
        return err_make(ERR_NOMEM, "intern mutex failed");
    return ERR_SUCCESS;
}
static InternNode *lookup(Intern *t, size_t bucket, Str key) {
    for (InternNode *n =
             atomic_load_explicit(&t->buckets[bucket], memory_order_acquire);
         n; n = n->next)
        if (str_equal(n->key, key))
            return n;
    return NULL;
}
Err intern_get(Intern *t, Str key, Str *out) {
    size_t bucket = str_hash(key) % 4096;
    InternNode *n = lookup(t, bucket, key);
    if (n) {
        *out = n->key;
        return ERR_SUCCESS;
    }
    pthread_mutex_lock(&t->mutex);
    n = lookup(t, bucket, key);
    if (!n) {
        n = malloc(sizeof(*n) + (size_t)key.n + 1);
        if (!n) {
            pthread_mutex_unlock(&t->mutex);
            return err_make(ERR_NOMEM, "intern allocation failed");
        }
        if (key.n)
            memcpy(n->data, key.p, key.n);
        n->data[key.n] = 0;
        n->key = (Str){n->data, key.n};
        n->next = atomic_load_explicit(&t->buckets[bucket], memory_order_relaxed);
        atomic_store_explicit(&t->buckets[bucket], n, memory_order_release);
    }
    *out = n->key;
    pthread_mutex_unlock(&t->mutex);
    return ERR_SUCCESS;
}
void intern_destroy(Intern *t) {
    for (size_t i = 0; i < 4096; i++) {
        InternNode *n = atomic_load(&t->buckets[i]);
        while (n) {
            InternNode *next = n->next;
            free(n);
            n = next;
        }
    }
    pthread_mutex_destroy(&t->mutex);
}
