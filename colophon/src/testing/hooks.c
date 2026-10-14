#define _POSIX_C_SOURCE 200809L
#include "hooks.h"
#include "util/omap.h"
#include <errno.h>
#include <math.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
static const char *sequence;
static char *owned;
static char *fault_setting;
static Omap fault_points;
static pthread_mutex_t fault_mutex = PTHREAD_MUTEX_INITIALIZER;
typedef struct {
    uint64_t calls, nth;
    bool every;
} FaultPoint;
static void clear_faults(void) {
    for (OmapEntry *e = fault_points.first; e; e = e->next)
        free(e->value);
    omap_destroy(&fault_points);
    free(fault_setting);
    fault_setting = NULL;
}
/* Malformed tokens are ignored; the first valid occurrence of a duplicated
 * name wins. Positive decimal :k selects one call; a bare name selects all.
 * Environment changes happen only between workers/runs. All retained config
 * and counters are owned and protected by the same mutex. */
static void load_faults(const char *setting) {
    clear_faults();
    fault_setting = strdup(setting);
    if (!fault_setting)
        return;
    char *cursor = fault_setting;
    while (*cursor) {
        char *end = strchr(cursor, ',');
        if (end)
            *end = 0;
        char *colon = strchr(cursor, ':');
        size_t length = colon ? (size_t)(colon - cursor) : strlen(cursor);
        bool valid = length != 0;
        uint64_t nth = 0;
        if (colon) {
            const char *digits = colon + 1;
            valid = valid && *digits;
            for (const char *p = digits; *p; p++)
                if (*p < '0' || *p > '9')
                    valid = false;
            errno = 0;
            char *last;
            unsigned long long value = strtoull(digits, &last, 10);
            valid = valid && !errno && !*last && value != 0;
            nth = value;
        }
        Str name = {cursor, (uint32_t)length};
        if (valid && !omap_get(&fault_points, name)) {
            FaultPoint *point = calloc(1, sizeof *point);
            if (point) {
                point->nth = nth;
                point->every = !colon;
                if (omap_put(&fault_points, name, point).code)
                    free(point);
            }
        }
        if (!end)
            break;
        *end = ',';
        cursor = end + 1;
    }
}
bool cp_fault(const char *point) {
    pthread_mutex_lock(&fault_mutex);
    const char *s = getenv("COLOPHON_TEST_FAULT");
    bool hit = false;
    if (!s)
        clear_faults();
    else {
        if (!fault_setting || strcmp(fault_setting, s))
            load_faults(s);
        FaultPoint *value = omap_get(&fault_points, (Str){point, (uint32_t)strlen(point)});
        if (value) {
            if (value->calls < UINT64_MAX)
                value->calls++;
            hit = value->every || value->calls == value->nth;
        }
    }
    pthread_mutex_unlock(&fault_mutex);
    return hit;
}
static _Thread_local int atomic_observed_fd=-1;
static _Thread_local unsigned atomic_observed_closes;
void cp_atomic_created(int fd){atomic_observed_fd=fd;atomic_observed_closes=0;}
void cp_atomic_closed(int fd){if(fd==atomic_observed_fd)atomic_observed_closes++;}
int cp_atomic_fd(void){return atomic_observed_fd;}
unsigned cp_atomic_close_count(void){return atomic_observed_closes;}
size_t cp_page_warn_bytes(void) {
    const char *s = getenv("COLOPHON_TEST_PAGE_WARN_BYTES");
    if (!s)
        return 20u * 1024u * 1024u;
    char *end;
    unsigned long long n = strtoull(s, &end, 10);
    return *s && !*end ? (size_t)n : 20u * 1024u * 1024u;
}
bool cp_browser_fallback_fail(void) {
    const char *s = getenv("COLOPHON_TEST_BROWSER_FALLBACK");
    return s && !strcmp(s, "fail");
}
static int64_t override(const char *name) {
    const char *s = getenv(name);
    if (!s)
        return cp_real_wall_ms();
    char *end;
    long long value = strtoll(s, &end, 10);
    return *s && !*end ? (int64_t)value : cp_real_wall_ms();
}
int64_t cp_now_ms(void) {
    return override("COLOPHON_TEST_NOW_MS");
}
int64_t cp_wall_ms(void) {
    return override("COLOPHON_TEST_WALL_MS");
}
int64_t cp_catalog_budget(const char *name,int64_t fallback) {
    const char *s=getenv(name);if(!s||!*s)return fallback;
    const char *digits=*s=='-'?s+1:s;if(!*digits)return fallback;
    for(const char *p=digits;*p;p++)if(*p<'0'||*p>'9')return fallback;
    char *end;errno=0;long long value=strtoll(s,&end,10);
    int64_t minimum=!strcmp(name,"COLOPHON_TEST_JOIN_EXTRA_MS")?-3600000:0;
    return !errno&&!*end&&value>=minimum&&value<=3600000?(int64_t)value:fallback;
}
Err cp_monotonic_start(void) {
    free(owned);
    owned = NULL;
    sequence = NULL;
    const char *s = getenv("COLOPHON_TEST_MONOTONIC");
    if (s) {
        owned = strdup(s);
        if (!owned)
            return err_make(ERR_NOMEM, "clock sequence allocation failed");
        sequence = owned;
    }
    return ERR_SUCCESS;
}
Err cp_monotonic(double *out) {
    if (sequence) {
        if (!*sequence)
            return err_make(ERR_INVALID, "monotonic sequence exhausted");
        char *end;
        double v = strtod(sequence, &end);
        if (end == sequence || !isfinite(v) || (*end && (*end != ',' || !end[1])))
            return err_make(ERR_INVALID, "invalid monotonic sequence");
        *out = v;
        sequence = *end ? end + 1 : end;
        return ERR_SUCCESS;
    }
    return cp_real_monotonic(out);
}
Err cp_monotonic_finish(void) {
    bool unused = sequence && *sequence;
    free(owned);
    owned = NULL;
    sequence = NULL;
    return unused ? err_make(ERR_INVALID, "monotonic sequence not fully consumed") : ERR_SUCCESS;
}
