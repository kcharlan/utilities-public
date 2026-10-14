#include "arena.h"
#include <stdint.h>
#include <stdlib.h>
struct ArenaChunk {
    struct ArenaChunk *next;
    size_t capacity, used;
    unsigned char data[];
};
Err arena_alloc(Arena *a, size_t size, size_t alignment, void **out) {
    *out = NULL;
    if (!alignment || (alignment & (alignment - 1)))
        return err_make(ERR_INVALID, "invalid arena alignment");
    if (size > SIZE_MAX - alignment || size + alignment > SIZE_MAX - sizeof(ArenaChunk))
        return err_make(ERR_NOMEM, "arena size overflow");
    ArenaChunk *c = a->head;
    size_t padding = 0;
    if (c)
        padding = (alignment - ((uintptr_t)(c->data + c->used) & (alignment - 1))) &
                  (alignment - 1);
    if (!c || padding > c->capacity - c->used ||
        size > c->capacity - c->used - padding) {
        size_t capacity = size + alignment;
        if (capacity < 65536)
            capacity = 65536;
        c = malloc(sizeof(*c) + capacity);
        if (!c)
            return err_make(ERR_NOMEM, "arena allocation failed");
        *c = (ArenaChunk){.next = a->head, .capacity = capacity};
        a->head = c;
        padding =
            (alignment - ((uintptr_t)c->data & (alignment - 1))) & (alignment - 1);
    }
    *out = c->data + c->used + padding;
    c->used += padding + size;
    return ERR_SUCCESS;
}
void arena_destroy(Arena *a) {
    while (a->head) {
        ArenaChunk *c = a->head;
        a->head = c->next;
        free(c);
    }
}
#ifdef COLOPHON_TESTING
size_t cp_test_arena_capacity(const Arena *a) {
    size_t total=0;
    for(const ArenaChunk *c=a->head;c;c=c->next)total+=c->capacity;
    return total;
}
#endif
