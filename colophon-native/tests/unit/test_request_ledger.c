#define _DARWIN_C_SOURCE
#include "corpus/assemble.h"
#include "meta/metadata.h"
#include "parse/record.h"
#include "price/compose.h"
#include "price/request_ledger.h"
#include "runner.h"
#include <stdio.h>
#include <math.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <unistd.h> /* mkdtemp; macOS declares it here */

typedef struct {
    char dir[1024], paths[2][1100];
    Intern ids;
    LogRecord records[2];
    size_t count;
    Corpus corpus;
    CodexMetadata metadata;
    PriorityTurns priority;
} LedgerFixture;

/* files[i] is a NULL-terminated list of JSONL lines; mtimes[i] orders copies (newest first). */
static void ledger_fixture(LedgerFixture *f, const char *const *const *files, size_t count, const long *mtimes) {
    memset(f, 0, sizeof *f);
    snprintf(f->dir, sizeof f->dir, "%s/synthetic-ledger-XXXXXX", getenv("COLOPHON_HOME"));
    ASSERT_TRUE(mkdtemp(f->dir));
    ASSERT_EQ(ERR_OK, intern_init(&f->ids).code);
    AssemblyRecord input[2];
    ASSERT_TRUE(count >= 1 && count <= 2);
    for (size_t i = 0; i < count; i++) {
        snprintf(f->paths[i], sizeof f->paths[i], "%s/rollout-synthetic-%zu.jsonl", f->dir, i);
        FILE *file = fopen(f->paths[i], "wb");
        ASSERT_TRUE(file);
        for (const char *const *line = files[i]; *line; line++) ASSERT_TRUE(fprintf(file, "%s\n", *line) > 0);
        ASSERT_EQ(0, fclose(file));
        long when = mtimes ? mtimes[i] : 1700000000L;
        struct timeval times[2] = {{when, 0}, {when, 0}};
        ASSERT_EQ(0, utimes(f->paths[i], times));
        struct stat st;
        ASSERT_EQ(0, stat(f->paths[i], &st));
        DiscoveredLog key = {.path = {f->paths[i], (uint32_t)strlen(f->paths[i])}, .size = st.st_size,
                             .mtime_ns = (int64_t)st.st_mtimespec.tv_sec * 1000000000 + st.st_mtimespec.tv_nsec,
                             .stat_ok = true};
        ASSERT_EQ(ERR_OK, record_parse(&key, &f->ids, NULL, &f->records[i]).code);
        input[i] = assembly_record(&f->records[i]);
    }
    f->count = count;
    ASSERT_EQ(ERR_OK, corpus_build(input, count, &f->metadata, 0, &f->ids, &f->corpus).code);
    ASSERT_EQ(ERR_OK, compose_usage(&f->corpus, &f->priority).code);
}
static void ledger_fixture_destroy(LedgerFixture *f) {
    corpus_destroy(&f->corpus);
    priority_destroy(&f->priority);
    metadata_destroy(&f->metadata);
    for (size_t i = 0; i < f->count; i++) record_destroy(&f->records[i]);
    intern_destroy(&f->ids);
}
static SessionModel *only_session(LedgerFixture *f) {
    ASSERT_EQ(1, f->corpus.sessions.size);
    return f->corpus.sessions.first->value;
}
#define META(id, sid) "{\"type\":\"session_meta\",\"timestamp\":\"2030-01-02T12:00:00Z\",\"payload\":{\"id\":\"" id "\",\"session_id\":\"" sid "\",\"cwd\":\"/synthetic/kite\"}}"
#define STARTED(sec, turn) "{\"type\":\"event_msg\",\"timestamp\":\"2030-01-02T12:00:" sec "Z\",\"payload\":{\"type\":\"task_started\",\"turn_id\":\"" turn "\"}}"
#define CONTEXT(sec, turn) "{\"type\":\"turn_context\",\"timestamp\":\"2030-01-02T12:00:" sec "Z\",\"payload\":{\"model\":\"gpt-5\",\"turn_id\":\"" turn "\"}}"
#define USAGE(i, c, o) "{\"input_tokens\":" #i ",\"cached_input_tokens\":" #c ",\"output_tokens\":" #o ",\"reasoning_output_tokens\":0}"
/* LEDGER(time, thread, session_id field (with trailing comma or empty), response field, turn field, usage, thread total) */
#define LEDGER(ts, thread, sid, resp, turn, use, total) "{\"type\":\"token_usage_record\",\"timestamp\":\"2030-01-02T12:00:" ts "Z\",\"payload\":{\"thread_id\":\"" thread "\"," sid resp turn "\"usage\":" use ",\"thread_token_usage\":" total "}}"
#define COUNT(ts, last, total) "{\"type\":\"event_msg\",\"timestamp\":\"2030-01-02T12:00:" ts "Z\",\"payload\":{\"type\":\"token_count\",\"info\":{\"last_token_usage\":" last ",\"total_token_usage\":" total "}}}"

static size_t record_units(SessionModel *s) {
    size_t n = 0;
    for (size_t i = 0; i < s->unit_count; i++) n += str_equal(s->units[i].source, STR_LIT("record"));
    return n;
}
TEST(ledger_rejects_record_without_response_id) {
    const char *lines[] = {META("synthetic-ledger", "synthetic-ledger"), STARTED("01", "synthetic-turn"),
        LEDGER("02", "synthetic-ledger", "", "", "\"turn_id\":\"synthetic-turn\",", USAGE(100, 0, 10), USAGE(100, 0, 10)), NULL};
    const char *const *files[] = {lines};
    LedgerFixture f; ledger_fixture(&f, files, 1, NULL);
    ASSERT_EQ(0, record_units(only_session(&f)));
    ledger_fixture_destroy(&f);
}
TEST(ledger_rejects_missing_or_short_thread_total) {
    const char *missing = "{\"type\":\"token_usage_record\",\"timestamp\":\"2030-01-02T12:00:02Z\",\"payload\":{\"thread_id\":\"synthetic-ledger\",\"response_id\":\"synthetic-r1\",\"usage\":" USAGE(100, 0, 10) "}}";
    const char *lines[] = {META("synthetic-ledger", "synthetic-ledger"), missing,
        LEDGER("03", "synthetic-ledger", "", "\"response_id\":\"synthetic-r2\",", "", USAGE(100, 0, 10), USAGE(99, 0, 10)), NULL};
    const char *const *files[] = {lines};
    LedgerFixture f; ledger_fixture(&f, files, 1, NULL);
    ASSERT_EQ(0, record_units(only_session(&f)));
    ledger_fixture_destroy(&f);
}
TEST(ledger_rejects_fractional_or_boolean_counts_and_accepts_integral_float) {
    const char *lines[] = {META("synthetic-ledger", "synthetic-ledger"),
        LEDGER("02", "synthetic-ledger", "", "\"response_id\":\"synthetic-r1\",", "", "{\"input_tokens\":7.5,\"output_tokens\":1}", USAGE(100, 0, 10)),
        LEDGER("03", "synthetic-ledger", "", "\"response_id\":\"synthetic-r2\",", "", "{\"input_tokens\":7,\"output_tokens\":true}", USAGE(100, 0, 10)),
        LEDGER("04", "synthetic-ledger", "", "\"response_id\":\"synthetic-r3\",", "", "{\"input_tokens\":7.0,\"output_tokens\":1}", USAGE(100, 0, 10)), NULL};
    const char *const *files[] = {lines};
    LedgerFixture f; ledger_fixture(&f, files, 1, NULL);
    SessionModel *s = only_session(&f);
    ASSERT_EQ(1, record_units(s));
    ASSERT_EQ(7, s->units[0].input);
    ledger_fixture_destroy(&f);
}
TEST(ledger_accepts_root_session_id_for_subagent) {
    const char *lines[] = {META("synthetic-child", "synthetic-root"),
        LEDGER("02", "synthetic-child", "\"session_id\":\"synthetic-root\",", "\"response_id\":\"synthetic-r1\",", "", USAGE(100, 0, 10), USAGE(100, 0, 10)),
        LEDGER("03", "synthetic-child", "\"session_id\":\"synthetic-other\",", "\"response_id\":\"synthetic-r2\",", "", USAGE(50, 0, 5), USAGE(150, 0, 15)), NULL};
    const char *const *files[] = {lines};
    LedgerFixture f; ledger_fixture(&f, files, 1, NULL);
    SessionModel *s = only_session(&f);
    ASSERT_EQ(1, record_units(s));
    ASSERT_EQ(100, s->units[0].input);
    ledger_fixture_destroy(&f);
}
TEST(ledger_record_without_turn_inherits_task_started_turn) {
    const char *lines[] = {META("synthetic-ledger", "synthetic-ledger"), CONTEXT("01", "synthetic-context"), STARTED("01", "synthetic-turn"),
        LEDGER("02", "synthetic-ledger", "", "\"response_id\":\"synthetic-r1\",", "", USAGE(100, 0, 10), USAGE(100, 0, 10)), NULL};
    const char *const *files[] = {lines};
    LedgerFixture f; ledger_fixture(&f, files, 1, NULL);
    SessionModel *s = only_session(&f);
    ASSERT_EQ(1, record_units(s));
    ASSERT_TRUE(str_equal(s->units[0].turn_id, STR_LIT("synthetic-turn")));
    ledger_fixture_destroy(&f);
}
TEST(ledger_record_without_turn_falls_back_to_turn_context) {
    const char *lines[] = {META("synthetic-ledger", "synthetic-ledger"), CONTEXT("01", "synthetic-context"),
        LEDGER("02", "synthetic-ledger", "", "\"response_id\":\"synthetic-r1\",", "", USAGE(100, 0, 10), USAGE(100, 0, 10)), NULL};
    const char *const *files[] = {lines};
    LedgerFixture f; ledger_fixture(&f, files, 1, NULL);
    SessionModel *s = only_session(&f);
    ASSERT_EQ(1, record_units(s));
    ASSERT_TRUE(str_equal(s->units[0].turn_id, STR_LIT("synthetic-context")));
    ledger_fixture_destroy(&f);
}

TEST(ledger_and_context_choose_first_nonempty_turn_alias) {
    const char *aliases[] = {
        "\"turn_id\":\"\",\"turnId\":\"synthetic-alternate\",\"id\":\"synthetic-later\",",
        "\"turn_id\":null,\"turnId\":\"\",\"info\":{\"turn_id\":\"\",\"turnId\":\"synthetic-alternate\"},",
        "\"turn_id\":\"\",\"turnId\":false,\"id\":\"synthetic-alternate\","
    };
    for (size_t i = 0; i < sizeof aliases / sizeof *aliases; i++) {
        char context[1024], ledger[1024];
        snprintf(context, sizeof context, "{\"type\":\"turn_context\",\"timestamp\":\"2030-01-02T12:00:01Z\",\"payload\":{%s\"model\":\"gpt-5\"}}", aliases[i]);
        snprintf(ledger, sizeof ledger, "{\"type\":\"token_usage_record\",\"timestamp\":\"2030-01-02T12:00:02Z\",\"payload\":{\"thread_id\":\"synthetic-ledger\",\"response_id\":\"synthetic-r1\",%s\"usage\":" USAGE(7,0,1) ",\"thread_token_usage\":" USAGE(7,0,1) "}}", aliases[i]);
        const char *lines[] = {META("synthetic-ledger", "synthetic-ledger"), context, ledger, NULL};
        const char *const *files[] = {lines};
        LedgerFixture f; ledger_fixture(&f, files, 1, NULL);
        ASSERT_EQ(1, record_units(only_session(&f)));
        ASSERT_TRUE(str_equal(f.records[0].usage_records[0].turn_id.value.s, STR_LIT("synthetic-alternate")));
        ASSERT_TRUE(str_equal(f.records[0].token_stream.observations[1].turn_id, STR_LIT("synthetic-alternate")));
        ASSERT_TRUE(str_equal(only_session(&f)->units[0].turn_id, STR_LIT("synthetic-alternate")));
        ledger_fixture_destroy(&f);
    }
}

TEST(ledger_started_without_turn_retains_latest_context) {
    const char *lines[] = {META("synthetic-ledger", "synthetic-ledger"), CONTEXT("01", "synthetic-context"),
        STARTED("02", "synthetic-old"), STARTED("03", ""),
        LEDGER("04", "synthetic-ledger", "", "\"response_id\":\"synthetic-r1\",", "", USAGE(7,0,1), USAGE(7,0,1)), NULL};
    const char *const *files[] = {lines};
    LedgerFixture f; ledger_fixture(&f, files, 1, NULL);
    ASSERT_TRUE(str_equal(only_session(&f)->units[0].turn_id, STR_LIT("synthetic-context")));
    ledger_fixture_destroy(&f);
}

TEST(ledger_totals_numeric_boundaries) {
    UsageScalars s = {.input = {.kind = JS_INT, .value.i = 7}, .output = {.kind = JS_INT, .value.i = 1}};
    RequestTotals t;
    ASSERT_TRUE(request_totals_decode(&s, &t));
    ASSERT_EQ(0, t.cached); ASSERT_EQ(0, t.reasoning);
    JScalar invalid[] = {{.kind = JS_ABSENT}, {.kind = JS_NULL}, {.kind = JS_BOOL},
        {.kind = JS_STRING, .value.s = STR_LIT("7")}, {.kind = JS_ARRAY}, {.kind = JS_OBJECT},
        {.kind = JS_INT, .value.i = -1}, {.kind = JS_INT, .value.i = INT64_MAX},
        {.kind = JS_FLOAT, .value.f = 7.5}, {.kind = JS_FLOAT, .value.f = INFINITY},
        {.kind = JS_FLOAT, .value.f = NAN}, {.kind = JS_FLOAT, .value.f = 0x1p63}};
    for (size_t i = 0; i < sizeof invalid / sizeof *invalid; i++) {
        s.input = invalid[i]; ASSERT_FALSE(request_totals_decode(&s, &t));
    }
    s.input = (JScalar){.kind = JS_INT, .value.i = 7};
    s.cached_input = (JScalar){.kind = JS_INT, .value.i = 8}; ASSERT_FALSE(request_totals_decode(&s, &t));
    s.cached_input = (JScalar){0};
    s.reasoning = (JScalar){.kind = JS_INT, .value.i = 2}; ASSERT_FALSE(request_totals_decode(&s, &t));
    s.reasoning = (JScalar){.kind = JS_NULL}; ASSERT_FALSE(request_totals_decode(&s, &t));
    s.reasoning = (JScalar){0};
    s.input.value.i = INT64_MAX / 2 + 1; s.output.value.i = INT64_MAX / 2 + 1;
    ASSERT_FALSE(request_totals_decode(&s, &t));
}

static UsageRecord valid_ledger(void) {
    return (UsageRecord){.thread_id = {.kind = JS_STRING, .value.s = STR_LIT("synthetic-ledger")},
        .response_id = {.kind = JS_STRING, .value.s = STR_LIT(" synthetic-response ")},
        .ts = {.kind = JS_STRING, .value.s = STR_LIT("2030-01-02T12:00:02Z")},
        .input = {.kind = JS_INT, .value.i = 7}, .output = {.kind = JS_INT, .value.i = 2},
        .thread_usage = {.input = {.kind = JS_INT, .value.i = 7}, .output = {.kind = JS_INT, .value.i = 2}}};
}
TEST(ledger_acceptance_order_optional_totals_and_identity) {
    Arena a = {0}; LedgerRecord result; LedgerVerdict verdict;
    UsageRecord u = valid_ledger();
    ASSERT_EQ(ERR_OK, ledger_record_accept(&a, &u, STR_LIT("synthetic-ledger"), STR_LIT("synthetic-root"), &result, &verdict).code);
    ASSERT_EQ(LEDGER_ACCEPTED, verdict);
    ASSERT_TRUE(str_equal(result.response_id, STR_LIT("synthetic-response")));
    ASSERT_FALSE(result.has_turn_total); ASSERT_FALSE(result.has_reasoning);
    u.turn_usage = u.thread_usage;
    u.turn_usage.output.value.i = 1;
    ASSERT_EQ(ERR_OK, ledger_record_accept(&a, &u, STR_LIT("synthetic-ledger"), STR_LIT("synthetic-root"), &result, &verdict).code);
    ASSERT_EQ(LEDGER_ACCEPTED, verdict); ASSERT_FALSE(result.has_turn_total);
    u.turn_usage.output.value.i = 2;
    ASSERT_EQ(ERR_OK, ledger_record_accept(&a, &u, STR_LIT("synthetic-ledger"), STR_LIT("synthetic-root"), &result, &verdict).code);
    ASSERT_TRUE(result.has_turn_total);
    u.thread_id.value.s = STR_LIT(" synthetic-foreign "); u.response_id = (JScalar){0};
    ASSERT_EQ(ERR_OK, ledger_record_accept(&a, &u, STR_LIT("synthetic-ledger"), STR_LIT("synthetic-root"), &result, &verdict).code);
    ASSERT_EQ(LEDGER_FOREIGN, verdict);
    u = valid_ledger(); u.session_id = (JScalar){.kind = JS_NULL};
    ASSERT_EQ(ERR_OK, ledger_record_accept(&a, &u, STR_LIT("synthetic-ledger"), STR_LIT("synthetic-root"), &result, &verdict).code);
    ASSERT_EQ(LEDGER_INVALID, verdict);
    u.session_id = (JScalar){.kind = JS_STRING, .value.s = STR_LIT(" synthetic-root ")};
    ASSERT_EQ(ERR_OK, ledger_record_accept(&a, &u, STR_LIT("synthetic-ledger"), STR_LIT("synthetic-root"), &result, &verdict).code);
    ASSERT_EQ(LEDGER_ACCEPTED, verdict);
    u.ts.value.s = STR_LIT("synthetic-invalid-timestamp");
    ASSERT_EQ(ERR_OK, ledger_record_accept(&a, &u, STR_LIT("synthetic-ledger"), STR_LIT("synthetic-root"), &result, &verdict).code);
    ASSERT_EQ(LEDGER_INVALID, verdict);
    u = valid_ledger(); u.thread_id.value.s = STR_LIT(" synthetic-e\xcc\x81 ");
    ASSERT_EQ(ERR_OK, ledger_record_accept(&a, &u, STR_LIT("synthetic-\xc3\xa9"), STR_LIT("synthetic-root"), &result, &verdict).code);
    ASSERT_EQ(LEDGER_ACCEPTED, verdict);
    arena_destroy(&a);
}
TEST(ledger_cached_input_ignores_snapshot_cache_read_alias) {
    const char *lines[] = {META("synthetic-ledger", "synthetic-ledger"),
        LEDGER("02", "synthetic-ledger", "", "\"response_id\":\"synthetic-r1\",", "",
               "{\"input_tokens\":7,\"cache_read_input_tokens\":6,\"output_tokens\":1}", USAGE(7,0,1)), NULL};
    const char *const *files[] = {lines};
    LedgerFixture f; ledger_fixture(&f, files, 1, NULL);
    ASSERT_EQ(1, record_units(only_session(&f)));
    ASSERT_EQ(0, only_session(&f)->units[0].cached);
    ledger_fixture_destroy(&f);
}

TEST(ledger_truncated_context_keeps_previous_active_turn) {
    size_t size = TOKEN_LINE_LIMIT + 1024;
    char *large = malloc(size);
    ASSERT_TRUE(large);
    int n = snprintf(large, size, "{\"type\":\"turn_context\",\"timestamp\":\"2030-01-02T12:00:02Z\",\"payload\":{\"model\":\"gpt-5\",\"turn_id\":\"synthetic-unretained\",\"padding\":\"");
    ASSERT_TRUE(n > 0);
    memset(large + n, 'x', size - (size_t)n - 4);
    memcpy(large + size - 4, "\"}}", 4);
    const char *lines[] = {META("synthetic-ledger", "synthetic-ledger"), CONTEXT("01", "synthetic-context"), large,
        LEDGER("03", "synthetic-ledger", "", "\"response_id\":\"synthetic-r1\",", "", USAGE(7,0,1), USAGE(7,0,1)), NULL};
    const char *const *files[] = {lines};
    LedgerFixture f; ledger_fixture(&f, files, 1, NULL);
    ASSERT_EQ(TOKEN_XC, f.records[0].token_stream.observations[2].tag);
    ASSERT_EQ(0, f.records[0].token_stream.observations[2].turn_id.n);
    ASSERT_TRUE(str_equal(only_session(&f)->units[0].turn_id, STR_LIT("synthetic-context")));
    ledger_fixture_destroy(&f); free(large);
}
