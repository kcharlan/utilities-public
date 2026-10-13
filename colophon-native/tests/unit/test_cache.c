#define _DARWIN_C_SOURCE
#include "cache/cache.h"
#include "parse/record.h"
#include "runner.h"
#include "scan/scan.h"
#include "util/fileio.h"
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>
typedef struct {
    char home[1024], path[1100], entry[1200], old[1100];
    Cache cache;
    Intern ids;
    LogRecord record;
    Omap live;
} CacheFixture;
static void fixture(CacheFixture *f) {
    memset(f, 0, sizeof *f);
    snprintf(f->home, sizeof f->home, "%s/synthetic-cache-XXXXXX", getenv("COLOPHON_HOME"));
    ASSERT_TRUE(mkdtemp(f->home));
    snprintf(f->path, sizeof f->path, "%s/synthetic.jsonl", f->home);
    FILE *file = fopen(f->path, "wb");
    ASSERT_TRUE(file);
    ASSERT_TRUE(fputs("{\"type\":\"synthetic\"}\n", file) >= 0);
    ASSERT_EQ(0, fclose(file));
    struct stat st;
    ASSERT_EQ(0, stat(f->path, &st));
    DiscoveredLog key = {.path = {f->path, (uint32_t)strlen(f->path)},
                         .size = st.st_size,
                         .mtime_ns =
                             (int64_t)st.st_mtimespec.tv_sec * 1000000000 + st.st_mtimespec.tv_nsec,
                         .stat_ok = true};
    ASSERT_EQ(ERR_OK, intern_init(&f->ids).code);
    ASSERT_EQ(ERR_OK, record_parse(&key, &f->ids, NULL, &f->record).code);
    ASSERT_EQ(ERR_OK, omap_put(&f->live, key.path, f).code);
    char name[69];
    cache_entry_name(f->record.key.path, name);
    snprintf(f->entry, sizeof f->entry, "%s/cache-native/%s", f->home, name);
    snprintf(f->old, sizeof f->old, "%s/cache-native.old-%d", f->home, getpid());
}
static void cleanup(CacheFixture *f) {
    cache_destroy(&f->cache);
    record_destroy(&f->record);
    omap_destroy(&f->live);
    intern_destroy(&f->ids);
}
static void populate(CacheFixture *f) {
    ASSERT_EQ(ERR_OK, cache_open(f->home, false, &f->cache).code);
    ASSERT_EQ(ERR_OK, cache_put(&f->cache, &f->record).code);
    ASSERT_EQ(ERR_OK, cache_commit(&f->cache, &f->live, NULL).code);
    cache_destroy(&f->cache);
}
TEST(cli_missing_marker_peer_reads_cannot_publish_or_trust_old_entries) {
    CacheFixture f;fixture(&f);populate(&f);
    char marker[1200];snprintf(marker,sizeof marker,"%s/cache-native/FORMAT",f.home);
    ASSERT_EQ(0,unlink(marker));Cache first={0},second={0};
    ASSERT_EQ(ERR_OK,cache_open(f.home,false,&first).code);ASSERT_TRUE(access(marker,F_OK));
    ASSERT_EQ(ERR_OK,cache_open(f.home,false,&second).code);ASSERT_TRUE(access(marker,F_OK));
    bool hit=true;LogRecord decoded={0};
    ASSERT_EQ(ERR_OK,cache_get(&second,&f.record.key,&f.ids,&decoded,&hit).code);ASSERT_FALSE(hit);
    ASSERT_TRUE(access(marker,F_OK));record_destroy(&decoded);
    ASSERT_EQ(ERR_OK,cache_abort(&second).code);ASSERT_EQ(ERR_OK,cache_abort(&first).code);
    cache_destroy(&second);cache_destroy(&first);ASSERT_TRUE(access(marker,F_OK));cleanup(&f);
}
TEST(cache_format_mismatch_preserves_nondirectory_root) {
    CacheFixture f;
    fixture(&f);
    char installed[1200];
    snprintf(installed, sizeof installed, "%s/cache-native", f.home);
    FILE *file = fopen(installed, "wb");
    ASSERT_TRUE(file);
    ASSERT_TRUE(fputs("synthetic foreign file", file) >= 0);
    ASSERT_EQ(0, fclose(file));
    Err e = cache_open(f.home, false, &f.cache);
    ASSERT_EQ(ERR_IO, e.code);
    char *bytes = NULL;
    size_t n = 0;
    ASSERT_EQ(ERR_OK, file_read_all(installed, &bytes, &n).code);
    ASSERT_EQ(22, n);
    ASSERT_TRUE(!memcmp(bytes, "synthetic foreign file", 22));
    free(bytes);
    cleanup(&f);
}
TEST(cache_buffer_abort_and_tail_io) {
    CacheFixture f;
    fixture(&f);
    ASSERT_EQ(ERR_OK, cache_open(f.home, false, &f.cache).code);
    ASSERT_EQ(ERR_OK, cache_put(&f.cache, &f.record).code);
    ASSERT_TRUE(access(f.entry, F_OK));
    ASSERT_EQ(ERR_OK, cache_abort(&f.cache).code);
    ASSERT_TRUE(f.cache.finished);
    ASSERT_TRUE(!f.cache.committed);
    ASSERT_EQ(0, f.cache.buffer.size);
    cache_destroy(&f.cache);
    populate(&f);
    ASSERT_EQ(ERR_OK, cache_open(f.home, false, &f.cache).code);
    LogRecord decoded = {0};
    bool hit = false;
    ASSERT_EQ(ERR_OK, cache_get(&f.cache, &f.record.key, &f.ids, &decoded, &hit).code);
    ASSERT_TRUE(hit);
    record_destroy(&decoded);
    ASSERT_EQ(0, unlink(f.path));
    ASSERT_EQ(0, mkdir(f.path, 0700));
    ASSERT_EQ(ERR_IO, cache_get(&f.cache, &f.record.key, &f.ids, &decoded, &hit).code);
    ASSERT_FALSE(hit);
    record_destroy(&decoded);
    cleanup(&f);
}
TEST(cache_rebuild_swap_ownership_and_restore) {
    for (int variant = 0; variant < 3; variant++) {
        CacheFixture f;
        fixture(&f);
        populate(&f);
        char *before = NULL;
        size_t n = 0;
        ASSERT_EQ(ERR_OK, file_read_all(f.entry, &before, &n).code);
        ASSERT_EQ(ERR_OK, cache_open(f.home, true, &f.cache).code);
        if (variant < 2)
            ASSERT_EQ(ERR_OK, cache_put(&f.cache, &f.record).code);
        if (variant == 0)
            ASSERT_EQ(0, mkdir(f.old, 0700));
        else if (variant == 1)
            ASSERT_EQ(0, symlink("synthetic-missing", f.old));
        else {
            char marker[1200];
            snprintf(marker, sizeof marker, "%s/FORMAT", f.cache.directory);
            ASSERT_EQ(0, unlink(marker));
            ASSERT_EQ(0, rmdir(f.cache.directory));
        }
        {
            ASSERT_EQ(ERR_IO, cache_commit(&f.cache, &f.live, NULL).code);
            ASSERT_FALSE(f.cache.committed);
            ASSERT_EQ(ERR_OK, cache_abort(&f.cache).code);
            char *after = NULL;
            size_t m = 0;
            ASSERT_EQ(ERR_OK, file_read_all(f.entry, &after, &m).code);
            ASSERT_EQ(n, m);
            ASSERT_TRUE(!memcmp(before, after, n));
            free(after);
        }
        free(before);
        cleanup(&f);
    }
}

TEST(cache_open_failure_closes_owned_stage) {
    for (int cleanup_failure = 0; cleanup_failure < 2; cleanup_failure++) {
        CacheFixture f;
        fixture(&f);
        populate(&f);
        ASSERT_EQ(0, setenv("COLOPHON_TEST_FAULT",
                            cleanup_failure ? "cache_format_write,cache_abort_cleanup"
                                            : "cache_format_write",
                            1));
        Err failure = cache_open(f.home, true, &f.cache);
        ASSERT_EQ(0, unsetenv("COLOPHON_TEST_FAULT"));
        ASSERT_EQ(ERR_IO, failure.code);
        ASSERT_STREQ("synthetic injected cache_format_write", failure.message);
        ASSERT_TRUE(f.cache.finished);
        ASSERT_EQ(0, f.cache.buffer.size);
        if (cleanup_failure) {
            ASSERT_EQ(ERR_IO, f.cache.abort_cleanup_error.code);
            ASSERT_EQ(0, access(f.cache.directory, F_OK));
        } else {
            ASSERT_EQ(ERR_OK, f.cache.abort_cleanup_error.code);
            ASSERT_TRUE(access(f.cache.directory, F_OK));
        }
        cleanup(&f);
    }
}

typedef struct {
    const char *path;
    uint64_t done, total;
    bool called;
} Growth;
static Err grow(uint64_t done, uint64_t total, void *context) {
    Growth *g = context;
    g->done = done;
    g->total = total;
    g->called = true;
    FILE *file = fopen(g->path, "ab");
    if (!file)
        return err_make(ERR_IO, "synthetic growth open failed");
    bool ok = fputs("{\"type\":\"synthetic\"}\n", file) >= 0;
    int result = fclose(file);
    return ok && !result ? ERR_SUCCESS : err_make(ERR_IO, "synthetic growth write failed");
}
TEST(scan_frozen_key_growth_and_processing_order) {
    CacheFixture f;
    fixture(&f);
    char sessions[1100], moved[1200];
    snprintf(sessions, sizeof sessions, "%s/sessions", f.home);
    ASSERT_EQ(0, mkdir(sessions, 0700));
    snprintf(moved, sizeof moved, "%s/synthetic.jsonl", sessions);
    ASSERT_EQ(0, rename(f.path, moved));
    ASSERT_EQ(ERR_OK, cache_open(f.home, false, &f.cache).code);
    ScanResult scan = {0};
    Growth g = {.path = moved};
    ASSERT_EQ(ERR_OK, scan_logs(f.home, &f.cache, NULL, grow, &g, &scan).code);
    ASSERT_TRUE(g.called);
    ASSERT_EQ((uint64_t)f.record.key.size, g.done);
    ASSERT_EQ(g.done, g.total);
    ASSERT_EQ(1, scan.parsed);
    ASSERT_EQ(0, scan.cached);
    ASSERT_EQ(f.record.key.size, scan.records[0]->key.size);
    ASSERT_EQ(1,
              *(uint64_t *)omap_get(&scan.records[0]->reader.unknown_types, STR_LIT("synthetic")));
    Err committed = cache_commit(&f.cache, &scan.live, NULL);
    if (committed.code)
        fprintf(stderr, "synthetic cache commit: %s\n", committed.message);
    ASSERT_EQ(ERR_OK, committed.code);
    cache_destroy(&f.cache);
    scan_destroy(&scan);
    ASSERT_EQ(ERR_OK, cache_open(f.home, false, &f.cache).code);
    ASSERT_EQ(ERR_OK, scan_logs(f.home, &f.cache, NULL, NULL, NULL, &scan).code);
    ASSERT_EQ(1, scan.parsed);
    ASSERT_EQ(2,
              *(uint64_t *)omap_get(&scan.records[0]->reader.unknown_types, STR_LIT("synthetic")));
    cache_destroy(&f.cache);
    scan_destroy(&scan);
    cleanup(&f);
}

static Err fail_progress(uint64_t done, uint64_t total, void *context) {
    (void)done;
    (void)total;
    (void)context;
    return err_make(ERR_INVALID, "synthetic primary scan failure");
}
TEST(scan_failure_aborts_cache_and_preserves_primary) {
    CacheFixture f;
    fixture(&f);
    char sessions[1100], moved[1200];
    snprintf(sessions, sizeof sessions, "%s/sessions", f.home);
    ASSERT_EQ(0, mkdir(sessions, 0700));
    snprintf(moved, sizeof moved, "%s/synthetic.jsonl", sessions);
    ASSERT_EQ(0, rename(f.path, moved));
    ASSERT_EQ(ERR_OK, cache_open(f.home, true, &f.cache).code);
    ScanResult scan = {0};
    ASSERT_EQ(0, setenv("COLOPHON_TEST_FAULT", "cache_abort_cleanup", 1));
    Err e = scan_logs(f.home, &f.cache, NULL, fail_progress, NULL, &scan);
    ASSERT_EQ(0, unsetenv("COLOPHON_TEST_FAULT"));
    ASSERT_EQ(ERR_INVALID, e.code);
    ASSERT_STREQ("synthetic primary scan failure", e.message);
    ASSERT_TRUE(f.cache.finished);
    ASSERT_EQ(0, f.cache.buffer.size);
    ASSERT_EQ(ERR_IO, f.cache.abort_cleanup_error.code);
    ASSERT_FALSE(f.cache.committed);
    ASSERT_EQ(0, access(f.cache.directory, F_OK));
    cache_destroy(&f.cache);
    scan_destroy(&scan);
    cleanup(&f);
}

TEST(cache_entry_write_failure_and_abort_cleanup_state) {
    CacheFixture f;
    fixture(&f);
    populate(&f);
    char *before = NULL;
    size_t n = 0;
    ASSERT_EQ(ERR_OK, file_read_all(f.entry, &before, &n).code);
    ASSERT_EQ(ERR_OK, cache_open(f.home, true, &f.cache).code);
    ASSERT_EQ(ERR_OK, cache_put(&f.cache, &f.record).code);
    char target[1300], name[69];
    cache_entry_name(f.record.key.path, name);
    snprintf(target, sizeof target, "%s/%s", f.cache.directory, name);
    ASSERT_EQ(0, mkdir(target, 0700));
    ASSERT_EQ(ERR_IO, cache_commit(&f.cache, &f.live, NULL).code);
    ASSERT_FALSE(f.cache.committed);
    ASSERT_EQ(0, setenv("COLOPHON_TEST_FAULT", "cache_abort_cleanup:1", 1));
    Err aborted = cache_abort(&f.cache);
    ASSERT_EQ(0, unsetenv("COLOPHON_TEST_FAULT"));
    ASSERT_EQ(ERR_IO, aborted.code);
    ASSERT_TRUE(f.cache.finished);
    ASSERT_EQ(0, f.cache.buffer.size);
    ASSERT_EQ(ERR_IO, f.cache.abort_cleanup_error.code);
    ASSERT_EQ(ERR_OK, cache_abort(&f.cache).code);
    ASSERT_EQ(ERR_IO, f.cache.abort_cleanup_error.code);
    char *after = NULL;
    size_t m = 0;
    ASSERT_EQ(ERR_OK, file_read_all(f.entry, &after, &m).code);
    ASSERT_EQ(n, m);
    ASSERT_TRUE(!memcmp(before, after, n));
    free(before);
    free(after);
    cleanup(&f);
}

TEST(cache_post_install_cleanup_failure_keeps_commit) {
    CacheFixture f;
    fixture(&f);
    populate(&f);
    ASSERT_EQ(ERR_OK, cache_open(f.home, true, &f.cache).code);
    ASSERT_EQ(ERR_OK, cache_put(&f.cache, &f.record).code);
    ASSERT_EQ(0, chmod(f.cache.installed, 0500));
    Err e = cache_commit(&f.cache, &f.live, NULL);
    ASSERT_EQ(0, chmod(f.old, 0700));
    ASSERT_EQ(ERR_OK, e.code);
    ASSERT_TRUE(f.cache.committed && f.cache.finished);
    ASSERT_EQ(0, f.cache.buffer.size);
    ASSERT_EQ(0, access(f.entry, F_OK));
    ASSERT_EQ(0, access(f.old, F_OK));
    ASSERT_EQ(ERR_OK, cache_abort(&f.cache).code);
    ASSERT_TRUE(f.cache.committed);
    cleanup(&f);
}

TEST(cache_post_install_flag_only_preserves_owned_backup) {
    CacheFixture f;
    fixture(&f);
    populate(&f);
    char *before = NULL;
    size_t n = 0;
    ASSERT_EQ(ERR_OK, file_read_all(f.entry, &before, &n).code);
    ASSERT_EQ(ERR_OK, cache_open(f.home, true, &f.cache).code);
    f.record.reader.physical_lines++;
    ASSERT_EQ(ERR_OK, cache_put(&f.cache, &f.record).code);
    volatile sig_atomic_t flag = 0;
    ASSERT_EQ(0, setenv("COLOPHON_TEST_FAULT", "cache_commit_interrupt:1", 1));
    Err e = cache_commit(&f.cache, &f.live, &flag);
    ASSERT_EQ(0, unsetenv("COLOPHON_TEST_FAULT"));
    ASSERT_EQ(ERR_IO, e.code);
    ASSERT_STREQ("interrupted", e.message);
    ASSERT_EQ(1, flag);
    ASSERT_TRUE(f.cache.committed && f.cache.finished);
    ASSERT_EQ(0, f.cache.buffer.size);
    ASSERT_TRUE(access(f.cache.directory, F_OK));
    char name[69], old_entry[1200];
    cache_entry_name(f.record.key.path, name);
    snprintf(old_entry, sizeof old_entry, "%s/%s", f.old, name);
    char *old = NULL, *installed = NULL;
    size_t a = 0, b = 0;
    ASSERT_EQ(ERR_OK, file_read_all(old_entry, &old, &a).code);
    ASSERT_EQ(ERR_OK, file_read_all(f.entry, &installed, &b).code);
    ASSERT_EQ(n, a);
    ASSERT_TRUE(!memcmp(before, old, n));
    ASSERT_EQ(n, b);
    ASSERT_TRUE(memcmp(before, installed, n));
    ASSERT_EQ(ERR_OK, cache_abort(&f.cache).code);
    ASSERT_EQ(0, access(old_entry, F_OK));
    ASSERT_EQ(0, access(f.entry, F_OK));
    free(before);
    free(old);
    free(installed);
    cleanup(&f);
}

TEST(scan_processing_order_uses_frozen_milliseconds_size_path) {
    CacheFixture f;
    fixture(&f);
    char sessions[1100];
    snprintf(sessions, sizeof sessions, "%s/sessions", f.home);
    ASSERT_EQ(0, mkdir(sessions, 0700));
    const char *names[] = {"b.jsonl", "a.jsonl", "c.jsonl"};
    char paths[3][1200];
    for (int i = 0; i < 3; i++) {
        snprintf(paths[i], sizeof paths[i], "%s/%s", sessions, names[i]);
        FILE *file = fopen(paths[i], "wb");
        ASSERT_TRUE(file);
        ASSERT_TRUE(fputs(i == 2 ? "{}\n" : "{\"type\":\"synthetic\"}\n", file) >= 0);
        ASSERT_EQ(0, fclose(file));
        struct timespec times[2] = {{100, 1000000}, {100, 1000000 + i * 100}};
        ASSERT_EQ(0, utimensat(AT_FDCWD, paths[i], times, 0));
    }
    ASSERT_EQ(ERR_OK, cache_open(f.home, false, &f.cache).code);
    ScanResult scan = {0};
    ASSERT_EQ(ERR_OK, scan_logs(f.home, &f.cache, NULL, NULL, NULL, &scan).code);
    ASSERT_EQ(3, scan.count);
    ASSERT_TRUE(str_equal(scan.records[0]->key.path, (Str){paths[2], (uint32_t)strlen(paths[2])}));
    ASSERT_TRUE(str_equal(scan.records[1]->key.path, (Str){paths[1], (uint32_t)strlen(paths[1])}));
    ASSERT_TRUE(str_equal(scan.records[2]->key.path, (Str){paths[0], (uint32_t)strlen(paths[0])}));
    cache_destroy(&f.cache);
    scan_destroy(&scan);
    cleanup(&f);
}
