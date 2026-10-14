#define _POSIX_C_SOURCE 200809L
#define _DARWIN_C_SOURCE
#include "runner.h"
#include "testing/hooks.h"
#include "util/arena.h"
#include "util/events.h"
#include "util/intern.h"
#include "util/omap.h"
#include "util/sha256.h"
#include "util/sort.h"
#include "util/str.h"
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <sys/resource.h>
#include <sys/wait.h>
#include <unistd.h>

TEST(strict_utf8_scalar_membership_preserves_site_independent_controls) {
    ASSERT_TRUE(str_utf8_scalar_valid(STR_LIT("")));
    ASSERT_TRUE(str_utf8_scalar_valid(STR_LIT("synthetic\0text")));
    ASSERT_TRUE(str_utf8_scalar_valid(STR_LIT("\xef\xbb\xbf")));
    ASSERT_TRUE(str_utf8_scalar_valid(STR_LIT("\xf0\x9f\x98\x80")));
    ASSERT_FALSE(str_utf8_scalar_valid(STR_LIT("\xff")));
    ASSERT_FALSE(str_utf8_scalar_valid(STR_LIT("\xe2\x82")));
    ASSERT_FALSE(str_utf8_scalar_valid(STR_LIT("\xed\xa0\x80")));
    ASSERT_FALSE(str_utf8_scalar_valid(STR_LIT("\xed\xa0\x80\xed\xb0\x80")));
}

TEST(arena_growth_alignment) {
    Arena a = {0};
    void *p, *q;
    ASSERT_EQ(ERR_OK, arena_alloc(&a, 65530, 16, &p).code);
    ASSERT_EQ(0, (uintptr_t)p % 16);
    memset(p, 42, 65530);
    ASSERT_EQ(ERR_OK, arena_alloc(&a, 80000, 64, &q).code);
    ASSERT_EQ(0, (uintptr_t)q % 64);
    ASSERT_EQ(42, ((unsigned char *)p)[65529]);
    ASSERT_EQ(ERR_NOMEM, arena_alloc(&a, SIZE_MAX, 16, &q).code);
    arena_destroy(&a);
}
static Intern table;
static void *intern_worker(void *unused) {
    (void)unused;
    for (int i = 0; i < 2000; i++) {
        Str s;
        if (intern_get(&table, STR_LIT("same\0é"), &s).code)
            abort();
        char key[32];
        int n = snprintf(key, sizeof(key), "synthetic-%d", i);
        if (intern_get(&table, (Str){key, (uint32_t)n}, &s).code)
            abort();
        if (s.n != (uint32_t)n || memcmp(s.p, key, (size_t)n))
            abort();
    }
    return NULL;
}
TEST(intern_concurrent_identity) {
    ASSERT_EQ(ERR_OK, intern_init(&table).code);
    pthread_t workers[4];
    for (int i = 0; i < 4; i++)
        ASSERT_EQ(0, pthread_create(&workers[i], NULL, intern_worker, NULL));
    for (int i = 0; i < 4; i++)
        ASSERT_EQ(0, pthread_join(workers[i], NULL));
    Str a, b, c;
    ASSERT_EQ(ERR_OK, intern_get(&table, STR_LIT("same\0é"), &a).code);
    ASSERT_EQ(ERR_OK, intern_get(&table, STR_LIT("same\0é"), &b).code);
    ASSERT_EQ(ERR_OK, intern_get(&table, STR_LIT("same"), &c).code);
    ASSERT_TRUE(a.p == b.p);
    ASSERT_TRUE(a.p != c.p);
    ASSERT_EQ(7, a.n);
    intern_destroy(&table);
}
TEST(ordered_map_deletion) {
    Omap m = {0};
    ASSERT_EQ(ERR_OK, omap_put(&m, STR_LIT("a"), (void *)1).code);
    ASSERT_EQ(ERR_OK, omap_put(&m, STR_LIT("b"), (void *)2).code);
    ASSERT_EQ(ERR_OK, omap_put(&m, STR_LIT("a"), (void *)3).code);
    ASSERT_STREQ("a", m.first->key.p);
    ASSERT_EQ((void *)3, omap_get(&m, STR_LIT("a")));
    OmapEntry *first = m.first;
    for (int i = 0; i < 100; i++)
        ASSERT_EQ((void *)2, omap_get(&m, STR_LIT("b")));
    ASSERT_TRUE(first == m.first);
    ASSERT_TRUE(omap_delete(&m, STR_LIT("a"), NULL));
    ASSERT_EQ(ERR_OK, omap_put(&m, STR_LIT("a"), (void *)4).code);
    ASSERT_STREQ("b", m.first->key.p);
    ASSERT_STREQ("a", m.last->key.p);
    ASSERT_TRUE(omap_delete_oldest(&m, NULL));
    ASSERT_STREQ("a", m.first->key.p);
    for (int i = 0; i < 500; i++) {
        char key[32];
        int n = snprintf(key, sizeof(key), "synthetic-%d", i);
        ASSERT_EQ(ERR_OK, omap_put(&m, (Str){key, (uint32_t)n}, (void *)5).code);
    }
    ASSERT_STREQ("a", m.first->key.p);
    ASSERT_EQ(501, m.size);
    for (int i = 0; i < 500; i++) {
        char key[32];
        int n = snprintf(key, sizeof(key), "synthetic-%d", i);
        ASSERT_EQ((void *)5, omap_get(&m, (Str){key, (uint32_t)n}));
    }
    omap_destroy(&m);
}
typedef struct {
    int key, order;
} Item;
static int compare_items(const void *a, const void *b, void *ctx) {
    (void)ctx;
    return ((const Item *)a)->key - ((const Item *)b)->key;
}
TEST(stable_sort_equal_keys) {
    Item items[] = {{2, 0}, {1, 1}, {2, 2}, {1, 3}, {2, 4}};
    ASSERT_EQ(ERR_OK, stable_sort(items, 5, sizeof(*items), compare_items, NULL).code);
    ASSERT_EQ(1, items[0].order);
    ASSERT_EQ(3, items[1].order);
    ASSERT_EQ(0, items[2].order);
    ASSERT_EQ(2, items[3].order);
    ASSERT_EQ(4, items[4].order);
}
TEST(sha256_vectors) {
    char hex[65];
    sha256_hex("", 0, hex);
    ASSERT_STREQ("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                 hex);
    sha256_hex("abc", 3, hex);
    ASSERT_STREQ("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
                 hex);
    char *million = malloc(1000000);
    ASSERT_TRUE(million);
    memset(million, 'a', 1000000);
    sha256_hex(million, 1000000, hex);
    free(million);
    ASSERT_STREQ("cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0",
                 hex);
}
TEST(sha256_extra_padding_and_streaming_vectors) {
    /* Fixed SHA-256 vectors for repeated ASCII a, independently checked with
     * macOS shasum -a 256; expected bytes never use this implementation. */
    static const char *expected[] = {
        "b35439a4ac6f0948b6d6f9e3c6af0f5f590ce20f1bde7090ef7970686ec6738a",
        "f13b2d724659eb3bf47f2dd6af1accc87b81f09f59f2b75e5c0bed6589dfe8c6",
        "d5c039b748aa64665782974ec3dc3025c042edf54dcdc2b5de31385b094cb678",
        "111bb261277afd65f0744b247cd3e47d386d71563d0ed995517807d5ebd4fba3",
        "11ee391211c6256460b6ed375957fadd8061cafbb31daf967db875aebd5aaad4",
        "35d5fc17cfbbadd00f5e710ada39f194c5ad7c766ad67072245f1fad45f0f530",
        "f506898cc7c2e092f9eb9fadae7ba50383f5b46a2a4fe5597dbb553a78981268",
        "7d3e74a05d7db15bce4ad9ec0658ea98e3f06eeecf16b4c6fff2da457ddc2f34",
        "c12cb024a2e5551cca0e08fce8f1c5e314555cc3fef6329ee994a3db752166ae"
    };
    char input[129];
    memset(input, 'a', sizeof input);
    for (size_t vector = 0; vector < 9; vector++) {
        size_t length = vector == 8 ? 129 : 56 + vector;
        unsigned char wanted[32], actual[32];
        for (size_t i = 0; i < 32; i++) {
            unsigned value;
            ASSERT_EQ(1, sscanf(expected[vector] + i * 2, "%2x", &value));
            wanted[i] = (unsigned char)value;
        }
        /* Each split exercises buffering, including 63+2 crossing the first
         * block and the second block with an existing partial block. */
        for (size_t split = 0; split <= length; split++) {
            Sha256 hash;
            sha256_init(&hash);
            sha256_update(&hash, input, split);
            sha256_update(&hash, input + split, length - split);
            sha256_final(&hash, actual);
            ASSERT_EQ(0, memcmp(wanted, actual, sizeof actual));
        }
    }
}
TEST(wtf8_and_nfc) {
    Arena a = {0};
    Str out;
    size_t count;
    ASSERT_EQ(ERR_OK, str_codepoints(STR_LIT("\xed\xa0\x80\xed\xb0\x80"), &count).code);
    ASSERT_EQ(2, count);
    ASSERT_EQ(ERR_INVALID, str_codepoints(STR_LIT("\xc0\x80"), &count).code);
    ASSERT_EQ(ERR_OK, str_nfc(&a, STR_LIT("e\xcc\x81"), "log:title", &out).code);
    ASSERT_TRUE(str_equal(out, STR_LIT("é")));
    ASSERT_EQ(ERR_OK, str_nfc(&a, STR_LIT("\xed\xa0\x80"), "log:title", &out).code);
    ASSERT_TRUE(str_equal(out, STR_LIT("\xed\xa0\x80")));
    ASSERT_TRUE(str_compare(STR_LIT("\0a"), STR_LIT("\0b")) < 0);
    ASSERT_TRUE(str_compare(STR_LIT("z"), STR_LIT("é")) < 0);
    ASSERT_EQ(ERR_OK, str_nfc(&a, STR_LIT(""), "log:title", &out).code);
    ASSERT_EQ(0, out.n);
    arena_destroy(&a);
    event_flush(NULL);
}
static void *event_worker(void *unused) {
    (void)unused;
    for (int i = 0; i < 1000; i++)
        event_note("tier2_int", "log:payload.tokens", 1);
    return NULL;
}
TEST(event_concurrent_order_and_privacy) {
    char home[] = "/tmp/colophon-events.XXXXXX";
    ASSERT_TRUE(mkdtemp(home));
    char path[512];
    snprintf(path, sizeof(path), "%s/native-events.jsonl", home);
    setenv("COLOPHON_TEST_WALL_MS", "123", 1);
    event_note("nfc_non_ascii", "pricing-cache.json:models", 1);
    pthread_t workers[4];
    for (int i = 0; i < 4; i++)
        ASSERT_EQ(0, pthread_create(&workers[i], NULL, event_worker, NULL));
    for (int i = 0; i < 4; i++)
        ASSERT_EQ(0, pthread_join(workers[i], NULL));
    event_flush(home);
    FILE *f = fopen(path, "r");
    ASSERT_TRUE(f);
    char line[512];
    ASSERT_TRUE(fgets(line, sizeof(line), f));
    ASSERT_STREQ("{\"ts\":123,\"event\":\"nfc_non_ascii\",\"site\":\"pricing-cache."
                 "json:models\",\"count\":1}\n",
                 line);
    ASSERT_TRUE(fgets(line, sizeof(line), f));
    ASSERT_STREQ("{\"ts\":123,\"event\":\"tier2_int\",\"site\":\"log:payload.tokens\","
                 "\"count\":4000}\n",
                 line);
    ASSERT_EQ(EOF, fgetc(f));
    fclose(f);
    struct stat before, after;
    ASSERT_EQ(0, stat(path, &before));
    event_flush(home);
    ASSERT_EQ(0, stat(path, &after));
    ASSERT_EQ(before.st_size, after.st_size);
    ASSERT_EQ(before.st_mtimespec.tv_sec, after.st_mtimespec.tv_sec);
    ASSERT_EQ(before.st_mtimespec.tv_nsec, after.st_mtimespec.tv_nsec);
    unsetenv("COLOPHON_TEST_WALL_MS");
    unlink(path);
    rmdir(home);
}
TEST(event_post_open_write_and_close_failure_drains_once) {
    /* Run before the lifecycle test's once-per-process warning. Fork isolates
     * the real file-size limit and SIGXFSZ disposition from the application. */
    for (int large = 0; large < 2; large++) {
        char home[] = "/tmp/colophon-event-failure.XXXXXX";
        ASSERT_TRUE(mkdtemp(home));
        char path[512];
        snprintf(path, sizeof path, "%s/native-events.jsonl", home);
        int errors[2];
        ASSERT_EQ(0, pipe(errors));
        pid_t child = fork();
        ASSERT_TRUE(child >= 0);
        if (child == 0) {
            close(errors[0]);
            if (dup2(errors[1], STDERR_FILENO) < 0) _exit(10);
            close(errors[1]);
            struct rlimit original, zero;
            if (getrlimit(RLIMIT_FSIZE, &original)) _exit(11);
            zero = original;
            zero.rlim_cur = 0;
            if (signal(SIGXFSZ, SIG_IGN) == SIG_ERR || setrlimit(RLIMIT_FSIZE, &zero)) _exit(12);
            char site[32769];
            memset(site, 'x', sizeof site - 1);
            site[sizeof site - 1] = 0;
            /* Short output fits stdio's buffer and fails during fclose;
             * long output forces fprintf to write after a successful open. */
            event_note("tier2_int", large ? site : "test.close", 1);
            event_flush(home);
            event_note("tier2_int", "test.second_failure", 1);
            event_flush(home);
            if (setrlimit(RLIMIT_FSIZE, &original)) _exit(13);
            event_flush(home); /* recovered filesystem receives no drained data */
            struct stat st;
            if (stat(path, &st) || st.st_size != 0 || (st.st_mode & 0777) != 0600) _exit(14);
            _exit(0); /* best-effort failure did not abort the process */
        }
        close(errors[1]);
        char warning[512];
        ssize_t bytes = read(errors[0], warning, sizeof warning - 1);
        ASSERT_TRUE(bytes > 0);
        warning[bytes] = 0;
        /* Drain to EOF before judging the exact once-only diagnostic. */
        ssize_t extra = read(errors[0], warning + bytes, sizeof warning - 1 - (size_t)bytes);
        ASSERT_EQ(0, extra);
        close(errors[0]);
        int child_status;
        ASSERT_EQ(child, waitpid(child, &child_status, 0));
        ASSERT_TRUE(WIFEXITED(child_status));
        ASSERT_EQ(0, WEXITSTATUS(child_status));
        ASSERT_TRUE(strstr(warning, "colophon: event log unavailable: ") == warning);
        char *newline = strchr(warning, '\n');
        ASSERT_TRUE(newline && newline[1] == 0);
        unlink(path);
        rmdir(home);
    }
}
TEST(event_log_lifecycle) {
    char home[] = "/tmp/colophon-events.XXXXXX";
    ASSERT_TRUE(mkdtemp(home));
    char path[512], old[512];
    snprintf(path, sizeof(path), "%s/native-events.jsonl", home);
    snprintf(old, sizeof(old), "%s.1", path);
    event_flush(home);
    ASSERT_EQ(-1, access(path, F_OK));
    ASSERT_EQ(0, setenv("COLOPHON_TEST_WALL_MS", "123", 1));
    event_note("tier2_int", "log:payload.tokens", 2);
    event_note("tier2_int", "log:payload.tokens", 3);
    event_flush(home);
    struct stat st;
    ASSERT_EQ(0, stat(path, &st));
    ASSERT_EQ(0600, st.st_mode & 0777);
    FILE *f = fopen(path, "r");
    ASSERT_TRUE(f);
    char line[512];
    ASSERT_TRUE(fgets(line, sizeof(line), f));
    ASSERT_EQ(EOF, fgetc(f));
    fclose(f);
    ASSERT_STREQ("{\"ts\":123,\"event\":\"tier2_int\",\"site\":\"log:payload.tokens\","
                 "\"count\":5}\n",
                 line);
    f = fopen(path, "a");
    ASSERT_TRUE(f);
    ASSERT_EQ(0, ftruncate(fileno(f), 1048576));
    fclose(f);
    event_note("tier2_int", "log:payload.tokens", 1);
    event_flush(home);
    ASSERT_EQ(-1, access(old, F_OK)); /* exactly 1 MiB does not roll */
    f = fopen(old, "w");
    ASSERT_TRUE(f);
    fputs("synthetic old rollover", f);
    fclose(f);
    event_note("tier2_int", "log:payload.tokens", 1);
    event_flush(home);
    ASSERT_EQ(0, stat(old, &st));
    ASSERT_TRUE(st.st_size > 1048576);
    FILE *errors = tmpfile();
    ASSERT_TRUE(errors);
    int saved = dup(STDERR_FILENO);
    ASSERT_TRUE(saved >= 0);
    ASSERT_TRUE(dup2(fileno(errors), STDERR_FILENO) >= 0);
    event_note("tier2_int", "log:payload.tokens", 1);
    event_flush("/this-synthetic-directory-does-not-exist");
    event_note("tier2_int", "log:payload.tokens", 1);
    event_flush("/this-synthetic-directory-does-not-exist");
    fflush(stderr);
    ASSERT_TRUE(dup2(saved, STDERR_FILENO) >= 0);
    close(saved);
    rewind(errors);
    ASSERT_TRUE(fgets(line, sizeof(line), errors));
    ASSERT_TRUE(strstr(line, "colophon: event log unavailable: ") == line);
    ASSERT_EQ(EOF, fgetc(errors));
    fclose(errors);
    event_flush(home); /* failure drains the run; subsequent flush adds nothing */
    unsetenv("COLOPHON_TEST_WALL_MS");
    unlink(path);
    unlink(old);
    rmdir(home);
}
TEST(clock_overrides_and_sequence_errors) {
    setenv("COLOPHON_TEST_NOW_MS", "-2", 1);
    setenv("COLOPHON_TEST_WALL_MS", "123", 1);
    ASSERT_EQ(-2, cp_now_ms());
    ASSERT_EQ(123, cp_wall_ms());
    setenv("COLOPHON_TEST_MONOTONIC", "1.25,2.5", 1);
    ASSERT_EQ(ERR_OK, cp_monotonic_start().code);
    double s;
    ASSERT_EQ(ERR_OK, cp_monotonic(&s).code);
    ASSERT_EQ(1.25, s);
    ASSERT_EQ(ERR_INVALID, cp_monotonic_finish().code);
    ASSERT_EQ(ERR_OK, cp_monotonic_start().code);
    ASSERT_EQ(ERR_OK, cp_monotonic(&s).code);
    ASSERT_EQ(ERR_OK, cp_monotonic(&s).code);
    ASSERT_EQ(2.5, s);
    ASSERT_EQ(ERR_INVALID, cp_monotonic(&s).code);
    ASSERT_EQ(ERR_OK, cp_monotonic_finish().code);
    setenv("COLOPHON_TEST_MONOTONIC", "1,", 1);
    ASSERT_EQ(ERR_OK, cp_monotonic_start().code);
    ASSERT_EQ(ERR_INVALID, cp_monotonic(&s).code);
    cp_monotonic_finish();
    unsetenv("COLOPHON_TEST_MONOTONIC");
    unsetenv("COLOPHON_TEST_NOW_MS");
    unsetenv("COLOPHON_TEST_WALL_MS");
}
TEST(event_rejects_content_paths) {
    char home[] = "/tmp/colophon-events.XXXXXX";
    ASSERT_TRUE(mkdtemp(home));
    char path[512];
    snprintf(path, sizeof(path), "%s/native-events.jsonl", home);
    event_note("tier2_int", "/synthetic-secret/path", 1);
    event_flush(home);
    ASSERT_EQ(-1, access(path, F_OK));
    rmdir(home);
}
TEST(nfc_shared_wrapper_events) {
    char home[] = "/tmp/colophon-events.XXXXXX";
    ASSERT_TRUE(mkdtemp(home));
    char path[512];
    snprintf(path, sizeof(path), "%s/native-events.jsonl", home);
    Arena a = {0};
    Str out;
    ASSERT_EQ(ERR_OK, str_nfc(&a, STR_LIT("ASCII"), "log:title", &out).code);
    event_flush(home);
    ASSERT_EQ(-1, access(path, F_OK));
    setenv("COLOPHON_TEST_WALL_MS", "123", 1);
    ASSERT_EQ(ERR_OK, str_nfc(&a, STR_LIT("e\xcc\x81"), "log:title", &out).code);
    event_flush(home);
    FILE *f = fopen(path, "r");
    ASSERT_TRUE(f);
    char line[512];
    ASSERT_TRUE(fgets(line, sizeof(line), f));
    ASSERT_STREQ(
        "{\"ts\":123,\"event\":\"nfc_non_ascii\",\"site\":\"log:title\",\"count\":1}\n",
        line);
    ASSERT_EQ(EOF, fgetc(f));
    fclose(f);
    unsetenv("COLOPHON_TEST_WALL_MS");
    arena_destroy(&a);
    unlink(path);
    rmdir(home);
}
