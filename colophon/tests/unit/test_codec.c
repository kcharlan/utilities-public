#include "cache/codec.h"
#include "parse/record.h"
#include "runner.h"
#include "util/sha256.h"
#include <math.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <unistd.h>

TEST(codec_round_trips_thread_priority_observation) {
    Intern ids = {0};
    ASSERT_EQ(ERR_OK, intern_init(&ids).code);
    TokenObservation observation = {.tag = TOKEN_P, .line = 2, .priority = true};
    LogRecord raw = {.key = {.path = STR_LIT("/synthetic/priority-cache")},
                     .token_stream = {.observations = &observation, .count = 1}};
    unsigned char *bytes = NULL;
    size_t length = 0;
    ASSERT_EQ(ERR_OK, codec_encode(&raw, &bytes, &length).code);
    LogRecord decoded = {0};
    ASSERT_EQ(ERR_OK, codec_decode(bytes, length, &raw.key, raw.reader.tail_sha256, &ids, &decoded).code);
    ASSERT_EQ(1, decoded.token_stream.count);
    ASSERT_EQ(TOKEN_P, decoded.token_stream.observations[0].tag);
    ASSERT_TRUE(decoded.token_stream.observations[0].priority);
    free(bytes);
    record_destroy(&decoded);
    intern_destroy(&ids);
}

TEST(codec_encode_failure_returns_no_partial_wire) {
    LogRecord record = {.key = {.path = STR_LIT("/synthetic/invalid")},
                        .meta = {.cwd = {.kind = (JKind)255}}};
    unsigned char *bytes = (unsigned char *)1;
    size_t length = SIZE_MAX;
    ASSERT_EQ(ERR_INVALID, codec_encode(&record, &bytes, &length).code);
    ASSERT_TRUE(bytes == NULL);
    ASSERT_EQ(0, length);
    record.meta.cwd = (JScalar){.kind = JS_STRING};
    ASSERT_EQ(ERR_INVALID, codec_encode(&record, &bytes, &length).code);
    ASSERT_TRUE(bytes == NULL);
    ASSERT_EQ(0, length);
}

TEST(codec_encoder_accepts_readonly_records) {
    pid_t child = fork();
    ASSERT_TRUE(child >= 0);
    if (!child) {
        LogRecord *record =
            mmap(NULL, sizeof *record, PROT_READ | PROT_WRITE, MAP_ANON | MAP_PRIVATE, -1, 0);
        if (record == MAP_FAILED)
            _exit(2);
        *record = (LogRecord){.key = {.path = STR_LIT("/synthetic/readonly")}};
        if (mprotect(record, sizeof *record, PROT_READ))
            _exit(3);
        unsigned char *bytes = NULL;
        size_t length = 0;
        Err e = codec_encode(record, &bytes, &length);
        free(bytes);
        _exit(e.code ? 4 : 0);
    }
    int status = 0;
    ASSERT_EQ(child, waitpid(child, &status, 0));
    ASSERT_TRUE(WIFEXITED(status) && WEXITSTATUS(status) == 0);
}

/* Independent bitwise test checksum lets malformed bodies reach the decoder's
 * bounds/ownership checks instead of failing only at the checksum gate. */
static void checksum(unsigned char *p, size_t n) {
    uint32_t crc = UINT32_MAX;
    for (size_t i = 12; i < n - 4; i++) {
        crc ^= p[i];
        for (int j = 0; j < 8; j++)
            crc = (crc >> 1) ^ ((crc & 1) ? 0xedb88320u : 0);
    }
    crc = ~crc;
    for (int j = 0; j < 4; j++)
        p[n - 4 + j] = (unsigned char)(crc >> (8 * j));
}

TEST(codec_roundtrip_and_corrupt_bounds) {
    Intern ids;
    ASSERT_EQ(ERR_OK, intern_init(&ids).code);
    LogRecord input = {
        .identifiers = &ids,
        .key = {.path = STR_LIT("/synthetic/log"), .size = 17, .mtime_ns = -123, .stat_ok = true},
        .status = STR_LIT("ok"),
        .has_meta = true};
    sha256_hex("synthetic", 9, input.reader.tail_sha256);
    input.meta.cwd = (JScalar){.kind = JS_STRING, .value.s = {"x\0\xed\xa0\x80", 5}};
    input.meta.depth = (JScalar){.kind = JS_INT, .value.i = INT64_MIN};
    input.meta.originator = (JScalar){.kind = JS_ARRAY, .empty = false};
    input.meta.cli_version = (JScalar){.kind = JS_OBJECT, .empty = true};
    input.meta.parent_thread_id = (JScalar){.kind = JS_NULL};
    input.meta.agent_role = (JScalar){.kind = JS_BOOL, .value.b = true};
    input.meta.branch = (JScalar){.kind = JS_FLOAT, .value.f = -0.0};
    TokenObservation observations[8] = {0};
    for (int i = 0; i < 8; i++) {
        observations[i].tag = (TokenTag)i;
        observations[i].line = (uint64_t)i;
        observations[i].ordinal = (TokenInteger){true, INT64_MAX};
        observations[i].model_state.kind = i % 3;
        observations[i].model_state.model = STR_LIT("synthetic-model");
        observations[i].total = (TokenTotals){true, true, 1, 2, 3, 4};
    }
    input.token_stream.observations = observations;
    input.token_stream.count = 8;
    input.token_stream.has_prepass = true;
    input.token_stream.prepass.project_path = STR_LIT("");
    unsigned char *bytes = NULL, *again = NULL;
    size_t n = 0, m = 0;
    ASSERT_EQ(ERR_OK, codec_encode(&input, &bytes, &n).code);
    LogRecord decoded = {0};
    ASSERT_EQ(ERR_OK,
              codec_decode(bytes, n, &input.key, input.reader.tail_sha256, &ids, &decoded).code);
    ASSERT_EQ(JS_ABSENT, decoded.meta.agent_path.kind);
    ASSERT_EQ(JS_NULL, decoded.meta.parent_thread_id.kind);
    ASSERT_TRUE(str_equal(input.meta.cwd.value.s, decoded.meta.cwd.value.s));
    ASSERT_TRUE(decoded.token_stream.prepass.project_path.p != NULL);
    ASSERT_EQ(ERR_OK, codec_encode(&decoded, &again, &m).code);
    ASSERT_EQ(n, m);
    ASSERT_TRUE(!memcmp(bytes, again, n));
    free(again);
    record_destroy(&decoded);
    for (size_t i = 0; i < n; i++) {
        ASSERT_EQ(
            ERR_INVALID,
            codec_decode(bytes, i, &input.key, input.reader.tail_sha256, &ids, &decoded).code);
        record_destroy(&decoded);
    }
    for (size_t i = 0; i < n; i++) {
        bytes[i] ^= 0x80;
        ASSERT_EQ(
            ERR_INVALID,
            codec_decode(bytes, n, &input.key, input.reader.tail_sha256, &ids, &decoded).code);
        record_destroy(&decoded);
        bytes[i] ^= 0x80;
    }
    DiscoveredLog wrong = input.key;
    wrong.size++;
    ASSERT_EQ(ERR_INVALID,
              codec_decode(bytes, n, &wrong, input.reader.tail_sha256, &ids, &decoded).code);
    record_destroy(&decoded);
    free(bytes);
    intern_destroy(&ids);
}

TEST(codec_rechecksummed_body_bounds_and_float_bits) {
    Intern ids;
    ASSERT_EQ(ERR_OK, intern_init(&ids).code);
    LogRecord source = {.identifiers = &ids,
                        .key = {.path = STR_LIT("/synthetic/bounds")},
                        .status = STR_LIT("empty")};
    sha256_hex("", 0, source.reader.tail_sha256);
    source.meta.depth = (JScalar){.kind = JS_FLOAT, .value.f = NAN};
    source.meta.branch = (JScalar){.kind = JS_FLOAT, .value.f = INFINITY};
    source.meta.sha = (JScalar){.kind = JS_FLOAT, .value.f = -INFINITY};
    TokenObservation blank = {.tag = TOKEN_B};
    source.token_stream.observations = &blank;
    source.token_stream.count = 1;
    unsigned char *data = NULL;
    size_t n = 0;
    ASSERT_EQ(ERR_OK, codec_encode(&source, &data, &n).code);
    LogRecord result = {0};
    ASSERT_EQ(ERR_OK,
              codec_decode(data, n, &source.key, source.reader.tail_sha256, &ids, &result).code);
    ASSERT_TRUE(isnan(result.meta.depth.value.f));
    ASSERT_EQ(INFINITY, result.meta.branch.value.f);
    ASSERT_EQ(-INFINITY, result.meta.sha.value.f);
    ASSERT_EQ(1, result.token_stream.count);
    record_destroy(&result);
    /* UINT32_MAX key length: checked before pointer arithmetic/allocation. */
    unsigned char saved[4];
    memcpy(saved, data + 13, 4);
    memset(data + 13, 255, 4);
    checksum(data, n);
    ASSERT_EQ(ERR_INVALID,
              codec_decode(data, n, &source.key, source.reader.tail_sha256, &ids, &result).code);
    record_destroy(&result);
    memcpy(data + 13, saved, 4);
    checksum(data, n);
    /* Every body byte is independently corrupted with a valid checksum. Some
     * scalar mutations remain valid; all rejected partial records must destroy. */
    for (size_t i = 12; i < n - 4; i++) {
        data[i] ^= 255;
        checksum(data, n);
        Err e = codec_decode(data, n, &source.key, source.reader.tail_sha256, &ids, &result);
        ASSERT_TRUE(e.code == ERR_OK || e.code == ERR_INVALID);
        record_destroy(&result);
        data[i] ^= 255;
        checksum(data, n);
    }
    free(data);
    intern_destroy(&ids);
}

TEST(codec_large_strings_and_invalid_wtf8_body) {
    Intern ids;
    ASSERT_EQ(ERR_OK, intern_init(&ids).code);
    size_t size = 4 * 1024 * 1024;
    char *text = malloc(size);
    ASSERT_TRUE(text);
    memset(text, 'a', size);
    text[size - 1] = 0;
    memcpy(text + size - 7, "\xed\xa0\x80\xed\xb0\x80", 6);
    LogRecord source = {.identifiers = &ids,
                        .key = {.path = STR_LIT("/synthetic/large")},
                        .meta = {.cwd = {.kind = JS_STRING, .value.s = {text, (uint32_t)size}}}};
    sha256_hex("", 0, source.reader.tail_sha256);
    unsigned char *bytes = NULL;
    size_t n = 0;
    ASSERT_EQ(ERR_OK, codec_encode(&source, &bytes, &n).code);
    LogRecord result = {0};
    ASSERT_EQ(ERR_OK,
              codec_decode(bytes, n, &source.key, source.reader.tail_sha256, &ids, &result).code);
    ASSERT_TRUE(str_equal(source.meta.cwd.value.s, result.meta.cwd.value.s));
    record_destroy(&result);
    size_t offset = 0;
    while (offset + 32 < n && memcmp(bytes + offset, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", 32))
        offset++;
    ASSERT_TRUE(offset + 32 < n);
    bytes[offset] = 0xff;
    checksum(bytes, n);
    ASSERT_EQ(ERR_INVALID,
              codec_decode(bytes, n, &source.key, source.reader.tail_sha256, &ids, &result).code);
    record_destroy(&result);
    free(bytes);
    free(text);
    intern_destroy(&ids);
}

TEST(codec_round_trips_ledger_session_totals_and_context_turn) {
    Intern ids;
    ASSERT_EQ(ERR_OK, intern_init(&ids).code);
    UsageRecord usage = {.session_id = {.kind = JS_STRING, .value.s = STR_LIT("synthetic-root")},
                         .thread_usage = {{.kind = JS_INT, .value.i = 31}, {.kind = JS_INT, .value.i = 7},
                                          {.kind = JS_INT, .value.i = 11}, {.kind = JS_INT, .value.i = 3}},
                         .turn_usage = {{.kind = JS_FLOAT, .value.f = 17.0}, {.kind = JS_INT, .value.i = 5},
                                        {.kind = JS_INT, .value.i = 9}, {.kind = JS_INT, .value.i = 2}}};
    TokenObservation context = {.tag = TOKEN_C, .turn_id = STR_LIT("synthetic-context")};
    LogRecord raw = {.key = {.path = STR_LIT("/synthetic/ledger-cache")},
                     .meta = {.request_session_id = STR_LIT("synthetic-root")},
                     .usage_records = &usage, .usage_count = 1,
                     .token_stream = {.observations = &context, .count = 1}};
    unsigned char *before = NULL, *after = NULL;
    size_t n = 0, m = 0;
    ASSERT_EQ(ERR_OK, codec_encode(&raw, &before, &n).code);
    LogRecord decoded = {0};
    ASSERT_EQ(ERR_OK, codec_decode(before, n, &raw.key, raw.reader.tail_sha256, &ids, &decoded).code);
    ASSERT_TRUE(str_equal(decoded.meta.request_session_id, STR_LIT("synthetic-root")));
    ASSERT_TRUE(str_equal(decoded.usage_records[0].session_id.value.s, STR_LIT("synthetic-root")));
    ASSERT_EQ(31, decoded.usage_records[0].thread_usage.input.value.i);
    ASSERT_EQ(7, decoded.usage_records[0].thread_usage.cached_input.value.i);
    ASSERT_EQ(11, decoded.usage_records[0].thread_usage.output.value.i);
    ASSERT_EQ(3, decoded.usage_records[0].thread_usage.reasoning.value.i);
    ASSERT_EQ(JS_FLOAT, decoded.usage_records[0].turn_usage.input.kind);
    ASSERT_EQ(17.0, decoded.usage_records[0].turn_usage.input.value.f);
    ASSERT_EQ(5, decoded.usage_records[0].turn_usage.cached_input.value.i);
    ASSERT_EQ(9, decoded.usage_records[0].turn_usage.output.value.i);
    ASSERT_EQ(2, decoded.usage_records[0].turn_usage.reasoning.value.i);
    ASSERT_TRUE(str_equal(decoded.token_stream.observations[0].turn_id, STR_LIT("synthetic-context")));
    ASSERT_EQ(ERR_OK, codec_encode(&decoded, &after, &m).code);
    ASSERT_EQ(n, m);
    ASSERT_EQ(0, memcmp(before, after, n));
    free(before); free(after);
    record_destroy(&decoded);
    intern_destroy(&ids);
}
