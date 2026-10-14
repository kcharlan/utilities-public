/* macOS allocated-byte walker. Protocol fields are bytes terminated by NUL. */
#include <sys/attr.h>
#include <sys/stat.h>
#include <sys/vnode.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define SMW_VERSION "1.0.0"
#define SMW_PROTOCOL 1
#define BULK_SIZE (256 * 1024)
#define FLUSH_SIZE (64 * 1024)

struct job { char *path; uint64_t own; bool root; struct job *next; };
struct buffer { char *data; size_t used, capacity; };
struct worker { struct buffer output; char *bulk; };
static struct {
    dev_t device;
    uint64_t threshold, progress;
    const char **excluded;
    size_t exclude_count;
    uint64_t *registered;
    size_t registered_count;
    bool stat_mode;
    struct job *jobs;
    uint64_t pending, dirs, files, errors;
    pthread_mutex_t queue_lock, output_lock;
    pthread_cond_t ready;
} state = { .queue_lock = PTHREAD_MUTEX_INITIALIZER,
            .output_lock = PTHREAD_MUTEX_INITIALIZER,
            .ready = PTHREAD_COND_INITIALIZER };

static void fatal(const char *message) {
    fprintf(stderr, "storage_monitor_walk: %s\n", message);
    exit(1);
}
static void *allocate(size_t size) {
    void *p = malloc(size);
    if (!p) fatal("allocation failed");
    return p;
}
static void flush(struct buffer *b) {
    if (!b->used) return;
    pthread_mutex_lock(&state.output_lock);
    if (fwrite(b->data, 1, b->used, stdout) != b->used) fatal("write failed");
    pthread_mutex_unlock(&state.output_lock);
    b->used = 0;
}
/* Reserve the entire record before appending: flushes never split a record. */
static void record(struct buffer *b, size_t count, ...) {
    va_list args;
    size_t length = 0;
    va_start(args, count);
    for (size_t i = 0; i < count; i++) {
        const char *field = va_arg(args, const char *);
        size_t n = strlen(field) + 1;
        if (n > SIZE_MAX - length) fatal("record too large");
        length += n;
    }
    va_end(args);
    if (length > SIZE_MAX - b->used) fatal("output too large");
    if (b->used + length > b->capacity) {
        size_t capacity = b->used + length;
        if (capacity < FLUSH_SIZE * 2) capacity = FLUSH_SIZE * 2;
        char *p = realloc(b->data, capacity);
        if (!p) fatal("allocation failed");
        b->data = p;
        b->capacity = capacity;
    }
    va_start(args, count);
    for (size_t i = 0; i < count; i++) {
        const char *field = va_arg(args, const char *);
        size_t n = strlen(field) + 1;
        memcpy(b->data + b->used, field, n);
        b->used += n;
    }
    va_end(args);
    if (b->used > FLUSH_SIZE) flush(b);
}
static void number(char out[32], uint64_t value) {
    snprintf(out, 32, "%" PRIu64, value);
}
static int compare_inode(const void *a, const void *b) {
    uint64_t x = *(const uint64_t *)a, y = *(const uint64_t *)b;
    return (x > y) - (x < y);
}
static bool registered(uint64_t ino) {
    return state.registered_count && bsearch(&ino, state.registered,
        state.registered_count, sizeof ino, compare_inode) != NULL;
}
static char *join_path(const char *parent, const char *name) {
    size_t p = strlen(parent), n = strlen(name);
    bool slash = p != 1 || parent[0] != '/';
    if (p > SIZE_MAX - n - 2) fatal("path too large");
    char *result = allocate(p + n + 2);
    memcpy(result, parent, p);
    if (slash) result[p++] = '/';
    memcpy(result + p, name, n + 1);
    return result;
}
static void enqueue(char *path, uint64_t own, bool root) {
    struct job *job = allocate(sizeof *job);
    *job = (struct job){path, own, root, NULL};
    pthread_mutex_lock(&state.queue_lock);
    job->next = state.jobs;
    state.jobs = job;
    state.pending++;
    pthread_cond_signal(&state.ready);
    pthread_mutex_unlock(&state.queue_lock);
}
struct totals { uint64_t local, files, errors; };
static void entry(struct worker *w, const char *parent, const char *name,
                  dev_t device, uint64_t ino, uint64_t links, uint64_t allocated,
                  uint64_t size, bool directory, struct totals *totals) {
    if (device != state.device) return;
    if (directory) {
        char *path = join_path(parent, name);
        for (size_t i = 0; i < state.exclude_count; i++) {
            if (!strcmp(path, state.excluded[i])) { free(path); return; }
        }
        enqueue(path, allocated, false);
        return;
    }
    totals->files++;
    char dev[32], inode[32], nlink[32], alloc[32], apparent[32];
    number(alloc, allocated);
    if (links > 1 || registered(ino)) {
        number(dev, (uint64_t)device); number(inode, ino); number(nlink, links);
        record(&w->output, 7, "H", dev, inode, nlink, alloc, parent, name);
    } else {
        totals->local += allocated;
    }
    if (size >= state.threshold) {
        number(apparent, size);
        record(&w->output, 5, "L", apparent, alloc, parent, name);
    }
}
static void stat_entry(struct worker *w, int fd, const char *parent,
                       const char *name, struct totals *totals) {
    struct stat st;
    if (fstatat(fd, name, &st, AT_SYMLINK_NOFOLLOW)) { totals->errors++; return; }
    entry(w, parent, name, st.st_dev, st.st_ino, st.st_nlink,
          (uint64_t)st.st_blocks * 512, (uint64_t)st.st_size, S_ISDIR(st.st_mode), totals);
}
static void stat_directory(struct worker *w, int fd, const char *path, struct totals *totals) {
    /* dup shares the offset, including after a rejected first bulk call. */
    int copy = dup(fd);
    if (copy < 0) { totals->errors++; return; }
    DIR *dir = fdopendir(copy);
    if (!dir) { close(copy); totals->errors++; return; }
    for (;;) {
        errno = 0;
        struct dirent *item = readdir(dir);
        if (!item) { if (errno) totals->errors++; break; }
        if (!strcmp(item->d_name, ".") || !strcmp(item->d_name, "..")) continue;
        stat_entry(w, fd, path, item->d_name, totals);
    }
    closedir(dir);
}
/* Kernel attributes have only four-byte alignment. Never dereference them. */
static bool take(const char **p, const char *end, void *out, size_t n) {
    if ((size_t)(end - *p) < n) return false;
    memcpy(out, *p, n); *p += n;
    return true;
}
static bool bulk_entry(struct worker *w, int fd, const char *parent,
                       const char *start, size_t length, struct totals *totals) {
    const char *p = start + 4, *end = start + length;
    attribute_set_t ret;
    uint32_t error = 0;
    attrreference_t ref;
    const char *name = NULL;
    dev_t device = 0;
    fsobj_type_t type = 0;
    uint64_t ino = 0;
    uint32_t links = 1;
    off_t allocated = 0, size = 0;
    if (!take(&p, end, &ret, sizeof ret)) return false;
    /* ATTR_CMN_ERROR precedes NAME, despite its numerical bit position. */
    if ((ret.commonattr & ATTR_CMN_ERROR) && !take(&p, end, &error, 4)) return false;
    if (error) { totals->errors++; return true; }
    if (ret.commonattr & ATTR_CMN_NAME) {
        const char *reference = p;
        if (!take(&p, end, &ref, sizeof ref)) return false;
        /* Validate offsets before forming a pointer outside the record. */
        int64_t offset = (int64_t)(reference - start) + ref.attr_dataoffset;
        if (offset < 0 || (uint64_t)offset >= length || !ref.attr_length ||
            ref.attr_length > length - (size_t)offset) return false;
        name = start + offset;
        if (!memchr(name, 0, ref.attr_length)) return false;
    }
    if ((ret.commonattr & ATTR_CMN_DEVID) && !take(&p, end, &device, sizeof device)) return false;
    if ((ret.commonattr & ATTR_CMN_OBJTYPE) && !take(&p, end, &type, sizeof type)) return false;
    if ((ret.commonattr & ATTR_CMN_FILEID) && !take(&p, end, &ino, 8)) return false;
    if ((ret.fileattr & ATTR_FILE_LINKCOUNT) && !take(&p, end, &links, 4)) return false;
    if ((ret.fileattr & ATTR_FILE_ALLOCSIZE) && !take(&p, end, &allocated, 8)) return false;
    if ((ret.fileattr & ATTR_FILE_DATALENGTH) && !take(&p, end, &size, 8)) return false;
    if (!name) { totals->errors++; return true; }
    if (!strcmp(name, ".") || !strcmp(name, "..")) return true;
    attrgroup_t common = ATTR_CMN_NAME | ATTR_CMN_DEVID | ATTR_CMN_OBJTYPE | ATTR_CMN_FILEID;
    attrgroup_t file = ATTR_FILE_LINKCOUNT | ATTR_FILE_ALLOCSIZE | ATTR_FILE_DATALENGTH;
    /* Directories need st_blocks for the failed-open D record. Opened ones are
       measured again via fstat, which also rechecks the mount boundary. */
    if ((ret.commonattr & common) != common || type == VDIR || (ret.fileattr & file) != file) {
        stat_entry(w, fd, parent, name, totals);
    } else {
        entry(w, parent, name, device, ino, links, (uint64_t)allocated,
              (uint64_t)size, false, totals);
    }
    return true;
}
static void bulk_directory(struct worker *w, int fd, const char *path, struct totals *totals) {
    struct attrlist attributes = { .bitmapcount = ATTR_BIT_MAP_COUNT,
        .commonattr = ATTR_CMN_RETURNED_ATTRS | ATTR_CMN_NAME | ATTR_CMN_DEVID |
                      ATTR_CMN_OBJTYPE | ATTR_CMN_FILEID | ATTR_CMN_ERROR,
        .fileattr = ATTR_FILE_LINKCOUNT | ATTR_FILE_ALLOCSIZE | ATTR_FILE_DATALENGTH };
    bool first = true;
    for (;;) {
        int count = getattrlistbulk(fd, &attributes, w->bulk, BULK_SIZE, 0);
        if (count < 0) {
            if (first && (errno == ENOTSUP || errno == EINVAL)) {
                /* An unsupported bulk operation must not consume entries. */
                if (lseek(fd, 0, SEEK_SET) < 0) { totals->errors++; return; }
                stat_directory(w, fd, path, totals);
            } else totals->errors++;
            return;
        }
        if (!count) return;
        first = false;
        size_t offset = 0;
        for (int i = 0; i < count; i++) {
            uint32_t length;
            if (offset > BULK_SIZE - 4) { totals->errors++; return; }
            memcpy(&length, w->bulk + offset, 4);
            if (length < 4 || length > BULK_SIZE - offset ||
                !bulk_entry(w, fd, path, w->bulk + offset, length, totals)) {
                totals->errors++; return;
            }
            offset += length;
        }
    }
}
static bool scan(struct worker *w, struct job *job, struct totals *totals) {
    totals->local = job->own;
    int flags = O_RDONLY | O_DIRECTORY | O_CLOEXEC;
    if (!job->root) flags |= O_NOFOLLOW;
    int fd = open(job->path, flags);
    if (fd < 0) { totals->errors++; return true; }
    if (!job->root) {
        struct stat st;
        if (fstat(fd, &st)) { close(fd); totals->errors++; return true; }
        if (st.st_dev != state.device) { close(fd); return false; }
        totals->local = (uint64_t)st.st_blocks * 512;
    }
    if (state.stat_mode) stat_directory(w, fd, job->path, totals);
    else bulk_directory(w, fd, job->path, totals);
    close(fd);
    return true;
}
static void *worker_main(void *unused) {
    (void)unused;
    struct worker worker = { .bulk = allocate(BULK_SIZE) };
    for (;;) {
        pthread_mutex_lock(&state.queue_lock);
        while (!state.jobs && state.pending) pthread_cond_wait(&state.ready, &state.queue_lock);
        struct job *job = state.jobs;
        if (!job) { pthread_mutex_unlock(&state.queue_lock); break; }
        state.jobs = job->next;
        pthread_mutex_unlock(&state.queue_lock);
        struct totals totals = {0};
        bool counted = scan(&worker, job, &totals);
        if (counted) {
            char bytes[32]; number(bytes, totals.local);
            record(&worker.output, 3, "D", job->path, bytes);
        }
        free(job->path); free(job);
        pthread_mutex_lock(&state.queue_lock);
        if (counted) {
            state.dirs++; state.files += totals.files; state.errors += totals.errors;
            if (state.dirs % state.progress == 0) {
                char completed[32]; number(completed, state.dirs);
                pthread_mutex_lock(&state.output_lock);
                if (fwrite("P", 1, 2, stdout) != 2 ||
                    fwrite(completed, 1, strlen(completed) + 1, stdout) != strlen(completed) + 1)
                    fatal("write failed");
                pthread_mutex_unlock(&state.output_lock);
            }
        }
        state.pending--;
        if (!state.pending) pthread_cond_broadcast(&state.ready);
        pthread_mutex_unlock(&state.queue_lock);
    }
    flush(&worker.output);
    free(worker.output.data); free(worker.bulk);
    return NULL;
}
static void usage(void) {
    fprintf(stderr, "usage: storage_monitor_walk --version | walk --root PATH --workers N --large-file-bytes B --progress-every K [--exclude PATH] [--registered-inodes-stdin] [--stat-mode]\n");
    exit(2);
}
static uint64_t decimal(const char *s) {
    if (!*s) usage();
    for (const char *p = s; *p; p++) if (*p < '0' || *p > '9') usage();
    errno = 0; char *end;
    uint64_t value = strtoull(s, &end, 10);
    if (errno || *end) usage();
    return value;
}
int main(int argc, char **argv) {
    if (argc == 2 && !strcmp(argv[1], "--version")) {
        printf("storage_monitor_walk %s protocol %d\n", SMW_VERSION, SMW_PROTOCOL);
        return fflush(stdout) ? 1 : 0;
    }
    if (argc < 2 || strcmp(argv[1], "walk")) usage();
    const char *root = NULL;
    uint64_t workers = 0;
    bool have_threshold = false, read_inodes = false;
    state.excluded = allocate((size_t)argc * sizeof *state.excluded);
    for (int i = 2; i < argc; i++) {
        const char *arg = argv[i];
        if (!strcmp(arg, "--stat-mode")) { state.stat_mode = true; continue; }
        if (!strcmp(arg, "--registered-inodes-stdin")) { read_inodes = true; continue; }
        if (++i >= argc) usage();
        if (!strcmp(arg, "--root")) root = argv[i];
        else if (!strcmp(arg, "--workers")) workers = decimal(argv[i]);
        else if (!strcmp(arg, "--large-file-bytes")) { state.threshold = decimal(argv[i]); have_threshold = true; }
        else if (!strcmp(arg, "--progress-every")) state.progress = decimal(argv[i]);
        else if (!strcmp(arg, "--exclude")) state.excluded[state.exclude_count++] = argv[i];
        else usage();
    }
    if (!root || !workers || workers > 16 || !have_threshold || !state.progress) usage();
    if (read_inodes) {
        char *line = NULL; size_t capacity = 0; ssize_t n;
        size_t allocated = 0;
        while ((n = getline(&line, &capacity, stdin)) >= 0) {
            if (n && line[n - 1] == '\n') line[--n] = 0;
            if ((size_t)n != strlen(line)) usage();
            uint64_t ino = decimal(line);
            if (state.registered_count == allocated) {
                allocated = allocated ? allocated * 2 : 256;
                if (allocated > SIZE_MAX / sizeof ino) fatal("too many registered inodes");
                void *p = realloc(state.registered, allocated * sizeof ino);
                if (!p) fatal("allocation failed");
                state.registered = p;
            }
            state.registered[state.registered_count++] = ino;
        }
        free(line);
        if (ferror(stdin)) fatal("stdin read failed");
        if (state.registered_count) qsort(state.registered, state.registered_count, sizeof(uint64_t), compare_inode);
    }
    struct stat st;
    if (lstat(root, &st)) {
        fprintf(stderr, "errno=%d\n", errno);
        free(state.registered); free(state.excluded);
        return 3;
    }
    state.device = st.st_dev;
    struct timespec start, end;
    clock_gettime(CLOCK_MONOTONIC, &start);
    char *root_copy = strdup(root);
    if (!root_copy) fatal("allocation failed");
    enqueue(root_copy, (uint64_t)st.st_blocks * 512, true);
    pthread_t threads[16];
    for (size_t i = 0; i < workers; i++) if (pthread_create(&threads[i], NULL, worker_main, NULL)) fatal("thread creation failed");
    for (size_t i = 0; i < workers; i++) if (pthread_join(threads[i], NULL)) fatal("thread join failed");
    clock_gettime(CLOCK_MONOTONIC, &end);
    uint64_t duration = (uint64_t)((end.tv_sec - start.tv_sec) * 1000 + (end.tv_nsec - start.tv_nsec) / 1000000);
    struct buffer output = {0};
    char dirs[32], files[32], errors[32], milliseconds[32];
    number(dirs, state.dirs); number(files, state.files); number(errors, state.errors); number(milliseconds, duration);
    record(&output, 5, "S", dirs, files, errors, milliseconds);
    flush(&output);
    int status = fflush(stdout) ? 1 : 0;
    free(output.data); free(state.registered); free(state.excluded);
    return status;
}
