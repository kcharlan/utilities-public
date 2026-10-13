#include "omap.h"
#include <stdlib.h>
#include <string.h>
static OmapEntry *find(const Omap *m, Str key) {
    if (!m->capacity)
        return NULL;
    for (OmapEntry *e = m->buckets[str_hash(key) % m->capacity]; e; e = e->bucket_next)
        if (str_equal(e->key, key))
            return e;
    return NULL;
}
void *omap_get(const Omap *m, Str key) {
    OmapEntry *e = find(m, key);
    return e ? e->value : NULL;
}
Err omap_put(Omap *m, Str key, void *value) {
    OmapEntry *existing = find(m, key);
    if (existing) {
        existing->value = value;
        return ERR_SUCCESS;
    }
    if (!m->capacity || m->size >= m->capacity) {
        size_t cap = m->capacity ? m->capacity * 2 : 64;
        if (cap < m->capacity || cap > SIZE_MAX / sizeof(*m->buckets))
            return err_make(ERR_NOMEM, "map size overflow");
        OmapEntry **b = calloc(cap, sizeof(*b));
        if (!b)
            return err_make(ERR_NOMEM, "map allocation failed");
        for (OmapEntry *e = m->first; e; e = e->next) {
            size_t h = str_hash(e->key) % cap;
            e->bucket_next = b[h];
            b[h] = e;
        }
        free(m->buckets);
        m->buckets = b;
        m->capacity = cap;
    }
    OmapEntry *e = calloc(1, sizeof(*e));
    char *p = malloc((size_t)key.n + 1);
    if (!e || !p) {
        free(e);
        free(p);
        return err_make(ERR_NOMEM, "map allocation failed");
    }
    if (key.n)
        memcpy(p, key.p, key.n);
    p[key.n] = 0;
    e->key = (Str){p, key.n};
    e->value = value;
    e->prev = m->last;
    if (m->last)
        m->last->next = e;
    else
        m->first = e;
    m->last = e;
    size_t h = str_hash(key) % m->capacity;
    e->bucket_next = m->buckets[h];
    m->buckets[h] = e;
    m->size++;
    return ERR_SUCCESS;
}
bool omap_delete(Omap *m, Str key, void **value) {
    if (!m->capacity)
        return false;
    OmapEntry **link = &m->buckets[str_hash(key) % m->capacity];
    while (*link && !str_equal((*link)->key, key))
        link = &(*link)->bucket_next;
    if (!*link)
        return false;
    OmapEntry *e = *link;
    *link = e->bucket_next;
    if (e->prev)
        e->prev->next = e->next;
    else
        m->first = e->next;
    if (e->next)
        e->next->prev = e->prev;
    else
        m->last = e->prev;
    if (value)
        *value = e->value;
    free((void *)e->key.p);
    free(e);
    m->size--;
    return true;
}
bool omap_delete_oldest(Omap *m, void **value) {
    return m->first ? omap_delete(m, m->first->key, value) : false;
}
void omap_destroy(Omap *m) {
    while (m->first)
        omap_delete_oldest(m, NULL);
    free(m->buckets);
    *m = (Omap){0};
}
