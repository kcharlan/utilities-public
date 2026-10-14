#ifndef CP_SORT_H
#define CP_SORT_H
#include "err.h"
#include <stddef.h>
typedef int (*SortCompare)(const void *, const void *, void *);
Err stable_sort(void *base, size_t count, size_t width, SortCompare compare,
                void *context);
#endif
