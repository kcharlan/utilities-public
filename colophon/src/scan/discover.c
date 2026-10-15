#include "discover.h"
#include "logname.h"
#include "resource.h"
#include "gen/assets.h"
#include "util/fileio.h"
#include "util/omap.h"
#include "util/pynum.h"
#include "util/sort.h"
#include "util/time.h"
#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#ifdef __APPLE__
#include <CoreFoundation/CoreFoundation.h>
#endif

typedef struct { char **items; size_t count, capacity; } Paths;

static void paths_destroy(Paths *paths) {
    for (size_t i = 0; i < paths->count; i++) free(paths->items[i]);
    free(paths->items);
    *paths = (Paths){0};
}

static Err paths_add(Paths *paths, const char *path) {
    if (paths->count == paths->capacity) {
        size_t capacity = paths->capacity ? paths->capacity * 2 : 32;
        char **items = realloc(paths->items, capacity * sizeof(*items));
        if (!items) return err_make(ERR_NOMEM, "discovery allocation failed");
        paths->items = items;
        paths->capacity = capacity;
    }
    char *copy = strdup(path);
    if (!copy) return err_make(ERR_NOMEM, "discovery allocation failed");
    paths->items[paths->count++] = copy;
    return ERR_SUCCESS;
}

static char *join(const char *parent, const char *name) {
    size_t a = strlen(parent), b = strlen(name);
    char *path = malloc(a + b + 2);
    if (path) {
        memcpy(path, parent, a);
        if (a) path[a++] = '/';
        memcpy(path+a, name, b+1);
    }
    return path;
}

static Err children(const char *parent, Paths *out) {
    DIR *directory = opendir(parent);
    if (!directory) return ERR_SUCCESS; /* Python's iterdir / os.walk ignore OSError. */
    Err err = ERR_SUCCESS;
    struct dirent *entry;
    while ((entry = readdir(directory))) {
        if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, "..")) continue;
        char *path = join(parent, entry->d_name);
        if (!path) { err = err_make(ERR_NOMEM, "discovery allocation failed"); break; }
        err = paths_add(out, path);
        free(path);
        if (err.code) break;
    }
    closedir(directory);
    return err;
}

static const char *basename_of(const char *path) { return strrchr(path, '/') + 1; }

static Err resource_property(bool darwin, const char *path, const void *key,
                             const ResourceOps *ops, bool *result) {
    *result = false;
    if (!darwin) return ERR_SUCCESS;
    void *url = ops->create(ops->context, path);
    if (!url) return ERR_SUCCESS;
    void *value = NULL, *error = NULL;
    bool ok = ops->copy(ops->context, url, key, &value, &error);
    Err e = ERR_SUCCESS;
    if (ok && value) e = ops->boolean(ops->context, value, result);
    if (value) ops->release(ops->context, value);
    if (error) ops->release(ops->context, error);
    ops->release(ops->context, url);
    return e;
}
#ifdef COLOPHON_TESTING
Err test_resource_property(bool darwin, const char *path, const void *key,
                           const ResourceOps *ops, bool *result) {
    return resource_property(darwin, path, key, ops, result);
}
#endif
#ifdef __APPLE__
static void *cf_create(void *context, const char *path) {
    (void)context;
    return (void *)CFURLCreateFromFileSystemRepresentation(NULL, (const UInt8 *)path,
                                                          (CFIndex)strlen(path), true);
}
static bool cf_copy(void *context, void *url, const void *key, void **value, void **error) {
    (void)context;
    CFTypeRef owned_value = NULL;
    CFErrorRef owned_error = NULL;
    bool ok = CFURLCopyResourcePropertyForKey(url, key, &owned_value, &owned_error);
    *value = (void *)owned_value; *error = (void *)owned_error;
    return ok;
}
static Err cf_boolean(void *context, void *value, bool *result) {
    (void)context;
    *result = CFBooleanGetValue(value);
    return ERR_SUCCESS;
}
static void cf_release(void *context, void *object) {
    (void)context; CFRelease(object);
}
static bool resource_flag(const char *path, CFStringRef key) {
    const ResourceOps ops = {NULL, cf_create, cf_copy, cf_boolean, cf_release};
    bool result;
    (void)resource_property(true, path, key, &ops, &result);
    return result;
}
#endif

bool discovery_hidden(const char *path) {
    if (*basename_of(path) == '.') return true;
#ifdef __APPLE__
    return resource_flag(path, kCFURLIsHiddenKey);
#else
    return false;
#endif
}

bool discovery_package(const char *path) {
#ifdef __APPLE__
    return resource_flag(path, kCFURLIsPackageKey);
#else
    (void)path; return false;
#endif
}

#define hidden discovery_hidden
#define package discovery_package

static bool directory(const char *path) {
    struct stat st;
    return !stat(path, &st) && S_ISDIR(st.st_mode);
}

static bool ascii_digits(const char *path, size_t count) {
    const char *name = basename_of(path);
    if (strlen(name) != count) return false;
    for (size_t i = 0; i < count; i++) if (name[i] < '0' || name[i] > '9') return false;
    return true;
}

static bool partition_year(const char *path) {
    const char *name = basename_of(path);
    Str text = {name, (uint32_t)strlen(name)};
    size_t offset = 0, count = 0;
    uint32_t cp;
    while (offset < text.n) {
        if (!str_decode_next(text, &offset, &cp)) return false;
        bool numeric = false;
        for (size_t i = 0; i < cp_pricing_numeric_ranges_count; i++) {
            if (cp < cp_pricing_numeric_ranges[i][0]) break;
            if (cp <= cp_pricing_numeric_ranges[i][1]) { numeric = true; break; }
        }
        if (!numeric || ++count > 4) return false;
    }
    return count == 4;
}

static Err visible_logs(const char *parent, Paths *candidates) {
    Paths entries = {0};
    Err err = children(parent, &entries);
    for (size_t i = 0; !err.code && i < entries.count; i++)
        if (!hidden(entries.items[i]) &&
            log_name_format((Str){entries.items[i], (uint32_t)strlen(entries.items[i])}) != LOG_NAME_OTHER)
            err = paths_add(candidates, entries.items[i]);
    paths_destroy(&entries);
    return err;
}

static Err partitions(const char *root, Paths *candidates) {
    Paths years = {0};
    Err err = children(root, &years);
    for (size_t y = 0; !err.code && y < years.count; y++) {
        if (!ascii_digits(years.items[y], 4) || !directory(years.items[y])) continue;
        Paths months = {0};
        err = children(years.items[y], &months);
        for (size_t m = 0; !err.code && m < months.count; m++) {
            if (!ascii_digits(months.items[m], 2) || !directory(months.items[m])) continue;
            Paths days = {0};
            err = children(months.items[m], &days);
            for (size_t d = 0; !err.code && d < days.count; d++) {
                if (!ascii_digits(days.items[d], 2) || !directory(days.items[d])) continue;
                char timestamp[21];
                snprintf(timestamp, sizeof timestamp, "%s-%s-%sT00:00:00Z",
                         basename_of(years.items[y]), basename_of(months.items[m]),
                         basename_of(days.items[d]));
                int64_t ms;
                if (time_parse_rfc3339((Str){timestamp, 20}, "discovery.partition", &ms))
                    err = visible_logs(days.items[d], candidates);
            }
            paths_destroy(&days);
        }
        paths_destroy(&months);
    }
    paths_destroy(&years);
    return err;
}

static Err legacy(const char *root, Paths *candidates) {
    Paths pending = {0};
    Err err = paths_add(&pending, root);
    for (size_t p = 0; !err.code && p < pending.count; p++) {
        Paths entries = {0};
        err = children(pending.items[p], &entries);
        for (size_t i = 0; !err.code && i < entries.count; i++) {
            const char *path = entries.items[i];
            if (hidden(path)) continue;
            bool is_dir = directory(path);
            if (is_dir && p == 0 && partition_year(path)) continue;
            if (log_name_format((Str){path, (uint32_t)strlen(path)}) != LOG_NAME_OTHER)
                err = paths_add(candidates, path);
            struct stat st;
            if (!err.code && is_dir && !package(path) && !lstat(path, &st) && !S_ISLNK(st.st_mode))
                err = paths_add(&pending, path);
        }
        paths_destroy(&entries);
    }
    paths_destroy(&pending);
    return err;
}

static int path_compare(const void *a, const void *b, void *context) {
    (void)context;
    const char *x = *(const char *const *)a, *y = *(const char *const *)b;
    return str_compare((Str){x, (uint32_t)strlen(x)}, (Str){y, (uint32_t)strlen(y)});
}

void discovery_destroy(Discovery *out) {
    free((void *)out->logs);
    if (out->paths_initialized) intern_destroy(&out->paths);
    *out = (Discovery){0};
}

Err discover_logs(const char *home, Discovery *out) {
    Err err = intern_init(&out->paths);
    if (err.code) return err;
    out->paths_initialized = true;
    Omap seen_paths = {0}, seen_ids = {0};
    size_t logs_capacity = 0;
    const char *roots[] = {"sessions", "archived_sessions"};
    for (size_t r = 0; !err.code && r < 2; r++) {
        Paths candidates = {0};
        char *joined = join(home, roots[r]), *root = NULL;
        if (!joined) { err = err_make(ERR_NOMEM, "discovery allocation failed"); break; }
        /* The shared lexical key preserves symlink spellings. Rewriting the
         * common root prefix does not change candidate ordering within it. */
        err = file_codex_path_key(joined, &root);
        free(joined);
        if (!err.code) err = visible_logs(root, &candidates);
        if (!err.code) err = partitions(root, &candidates);
        if (!err.code) err = legacy(root, &candidates);
        if (!err.code) err = stable_sort(candidates.items, candidates.count, sizeof(char *), path_compare, NULL);
        Omap plain = {0};
        for (size_t i = 0; !err.code && i < candidates.count; i++) {
            Str spelling = {candidates.items[i], (uint32_t)strlen(candidates.items[i])};
            if (log_name_format(spelling) == LOG_NAME_PLAIN) err = omap_put(&plain, spelling, (void *)1);
        }
        for (size_t i = 0; !err.code && i < candidates.count; i++) {
            Str spelling = {candidates.items[i], (uint32_t)strlen(candidates.items[i])};
            /* Codex writes NAME.jsonl.zst beside NAME.jsonl and removes the plain
             * log later; until then the plain copy may still be growing. */
            if (log_name_format(spelling) == LOG_NAME_ZSTD &&
                omap_get(&plain, (Str){spelling.p, spelling.n - 4})) continue;
            char *key = NULL;
            err = file_codex_path_key(candidates.items[i], &key);
            if (err.code) break;
            Str path = {key, (uint32_t)strlen(key)};
            if (omap_get(&seen_paths, path)) { free(key); continue; }
            err = omap_put(&seen_paths, path, (void *)1);
            DiscoveredLog log = {.archived = r == 1};
            struct stat st;
            if (!err.code && !stat(key, &st)) {
                log.stat_ok = true; log.device = st.st_dev; log.inode = st.st_ino;
                log.size = st.st_size;
#ifdef __APPLE__
                log.mtime_ns = (int64_t)st.st_mtimespec.tv_sec * 1000000000 + st.st_mtimespec.tv_nsec;
#else
                log.mtime_ns = (int64_t)st.st_mtim.tv_sec * 1000000000 + st.st_mtim.tv_nsec;
#endif
                char identity[80];
                int n = snprintf(identity, sizeof identity, "%llu:%llu", (unsigned long long)st.st_dev, (unsigned long long)st.st_ino);
                Str id = {identity, (uint32_t)n};
                if (omap_get(&seen_ids, id)) { free(key); continue; }
                err = omap_put(&seen_ids, id, (void *)1);
            }
            if (!err.code) err = intern_get(&out->paths, path, &log.path);
            free(key);
            if (err.code) break;
            if (out->count == logs_capacity) {
                size_t capacity = logs_capacity ? logs_capacity * 2 : 32;
                DiscoveredLog *logs = realloc((void *)out->logs, capacity * sizeof(*logs));
                if (!logs) { err = err_make(ERR_NOMEM, "discovery allocation failed"); break; }
                out->logs = logs;
                logs_capacity = capacity;
            }
            ((DiscoveredLog *)out->logs)[out->count++] = log;
        }
        omap_destroy(&plain);
        free(root);
        paths_destroy(&candidates);
    }
    omap_destroy(&seen_paths); omap_destroy(&seen_ids);
    if (err.code) discovery_destroy(out);
    return err;
}

static int processing_compare(const void *a, const void *b, void *context) {
    const Discovery *discovery = context;
    const DiscoveredLog *x = &discovery->logs[*(const size_t *)a], *y = &discovery->logs[*(const size_t *)b];
    int64_t xm, ym;
    (void)floordiv_i64(x->mtime_ns, 1000000, &xm);
    (void)floordiv_i64(y->mtime_ns, 1000000, &ym);
    if (xm != ym) return xm > ym ? -1 : 1;
    if (x->size != y->size) return x->size < y->size ? -1 : 1;
    return str_compare(x->path, y->path);
}

Err discovery_processing_order(const Discovery *discovery, size_t **indices) {
    *indices = NULL;
    if (!discovery->count) return ERR_SUCCESS;
    size_t *order = malloc(discovery->count * sizeof(*order));
    if (!order) return err_make(ERR_NOMEM, "discovery allocation failed");
    for (size_t i = 0; i < discovery->count; i++) order[i] = i;
    Err err = stable_sort(order, discovery->count, sizeof(*order), processing_compare, (void *)discovery);
    if (err.code) free(order); else *indices = order;
    return err;
}
