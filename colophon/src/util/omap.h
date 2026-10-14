#ifndef CP_OMAP_H
#define CP_OMAP_H
#include "str.h"
typedef struct OmapEntry {
    Str key;
    void *value;
    struct OmapEntry *next, *prev, *bucket_next;
} OmapEntry;
typedef struct {
    OmapEntry **buckets, *first, *last;
    size_t capacity, size;
} Omap;
/* Zero-initialize. Owns keys/entries, never values. Lookups do not mutate iteration. */
Err omap_put(Omap *map, Str key, void *value);
void *omap_get(const Omap *map, Str key);
bool omap_delete(Omap *map, Str key, void **value);
bool omap_delete_oldest(Omap *map, void **value);
void omap_destroy(Omap *map);
#endif
