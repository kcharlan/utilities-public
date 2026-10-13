#ifndef CP_HOOKS_H
#define CP_HOOKS_H
#include "util/err.h"
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <time.h>
static inline int64_t cp_real_wall_ms(void) {
    struct timespec ts;
    timespec_get(&ts, TIME_UTC);
    return (int64_t)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}
static inline Err cp_real_monotonic(double *seconds) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts))
        return err_make(ERR_IO, "monotonic clock unavailable");
    *seconds = (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
    return ERR_SUCCESS;
}
/* Production clock wrappers are inline; test override symbols stay test-only. */
#ifdef COLOPHON_TESTING
int64_t cp_now_ms(void);
int64_t cp_wall_ms(void);
Err cp_monotonic_start(void);
Err cp_monotonic(double *seconds);
Err cp_monotonic_finish(void);
bool cp_fault(const char *point);
void cp_atomic_created(int fd);
void cp_atomic_closed(int fd);
int cp_atomic_fd(void);
unsigned cp_atomic_close_count(void);
size_t cp_page_warn_bytes(void);
bool cp_browser_fallback_fail(void);
int64_t cp_catalog_budget(const char *name,int64_t fallback);
#else
/* Sanitizer instrumentation at -O1 may otherwise emit a local override-named
 * function despite static inline. Release has no hook symbols at any build. */
#define CP_RELEASE_INLINE static inline __attribute__((always_inline))
CP_RELEASE_INLINE int64_t cp_wall_ms(void) {
    return cp_real_wall_ms();
}
CP_RELEASE_INLINE int64_t cp_now_ms(void) {
    return cp_wall_ms();
}
CP_RELEASE_INLINE Err cp_monotonic_start(void) {
    return ERR_SUCCESS;
}
CP_RELEASE_INLINE Err cp_monotonic(double *seconds) {
    return cp_real_monotonic(seconds);
}
CP_RELEASE_INLINE Err cp_monotonic_finish(void) {
    return ERR_SUCCESS;
}
CP_RELEASE_INLINE bool cp_fault(const char *point) { (void)point;return false; }
CP_RELEASE_INLINE size_t cp_page_warn_bytes(void) { return 20u*1024u*1024u; }
CP_RELEASE_INLINE bool cp_browser_fallback_fail(void) { return false; }
CP_RELEASE_INLINE int64_t cp_catalog_budget(const char *name,int64_t fallback) {(void)name;return fallback;}
#undef CP_RELEASE_INLINE
#endif
#endif
