#ifndef CP_ARENA_H
#define CP_ARENA_H
#include "err.h"
#include <stddef.h>
typedef struct ArenaChunk ArenaChunk;
typedef struct {
    ArenaChunk *head;
} Arena;
/* Zero-initialize; pointers remain valid until destroy. Alignment is a power of two. */
Err arena_alloc(Arena *arena, size_t size, size_t alignment, void **output);
void arena_destroy(Arena *arena);
#ifdef COLOPHON_TESTING
size_t cp_test_arena_capacity(const Arena *arena);
#endif
#endif
