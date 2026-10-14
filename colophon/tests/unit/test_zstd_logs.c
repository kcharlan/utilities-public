#define _DARWIN_C_SOURCE
#include "runner.h"
#include "parse/reader.h"
#include "scan/logname.h"
#include "scan/discover.h"
#include "corpus/titles.h"
#include <sys/stat.h>
#include <fcntl.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static void touch(const char *root, const char *relative) {
    char path[1024];
    snprintf(path, sizeof path, "%s/%s", root, relative);
    for (char *p = path + strlen(root) + 1; *p; p++)
        if (*p == '/') { *p = 0; (void)mkdir(path, 0700); *p = '/'; }
    int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0600);
    ASSERT_TRUE(fd >= 0);
    ASSERT_EQ(0, close(fd));
}

TEST(discovery_accepts_zstd_logs_and_prefers_plain_sibling) {
    char root[1024];
    snprintf(root, sizeof root, "%s/synthetic-codex-XXXXXX", getenv("COLOPHON_HOME"));
    ASSERT_TRUE(mkdtemp(root));
    touch(root, "sessions/2026/01/02/rollout-pair.jsonl");
    touch(root, "sessions/2026/01/02/rollout-pair.jsonl.zst");
    touch(root, "sessions/2026/01/02/rollout-only.jsonl.zst");
    touch(root, "sessions/2026/01/02/rollout-upper.JSONL.ZST");
    touch(root, "sessions/2026/01/02/rollout-other.json.zst");
    touch(root, "archived_sessions/rollout-archived.jsonl.zst");
    Discovery d = {0};
    ASSERT_EQ(ERR_OK, discover_logs(root, &d).code);
    const char *expected[] = {"rollout-only.jsonl.zst", "rollout-pair.jsonl", "rollout-upper.JSONL.ZST", "rollout-archived.jsonl.zst"};
    ASSERT_EQ(4u, d.count);
    for (size_t i = 0; i < d.count; i++) {
        ASSERT_STREQ(expected[i], strrchr(d.logs[i].path.p, '/') + 1);
        ASSERT_EQ(i == 3, d.logs[i].archived);
    }
    discovery_destroy(&d);
}

TEST(title_stem_strips_whole_compressed_log_suffix) {
    Str plain = title_path_name(STR_LIT("/c/rollout-2026-01-02T12-00-00-00000000-0000-4000-8000-000000000001.jsonl"), true);
    Str zstd = title_path_name(STR_LIT("/c/rollout-2026-01-02T12-00-00-00000000-0000-4000-8000-000000000001.jsonl.zst"), true);
    ASSERT_TRUE(str_equal(plain, zstd));
    ASSERT_TRUE(str_equal(STR_LIT("archive.tar"), title_path_name(STR_LIT("/c/archive.tar.zst"), true)));
    ASSERT_TRUE(str_equal(STR_LIT("rollout-a.jsonl.zst"), title_path_name(STR_LIT("/c/rollout-a.jsonl.zst"), false)));
}

typedef struct { unsigned char *p; size_t n, cap; } Bytes;
static void put(Bytes *b, const void *p, size_t n) {
    if (b->n + n > b->cap) {
        b->cap = (b->n + n) * 2;
        b->p = realloc(b->p, b->cap);
        ASSERT_TRUE(b->p);
    }
    memcpy(b->p + b->n, p, n);
    b->n += n;
}
/* Synthetic Zstandard frame built from raw (stored) blocks, so no compressor
 * is needed. Narrow frames are single-segment with a 4-byte content size.
 * Wide frames carry window descriptor 0x90 (a 256 MiB window), which a
 * decoder at the default 128 MiB limit rejects. Verified with zstd 1.5.7. */
static void raw_frame(Bytes *b, const char *content, size_t n, bool wide) {
    const unsigned char magic[4] = {0x28, 0xB5, 0x2F, 0xFD};
    put(b, magic, 4);
    if (wide) {
        const unsigned char header[2] = {0x00, 0x90};
        put(b, header, 2);
    } else {
        const unsigned char header[5] = {0xA0, n & 255, (n >> 8) & 255, (n >> 16) & 255, (n >> 24) & 255};
        put(b, header, 5);
    }
    size_t offset = 0;
    do {
        size_t piece = n - offset > 131072 ? 131072 : n - offset;
        uint32_t block = (uint32_t)(offset + piece == n) | (uint32_t)(piece << 3);
        const unsigned char h[3] = {block & 255, (block >> 8) & 255, (block >> 16) & 255};
        put(b, h, 3);
        put(b, content + offset, piece);
        offset += piece;
    } while (offset < n);
}
typedef struct { size_t lines, chunks; bool last_terminated; } Seen;
static Err seen_line(void *context, const ReaderRawLine *line) {
    Seen *seen = context;
    seen->lines++;
    seen->last_terminated = line->terminated;
    return ERR_SUCCESS;
}
static Err seen_chunk(void *context) {
    ((Seen *)context)->chunks++;
    return ERR_SUCCESS;
}
static Err read_bytes(const char *suffix, const Bytes *b, Seen *seen, ReaderResult *result) {
    char path[1024];
    snprintf(path, sizeof path, "%s/synthetic-zstd-XXXXXX%s", getenv("COLOPHON_HOME"), suffix);
    int fd = mkstemps(path, (int)strlen(suffix));
    ASSERT_TRUE(fd >= 0);
    if (b->n) ASSERT_EQ((ssize_t)b->n, write(fd, b->p, b->n));
    ASSERT_EQ(0, close(fd));
    DiscoveredLog key = {.path = {path, (uint32_t)strlen(path)}, .size = (int64_t)b->n};
    ReaderCallbacks callbacks = {.context = seen, .chunk = seen_chunk, .raw_line = seen_line};
    Err e = reader_read_log(&key, &callbacks, result);
    ASSERT_EQ(0, unlink(path));
    return e;
}

TEST(log_name_format_classifies_plain_and_zstd_suffixes) {
    ASSERT_EQ(LOG_NAME_PLAIN, log_name_format(STR_LIT("/c/sessions/rollout-a.jsonl")));
    ASSERT_EQ(LOG_NAME_PLAIN, log_name_format(STR_LIT("rollout-a.JSONL")));
    ASSERT_EQ(LOG_NAME_ZSTD, log_name_format(STR_LIT("/c/archived_sessions/rollout-a.jsonl.zst")));
    ASSERT_EQ(LOG_NAME_ZSTD, log_name_format(STR_LIT("rollout-a.JSONL.ZST")));
    ASSERT_EQ(LOG_NAME_OTHER, log_name_format(STR_LIT("/c/.jsonl")));
    ASSERT_EQ(LOG_NAME_OTHER, log_name_format(STR_LIT("/c/.jsonl.zst")));
    ASSERT_EQ(LOG_NAME_OTHER, log_name_format(STR_LIT("rollout-a.json.zst")));
    ASSERT_EQ(LOG_NAME_OTHER, log_name_format(STR_LIT("rollout-a.zst")));
    ASSERT_EQ(LOG_NAME_OTHER, log_name_format(STR_LIT("rollout-a.jsonl.zst.bak")));
    ASSERT_EQ(LOG_NAME_OTHER, log_name_format(STR_LIT("/c/sessions.jsonl/notes.txt")));
}

TEST(zstd_reader_streams_lines_across_blocks_and_frames) {
    /* 3,000 synthetic 100-byte lines span three raw blocks; a second frame adds one more line. */
    char *content = malloc(300000);
    ASSERT_TRUE(content);
    for (size_t i = 0; i < 3000; i++) {
        memset(content + i * 100, 'x', 99);
        content[i * 100 + 99] = '\n';
    }
    Bytes b = {0};
    raw_frame(&b, content, 300000, false);
    raw_frame(&b, "{\"k\":2}\n", 8, false);
    Seen seen = {0};
    ReaderResult result = {0};
    ASSERT_EQ(ERR_OK, read_bytes(".jsonl.zst", &b, &seen, &result).code);
    ASSERT_EQ(3001u, seen.lines);
    ASSERT_EQ(3001u, result.physical_lines);
    ASSERT_TRUE(seen.last_terminated);
    ASSERT_FALSE(result.partial_final_line);
    ASSERT_TRUE(seen.chunks >= 1);
    reader_result_destroy(&result);
    free(content);
    free(b.p);
}

TEST(zstd_reader_accepts_declared_window_above_default_limit) {
    Bytes b = {0};
    raw_frame(&b, "{\"k\":1}\n", 8, true);
    Seen seen = {0};
    ReaderResult result = {0};
    ASSERT_EQ(ERR_OK, read_bytes(".jsonl.zst", &b, &seen, &result).code);
    ASSERT_EQ(1u, seen.lines);
    reader_result_destroy(&result);
    free(b.p);
}

TEST(zstd_reader_accepts_frame_ending_at_full_output_buffer) {
    /* Eight RLE blocks expand to exactly the reader's 1 MiB output buffer. */
    const unsigned char header[] = {0x28, 0xB5, 0x2F, 0xFD, 0xA0, 0, 0, 16, 0};
    Bytes b = {0};
    put(&b, header, sizeof header);
    for (size_t i = 0; i < 8; i++) {
        const unsigned char block[] = {i == 7 ? 3 : 2, 0, 16, 'x'};
        put(&b, block, sizeof block);
    }
    Seen seen = {0};
    ReaderResult result = {0};
    ASSERT_EQ(ERR_OK, read_bytes(".jsonl.zst", &b, &seen, &result).code);
    ASSERT_EQ(1u, seen.lines);
    ASSERT_TRUE(result.partial_final_line);
    reader_result_destroy(&result);
    free(b.p);
}

TEST(zstd_reader_reports_truncated_corrupt_and_trailing_bytes_as_io) {
    const char *suffix = ".jsonl.zst";
    Bytes valid = {0};
    raw_frame(&valid, "{\"k\":1}\n", 8, false);
    Bytes truncated = {valid.p, valid.n - 1, valid.cap};
    Bytes corrupt = {(unsigned char *)"not a zstd frame\n", 17, 0};
    Bytes trailing = {0};
    put(&trailing, valid.p, valid.n);
    put(&trailing, "junk", 4);
    const Bytes *cases[3] = {&truncated, &corrupt, &trailing};
    for (size_t i = 0; i < 3; i++) {
        Seen seen = {0};
        ReaderResult result = {0};
        ASSERT_EQ(ERR_IO, read_bytes(suffix, cases[i], &seen, &result).code);
        reader_result_destroy(&result);
    }
    free(valid.p);
    free(trailing.p);
}

TEST(zstd_reader_treats_zero_byte_file_as_empty_log) {
    Bytes empty = {0};
    Seen seen = {0};
    ReaderResult result = {0};
    ASSERT_EQ(ERR_OK, read_bytes(".jsonl.zst", &empty, &seen, &result).code);
    ASSERT_EQ(0u, seen.lines);
    ASSERT_EQ(0u, result.physical_lines);
    reader_result_destroy(&result);
}

TEST(zstd_reader_keeps_unterminated_final_line_partial) {
    Bytes b = {0};
    raw_frame(&b, "{\"k\":1}\n{\"k\":", 13, false);
    Seen seen = {0};
    ReaderResult result = {0};
    ASSERT_EQ(ERR_OK, read_bytes(".jsonl.zst", &b, &seen, &result).code);
    ASSERT_EQ(2u, seen.lines);
    ASSERT_FALSE(seen.last_terminated);
    ASSERT_TRUE(result.partial_final_line);
    reader_result_destroy(&result);
    free(b.p);
}
