#define _POSIX_C_SOURCE 200809L
#define _DARWIN_C_SOURCE
#include "events.h"
#include "omap.h"
#include "testing/hooks.h"
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
typedef struct {
    char *type, *site;
    uint64_t count;
} Event;
static Omap pending;
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static bool lost, reported;
static void unavailable(const char *reason) {
    if (!reported) {
        fprintf(stderr, "colophon: event log unavailable: %s\n", reason);
        reported = true;
    }
}
/* The API accepts identifiers, not arbitrary JSON strings. Enforce ASCII and
 * reject filesystem separators so accidental content/path values stay out. */
static bool identifier(const char *s) {
    if (!s || !*s)
        return false;
    for (; *s; s++)
        if ((unsigned char)*s < 32 || (unsigned char)*s > 126 || *s == '/' ||
            *s == '\\' || *s == '"')
            return false;
    return true;
}
void event_note(const char *type, const char *site, uint64_t count) {
    if (!count)
        return;
    pthread_mutex_lock(&mutex);
    if (!identifier(type) || !identifier(site)) {
        lost = true;
        pthread_mutex_unlock(&mutex);
        return;
    }
    size_t tn = strlen(type), sn = strlen(site);
    if (tn >= UINT32_MAX || sn > UINT32_MAX - tn - 1) {
        lost = true;
        pthread_mutex_unlock(&mutex);
        return;
    }
    char *key = malloc(tn + sn + 1);
    if (!key) {
        lost = true;
        pthread_mutex_unlock(&mutex);
        return;
    }
    memcpy(key, type, tn + 1);
    memcpy(key + tn + 1, site, sn);
    Str k = {key, (uint32_t)(tn + sn + 1)};
    Event *e = omap_get(&pending, k);
    if (e)
        e->count = count > UINT64_MAX - e->count ? UINT64_MAX : e->count + count;
    else {
        e = calloc(1, sizeof(*e));
        if (e) {
            e->type = strdup(type);
            e->site = strdup(site);
            e->count = count;
        }
        if (!e || !e->type || !e->site || omap_put(&pending, k, e).code) {
            if (e) {
                free(e->type);
                free(e->site);
                free(e);
            }
            lost = true;
        }
    }
    free(key);
    pthread_mutex_unlock(&mutex);
}
void event_flush(const char *home) {
    pthread_mutex_lock(&mutex);
    Omap batch = pending;
    pending = (Omap){0};
    bool allocation_failed = lost;
    lost = false;
    pthread_mutex_unlock(&mutex);
    if (allocation_failed)
        unavailable("event allocation or invalid site");
    if (!batch.size || !home || !*home)
        goto cleanup;
    size_t n = strlen(home);
    if (n > SIZE_MAX - 64) {
        unavailable("home path too long");
        goto cleanup;
    }
    char *path = malloc(n + 64), *old = malloc(n + 64);
    if (!path || !old) {
        free(path);
        free(old);
        unavailable("path allocation failed");
        goto cleanup;
    }
    snprintf(path, n + 64, "%s/native-events.jsonl", home);
    snprintf(old, n + 64, "%s.1", path);
    struct stat st;
    if (lstat(path, &st) == 0) {
        if (!S_ISREG(st.st_mode)) {
            unavailable("event target is not a regular file");
            goto paths;
        }
        if (st.st_size > 1048576 && rename(path, old)) {
            unavailable(strerror(errno));
            goto paths;
        }
    } else if (errno != ENOENT) {
        unavailable(strerror(errno));
        goto paths;
    }
    int fd = open(path, O_WRONLY | O_CREAT | O_APPEND | O_NOFOLLOW, 0600);
    if (fd < 0) {
        unavailable(strerror(errno));
        goto paths;
    }
    if (fchmod(fd, 0600)) {
        unavailable(strerror(errno));
        close(fd);
        goto paths;
    }
    FILE *f = fdopen(fd, "a");
    if (!f) {
        unavailable(strerror(errno));
        close(fd);
        goto paths;
    }
    int64_t ts = cp_wall_ms();
    for (OmapEntry *entry = batch.first; entry; entry = entry->next) {
        Event *e = entry->value;
        if (fprintf(f,
                    "{\"ts\":%" PRId64
                    ",\"event\":\"%s\",\"site\":\"%s\",\"count\":%" PRIu64 "}\n",
                    ts, e->type, e->site, e->count) < 0) {
            unavailable(strerror(errno));
            break;
        }
    }
    if (fclose(f))
        unavailable(strerror(errno));
paths:
    free(path);
    free(old);
cleanup:
    for (OmapEntry *entry = batch.first; entry; entry = entry->next) {
        Event *e = entry->value;
        free(e->type);
        free(e->site);
        free(e);
    }
    omap_destroy(&batch);
}
