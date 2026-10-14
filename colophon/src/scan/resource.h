#ifndef CP_RESOURCE_H
#define CP_RESOURCE_H
#include "util/err.h"
#include <stdbool.h>
/* Explicit owned-resource operations. Production always supplies fixed CF
 * adapters; test calls supply per-call state, never mutable global overrides. */
typedef struct {
    void *context;
    void *(*create)(void *context, const char *path);
    bool (*copy)(void *context, void *url, const void *key, void **value, void **error);
    Err (*boolean)(void *context, void *value, bool *result);
    void (*release)(void *context, void *object);
} ResourceOps;
#ifdef COLOPHON_TESTING
Err test_resource_property(bool darwin, const char *path, const void *key,
                           const ResourceOps *operations, bool *result);
#endif
#endif
