#define _DARWIN_C_SOURCE
#include "cache.h"
#include "parse/record.h"
#include "testing/cache_faults.h"
#include "testing/hooks.h"
#include "util/atomic.h"
#include "util/fileio.h"
#include "util/sha256.h"
#include "util/sort.h"
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <fts.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
static const char format[] = "native:1:2";
static char *join(const char *dir, const char *name) {
    size_t n = strlen(dir) + strlen(name) + 2;
    char *p = malloc(n);
    if (p)
        snprintf(p, n, "%s/%s", dir, name);
    return p;
}
static Err io(const char *operation) {
    char text[256];
    return err_make(ERR_IO, "cache %s failed: %s", operation, err_system(errno, text));
}
/* Physical traversal never follows a symlink outside the owned cache tree. */
static Err remove_tree(const char *path) {
    struct stat st;
    if (lstat(path, &st))
        return errno == ENOENT ? ERR_SUCCESS : io("stat");
    if (!S_ISDIR(st.st_mode)) {
        errno = ENOTDIR;
        return io("traversal");
    }
    char *paths[] = {(char *)path, NULL};
    FTS *tree = fts_open(paths, FTS_PHYSICAL | FTS_NOCHDIR, NULL);
    if (!tree)
        return io("traversal");
    Err e = ERR_SUCCESS;
    FTSENT *entry;
    for (;;) {
        errno = 0;
        entry = fts_read(tree);
        if (!entry) {
            if (errno)
                e = io("traversal");
            break;
        }
        int result = 0;
        if (entry->fts_info == FTS_DP)
            result = rmdir(entry->fts_path);
        else if (entry->fts_info == FTS_D)
            continue;
        else if (entry->fts_info == FTS_ERR || entry->fts_info == FTS_DNR ||
                 entry->fts_info == FTS_NS) {
            errno = entry->fts_errno;
            e = io("traversal");
            break;
        } else
            result = unlink(entry->fts_path);
        if (result && errno != ENOENT) {
            e = io("remove");
            break;
        }
    }
    if (fts_close(tree) && !e.code)
        e = io("close");
    return e;
}
static int compare_names(const void *a, const void *b, void *ctx) {
    (void)ctx;
    return strcmp(*(char *const *)a, *(char *const *)b);
}
static Err recover(Cache *c) {
    DIR *dir = opendir(c->home);
    if (!dir)
        return io("open directory");
    char **names = NULL;
    size_t count = 0;
    Err e = ERR_SUCCESS;
    struct dirent *entry;
    while ((entry = readdir(dir))) {
        const char *suffix = NULL;
        if (!strncmp(entry->d_name, "cache-native.old-", 17))
            suffix = entry->d_name + 17;
        else if (!strncmp(entry->d_name, "cache-native.rebuild-", 21))
            suffix = entry->d_name + 21;
        if (!suffix || !*suffix)
            continue;
        bool digits = true;
        for (const char *p = suffix; *p; p++)
            if (*p < '0' || *p > '9')
                digits = false;
        if (!digits)
            continue;
        errno = 0;
        char *end;
        unsigned long long pid = strtoull(suffix, &end, 10);
        if (errno || *end || !pid || pid > INT_MAX)
            continue;
        if (!kill((pid_t)pid, 0) || errno != ESRCH)
            continue;
        char *path = join(c->home, entry->d_name);
        if (!path) {
            e = err_make(ERR_NOMEM, "cache recovery allocation failed");
            break;
        }
        struct stat st;
        if (lstat(path, &st) || !S_ISDIR(st.st_mode)) {
            free(path);
            continue;
        }
        char **next = realloc(names, (count + 1) * sizeof *names);
        if (!next) {
            free(path);
            e = err_make(ERR_NOMEM, "cache recovery allocation failed");
            break;
        }
        names = next;
        names[count++] = path;
    }
    closedir(dir);
    if (!e.code)
        e = stable_sort(names, count, sizeof *names, compare_names, NULL);
    for (size_t i = 0; i < count && !e.code; i++) {
        struct stat st;
        bool absent = lstat(c->installed, &st) && errno == ENOENT;
        const char *base = strrchr(names[i], '/') + 1;
        if (!strncmp(base, "cache-native.old-", 17) && absent) {
            if (rename(names[i], c->installed))
                e = io("recover rename");
        } else
            e = remove_tree(names[i]);
    }
    for (size_t i = 0; i < count; i++)
        free(names[i]);
    free(names);
    return e;
}
void cache_entry_name(Str path, char name[69]) {
    sha256_hex(path.p, path.n, name);
    memcpy(name + 64, ".rec", 5);
}
static Err open_cache(const char *home, bool rebuild, Cache *c) {
    *c = (Cache){.rebuild = rebuild};
    c->home = strdup(home);
    c->installed = join(home, "cache-native");
    if (!c->home || !c->installed)
        return err_make(ERR_NOMEM, "cache path allocation failed");
    Err e = recover(c);
    if (e.code)
        return e;
    if (rebuild) {
        char name[80];
        snprintf(name, sizeof name, "cache-native.rebuild-%d", getpid());
        c->directory = join(home, name);
    } else
        c->directory = strdup(c->installed);
    if (!c->directory)
        return err_make(ERR_NOMEM, "cache path allocation failed");
    if (rebuild) {
        if (mkdir(c->directory, 0700))
            return io("stage mkdir");
        c->stage_owned = true;
        c->read_enabled = true;
    } else {
        char *marker = join(c->installed, "FORMAT"), *data = NULL;
        size_t n = 0;
        if (!marker)
            return err_make(ERR_NOMEM, "cache marker allocation failed");
        struct stat st;
        bool missing = lstat(marker, &st) && errno == ENOENT;
        e = file_read_all(marker, &data, &n);
        free(marker);
        c->read_enabled = !e.code && n == sizeof format - 1 && !memcmp(data, format, n);
        free(data);
        if (!c->read_enabled && !missing) {
            e = remove_tree(c->installed);
            if (e.code)
                return e;
        }
        e = ensure_runtime_home(c->directory);
        if (e.code)
            return e;
    }
    if (rebuild) {
        char *marker = join(c->directory, "FORMAT");
        if (!marker)
            return err_make(ERR_NOMEM, "cache marker allocation failed");
        e = cp_fault("cache_format_write")
                ? err_make(ERR_IO, "synthetic injected cache_format_write")
                : atomic_write(marker, format, sizeof format - 1);
        free(marker);
        return e;
    }
    return ERR_SUCCESS;
}
Err cache_open(const char *home, bool rebuild, Cache *c) {
    Err e = open_cache(home, rebuild, c);
    if (e.code)
        (void)cache_abort(c); /* Keep primary failure; retain cleanup error separately. */
    return e;
}
Err cache_get(Cache *c, const DiscoveredLog *key, Intern *ids, LogRecord *out, bool *hit) {
    *hit = false;
    if (c->rebuild || c->finished || !c->read_enabled)
        return ERR_SUCCESS;
    char name[69];
    cache_entry_name(key->path, name);
    char *path = join(c->directory, name), *data = NULL;
    size_t length = 0;
    if (!path)
        return err_make(ERR_NOMEM, "cache entry path allocation failed");
    Err e = file_read_all(path, &data, &length);
    free(path);
    if (e.code) {
        free(data);
        return e.code == ERR_NOMEM ? e : ERR_SUCCESS;
    }
    e = codec_decode(data, length, key, NULL, ids, out);
    free(data);
    if (e.code)
        return e.code == ERR_NOMEM ? e : ERR_SUCCESS;
    int fd = open(key->path.p, O_RDONLY);
    if (fd < 0) {
        record_destroy(out);
        return io("log open");
    }
    char tail[65];
    e = cp_fault("cache_tail_read") ? err_make(ERR_IO, "synthetic injected cache_tail_read")
                                    : reader_fingerprint(fd, key->size, tail);
#ifdef COLOPHON_TESTING
    const char *selected=getenv("COLOPHON_TEST_FAIL_PATH");
    if(selected && !strcmp(selected,key->path.p) && cp_fault("cache_selected"))e=err_make(ERR_IO,"Synthetic unreadable log during fingerprint read");
#endif
    close(fd);
    if (e.code) {
        record_destroy(out);
        return e;
    }
    if (memcmp(tail, out->reader.tail_sha256, 65)) {
        record_destroy(out);
        return ERR_SUCCESS;
    }
    *hit = true;
    return ERR_SUCCESS;
}
Err cache_put(Cache *c, LogRecord *record) {
    if (c->finished)
        return err_make(ERR_INVALID, "Parse cache is closed");
    return omap_put(&c->buffer, record->key.path, record);
}
static Err directory_identity(const char *path, struct stat *st, bool *present) {
    if (lstat(path, st)) {
        if (errno == ENOENT) {
            *present = false;
            return ERR_SUCCESS;
        }
        return io("directory stat");
    }
    if (!S_ISDIR(st->st_mode))
        return err_make(ERR_IO, "Cache path is not a directory");
    *present = true;
    return ERR_SUCCESS;
}
static bool identity(const char *path, const struct stat *expected) {
    struct stat st;
    return !lstat(path, &st) && S_ISDIR(st.st_mode) && st.st_dev == expected->st_dev &&
           st.st_ino == expected->st_ino;
}
static bool stopped(volatile sig_atomic_t *flag) {
    return flag && *flag;
}
Err cache_commit(Cache *c, const Omap *live, volatile sig_atomic_t *flag) {
    if (c->finished)
        return ERR_SUCCESS;
    Err e = ERR_SUCCESS;
    Omap names = {0};
    for (OmapEntry *entry = c->buffer.first; entry && !e.code; entry = entry->next) {
        if (stopped(flag)) {
            e = err_make(ERR_IO, "interrupted");
            break;
        }
        if (!omap_get(live, entry->key))
            continue;
        char name[69];
        cache_entry_name(entry->key, name);
        char *path = join(c->directory, name);
        unsigned char *data = NULL;
        size_t n = 0;
        if (!path) {
            e = err_make(ERR_NOMEM, "cache entry path allocation failed");
            break;
        }
        e = codec_encode(entry->value, &data, &n);
        if (!e.code)
            e = atomic_write(path, data, n);
        free(path);
        free(data);
        if (!e.code)
            e = omap_put(&names, (Str){name, 68}, c);
    }
    if (e.code)
        goto done;
    if (c->read_enabled)
        for (OmapEntry *entry = live->first; entry && !e.code; entry = entry->next) {
            char name[69];
            cache_entry_name(entry->key, name);
            e = omap_put(&names, (Str){name, 68}, c);
        }
    if (e.code)
        goto done;
    DIR *dir = opendir(c->directory);
    if (!dir) {
        e = io("prune open");
        goto done;
    }
    struct dirent *entry;
    while ((entry = readdir(dir))) {
        size_t n = strlen(entry->d_name);
        if (n < 4 || strcmp(entry->d_name + n - 4, ".rec") ||
            omap_get(&names, (Str){entry->d_name, (uint32_t)n}))
            continue;
        if (stopped(flag)) {
            e = err_make(ERR_IO, "interrupted");
            break;
        }
        char *path = join(c->directory, entry->d_name);
        if (!path) {
            e = err_make(ERR_NOMEM, "cache prune allocation failed");
            break;
        }
#ifdef COLOPHON_TESTING
        e=test_cache_prune_barrier();
        if(e.code){free(path);break;}
#endif
        if(cp_fault("cache_prune_unlink"))e=err_make(ERR_IO,"Synthetic stale cache deletion denied");
        else if (unlink(path) && errno != ENOENT)
            e = io("prune unlink");
        free(path);
        if (e.code)
            break;
    }
    closedir(dir);
    if (e.code)
        goto done;
    if (c->rebuild) {
        char name[80];
        snprintf(name, sizeof name, "cache-native.old-%d", getpid());
        char *old = join(c->home, name);
        if (!old) {
            e = err_make(ERR_NOMEM, "cache backup allocation failed");
            goto done;
        }
        struct stat prior, newer, st;
        bool had_prior = false, has_new = false;
        if (!lstat(old, &st) || errno != ENOENT) {
            e = err_make(ERR_IO, "Rebuild backup already exists");
            free(old);
            goto done;
        }
        e = directory_identity(c->installed, &prior, &had_prior);
        if (!e.code)
            e = directory_identity(c->directory, &newer, &has_new);
        if (!e.code && !has_new)
            e = err_make(ERR_IO, "Rebuild directory is missing");
        if (!e.code && stopped(flag))
            e = err_make(ERR_IO, "interrupted");
        if (!e.code && had_prior && rename(c->installed, old))
            e = io("backup rename");
#ifdef COLOPHON_TESTING
        if (!e.code && had_prior && cp_fault("cache_backup_replaced")) {
            e = test_cache_replace_backup(c->home, old);
            if (!e.code) {
                if (flag)
                    *flag = 1;
                e = err_make(ERR_IO, "interrupted");
            }
        }
#endif
        if (!e.code && had_prior && cp_fault("cache_backup_interrupt")) {
            if (flag)
                *flag = 1;
            e = err_make(ERR_IO, "interrupted");
        }
        if (!e.code && stopped(flag))
            e = err_make(ERR_IO, "interrupted");
        if (!e.code) {
            if (cp_fault("cache_install_rename"))
                e = err_make(ERR_IO, "synthetic injected cache_install_rename");
            else if (rename(c->directory, c->installed))
                e = io("install rename");
        }
        if (!e.code && cp_fault("cache_commit_interrupt")) {
            if (flag)
                *flag = 1;
            else
                e = err_make(ERR_IO, "interrupted");
        }
        if (has_new && identity(c->installed, &newer)) {
            c->committed = true;
            c->finished = true;
            omap_destroy(&c->buffer);
        } else if (had_prior && identity(old, &prior) && identity(c->directory, &newer) &&
                   lstat(c->installed, &st) && errno == ENOENT)
            (void)rename(old, c->installed);
        /* A real SIGINT changes only the flag. Recognize the completed install
         * first, then preserve its owned backup before garbage cleanup begins. */
        if (c->committed && !e.code && stopped(flag))
            e = err_make(ERR_IO, "interrupted");
        if (c->committed && had_prior && !e.code)
            (void)remove_tree(old);
        free(old);
    } else {
        if (stopped(flag)) {
            e = err_make(ERR_IO, "interrupted");
            goto done;
        }
        if (!c->read_enabled) {
            char *marker = join(c->directory, "FORMAT");
            if (!marker)
                e = err_make(ERR_NOMEM, "cache marker allocation failed");
            else {
                e = cp_fault("cache_format_write")
                        ? err_make(ERR_IO, "synthetic injected cache_format_write")
                        : atomic_write(marker, format, sizeof format - 1);
                free(marker);
            }
        }
        if (!e.code) {
            c->committed = true;
            c->finished = true;
            omap_destroy(&c->buffer);
        }
        if (!e.code && cp_fault("cache_commit_interrupt")) {
            if (flag)
                *flag = 1;
            e = err_make(ERR_IO, "interrupted");
        }
    }
done:
    omap_destroy(&names);
    return e;
}
Err cache_abort(Cache *c) {
    omap_destroy(&c->buffer);
    Err e = ERR_SUCCESS;
    if (c->rebuild && c->stage_owned && !c->finished && c->directory)
        e = cp_fault("cache_abort_cleanup")
                ? err_make(ERR_IO, "synthetic injected cache_abort_cleanup")
                : remove_tree(c->directory);
    if (e.code)
        c->abort_cleanup_error = e;
    c->finished = true;
    return e;
}
void cache_destroy(Cache *c) {
    (void)cache_abort(c);
    free(c->home);
    free(c->installed);
    free(c->directory);
    *c = (Cache){0};
}
