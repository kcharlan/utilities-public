#ifndef CP_ATOMIC_H
#define CP_ATOMIC_H
#include "err.h"
#include <stddef.h>
/* Publish a complete 0600 sibling temporary via fsync+rename. Failure removes
 * the temporary and preserves the destination. No directory fsync contract. */
Err atomic_write(const char *path, const void *bytes, size_t length);
#endif
