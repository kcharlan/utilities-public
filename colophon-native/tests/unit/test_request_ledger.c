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
#define SETTINGS(sec, tier) "{\"type\":\"event_msg\",\"timestamp\":\"2030-01-02T12:00:" sec "Z\",\"payload\":{\"type\":\"thread_settings_applied\",\"thread_settings\":{\"service_tier\":\"" tier "\"}}}"
#define STARTED_NO_TURN(sec) "{\"type\":\"event_msg\",\"timestamp\":\"2030-01-02T12:00:" sec "Z\",\"payload\":{\"type\":\"task_started\"}}"

TEST(tokenstream_records_thread_settings_priority) {
    const char *lines[] = {META("synthetic-ledger", "synthetic-ledger"), SETTINGS("01", " priority "), SETTINGS("02", "default"), NULL};
    const char *const *files[] = {lines};
    LedgerFixture f; ledger_fixture(&f, files, 1, NULL);
    const TokenStream *t = &f.records[0].token_stream;
    size_t seen = 0;
    for (size_t i = 0; i < t->count; i++)
        if (t->observations[i].tag == TOKEN_P) ASSERT_EQ(seen++ == 0, t->observations[i].priority);
    ASSERT_EQ(2, seen);
    ledger_fixture_destroy(&f);
}
TEST(compose_marks_turns_started_under_priority_setting) {
    const char *lines[] = {META("synthetic-ledger", "synthetic-ledger"), SETTINGS("01", "priority"), STARTED("02", "synthetic-fast"),
        COUNT("03", USAGE(100, 0, 10), USAGE(100, 0, 10)), SETTINGS("04", "default"), STARTED("05", "synthetic-standard"),
        COUNT("06", USAGE(50, 0, 5), USAGE(150, 0, 15)), NULL};
    const char *const *files[] = {lines};
    LedgerFixture f; ledger_fixture(&f, files, 1, NULL);
    SessionModel *s = only_session(&f);
    ASSERT_EQ(2, s->unit_count);
    ASSERT_TRUE(s->units[0].priority_tier && s->units[0].priority == NULL);
    ASSERT_FALSE(s->units[1].priority_tier);
    ledger_fixture_destroy(&f);
}
TEST(compose_priority_follows_latest_start_of_same_turn) {
    const char *lines[] = {META("synthetic-ledger", "synthetic-ledger"), SETTINGS("01", "priority"), STARTED("02", "synthetic-turn"),
        COUNT("03", USAGE(100, 0, 10), USAGE(100, 0, 10)), SETTINGS("04", "default"), STARTED("05", "synthetic-turn"),
        COUNT("06", USAGE(50, 0, 5), USAGE(150, 0, 15)), NULL};
    const char *const *files[] = {lines};
    LedgerFixture f; ledger_fixture(&f, files, 1, NULL);
    SessionModel *s = only_session(&f);
    ASSERT_EQ(2, s->unit_count);
    ASSERT_TRUE(s->units[0].priority_tier);
    ASSERT_FALSE(s->units[1].priority_tier);
    ledger_fixture_destroy(&f);
}
TEST(compose_turnless_rows_follow_turnless_start) {
    const char *lines[] = {META("synthetic-ledger", "synthetic-ledger"), SETTINGS("01", "priority"), STARTED_NO_TURN("02"),
        COUNT("03", USAGE(100, 0, 10), USAGE(100, 0, 10)), SETTINGS("04", "default"), STARTED_NO_TURN("05"),
        COUNT("06", USAGE(50, 0, 5), USAGE(150, 0, 15)), NULL};
    const char *const *files[] = {lines};
    LedgerFixture f; ledger_fixture(&f, files, 1, NULL);
    SessionModel *s = only_session(&f);
    ASSERT_EQ(2, s->unit_count);
    ASSERT_TRUE(s->units[0].priority_tier);
    ASSERT_FALSE(s->units[1].priority_tier);
    ledger_fixture_destroy(&f);
}
TEST(compose_priority_setting_persists_and_changes_only_at_start) {
    const char *lines[] = {META("synthetic-ledger", "synthetic-ledger"), SETTINGS("01", "priority"), STARTED("02", "synthetic-turn"),
        COUNT("03", USAGE(100, 0, 10), USAGE(100, 0, 10)), STARTED("04", "synthetic-turn"),
        SETTINGS("05", "default"), COUNT("06", USAGE(50, 0, 5), USAGE(150, 0, 15)),
        STARTED("07", "synthetic-turn"), COUNT("08", USAGE(25, 0, 2), USAGE(175, 0, 17)), NULL};
    const char *const *files[] = {lines};
    LedgerFixture f; ledger_fixture(&f, files, 1, NULL);
    SessionModel *s = only_session(&f);
    ASSERT_EQ(3, s->unit_count);
    ASSERT_TRUE(s->units[0].priority_tier);
    ASSERT_TRUE(s->units[1].priority_tier);
    ASSERT_FALSE(s->units[2].priority_tier);
    ledger_fixture_destroy(&f);
}
TEST(compose_priority_record_resume_is_line_sensitive) {
    const char *lines[] = {META("synthetic-ledger", "synthetic-ledger"), SETTINGS("01", "priority"), STARTED("02", "synthetic-turn"),
        LEDGER("03", "synthetic-ledger", "", "\"response_id\":\"synthetic-r1\",", "", USAGE(100, 0, 10), USAGE(100, 0, 10)),
        SETTINGS("04", "default"), STARTED("05", "synthetic-turn"),
        LEDGER("06", "synthetic-ledger", "", "\"response_id\":\"synthetic-r2\",", "", USAGE(50, 0, 5), USAGE(150, 0, 15)), NULL};
    const char *const *files[] = {lines};
    LedgerFixture f; ledger_fixture(&f, files, 1, NULL);
    SessionModel *s = only_session(&f);
    ASSERT_EQ(2, s->unit_count);
    ASSERT_TRUE(str_equal(s->units[0].source, STR_LIT("record")));
    ASSERT_TRUE(str_equal(s->units[1].source, STR_LIT("record")));
    ASSERT_TRUE(s->units[0].priority_tier && s->units[0].priority == NULL);
    ASSERT_FALSE(s->units[1].priority_tier);
    ledger_fixture_destroy(&f);
}
TEST(compose_priority_bare_rows_use_file_local_start_history) {
    const char *fast[] = {META("synthetic-ledger", "synthetic-ledger"), SETTINGS("01", "priority"), STARTED("02", "synthetic-turn"),
        "{\"timestamp\":\"2030-01-02T12:00:03Z\",\"usage\":" USAGE(100, 0, 10) "}", NULL};
    const char *normal[] = {META("synthetic-ledger", "synthetic-ledger"), STARTED("02", "synthetic-turn"),
        "{\"timestamp\":\"2030-01-02T12:00:04Z\",\"usage\":" USAGE(50, 0, 5) "}", NULL};
    const char *const *files[] = {fast, normal};
    LedgerFixture f; ledger_fixture(&f, files, 2, NULL);
    SessionModel *s = only_session(&f);
    ASSERT_EQ(2, s->unit_count);
    for (size_t i = 0; i < s->unit_count; i++) {
        ASSERT_TRUE(str_equal(s->units[i].source, STR_LIT("bare")));
        ASSERT_EQ(s->units[i].input == 100, s->units[i].priority_tier);
    }
    ledger_fixture_destroy(&f);
}
TEST(tokenstream_thread_priority_requires_string_tier_and_valid_timestamp) {
    const char *lines[] = {META("synthetic-ledger", "synthetic-ledger"),
        SETTINGS("01", "Priority"),
        "{\"type\":\"event_msg\",\"timestamp\":\"2030-01-02T12:00:02Z\",\"payload\":{\"type\":\"thread_settings_applied\",\"thread_settings\":{\"service_tier\":true}}}",
        "{\"type\":\"event_msg\",\"timestamp\":\"2030-01-02T12:00:03Z\",\"payload\":{\"type\":\"thread_settings_applied\"}}",
        "{\"type\":\"event_msg\",\"timestamp\":\"synthetic-invalid\",\"payload\":{\"type\":\"thread_settings_applied\",\"thread_settings\":{\"service_tier\":\"priority\"}}}", NULL};
    const char *const *files[] = {lines};
    LedgerFixture f; ledger_fixture(&f, files, 1, NULL);
    size_t seen = 0;
    for (size_t i = 0; i < f.records[0].token_stream.count; i++) {
        const TokenObservation *o = &f.records[0].token_stream.observations[i];
        if (o->tag != TOKEN_P) continue;
        seen++;
        ASSERT_FALSE(o->priority);
    }
    ASSERT_EQ(3, seen);
    ledger_fixture_destroy(&f);
}

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
/* Output is one tenth of input on both usage and totals, so counter advances can be exact. */
static PairSide snap(const char *turn, int64_t in, int64_t total_in, const char *ts, int64_t ms) {
  return (PairSide){.turn = turn ? (Str){turn, (uint32_t)strlen(turn)} : (Str){0}, .usage = {in, 0, in / 10, 0},
                    .has_total = true, .total = {total_in, 0, total_in / 10, 0}, .timestamp = {ts, (uint32_t)strlen(ts)},
                    .ms = {true, ms}};
}
static PairSide ledger(const char *turn, int64_t in, int64_t total_in, const char *ts, int64_t ms, bool replay) {
  PairSide side = snap(turn, in, total_in, ts, ms);
  side.replay = replay;
  return side;
}
static bool pair_one(PairSide s, PairSide l, bool snapshot_first, bool boundary_between) {
  PairEvent events[3];
  size_t n = 0;
  PairEvent se = {PAIR_SNAPSHOT, snapshot_first ? 1 : 3, 0}, le = {PAIR_LEDGER, snapshot_first ? 3 : 1, 0};
  events[n++] = snapshot_first ? se : le;
  if (boundary_between) events[n++] = (PairEvent){PAIR_BOUNDARY, 2, 0};
  events[n++] = snapshot_first ? le : se;
  bool matched = false;
  ASSERT_EQ(ERR_OK, request_pair_file(&s, 1, &l, 1, events, n, &matched).code);
  return matched;
}
TEST(pairing_matches_adjacent_snapshot_either_order) {
  ASSERT_TRUE(pair_one(snap("t", 100, 900, "a", 1000), ledger("t", 100, 100, "b", 1300, false), false, false));
  ASSERT_TRUE(pair_one(snap("t", 100, 900, "a", 1300), ledger("t", 100, 100, "b", 1000, false), true, false));
}
TEST(pairing_rejects_other_turn_other_usage_or_boundary) {
  ASSERT_FALSE(pair_one(snap("t", 100, 900, "a", 1000), ledger("u", 100, 100, "b", 1300, false), false, false));
  ASSERT_FALSE(pair_one(snap("t", 101, 900, "a", 1000), ledger("t", 100, 100, "b", 1300, false), false, false));
  ASSERT_FALSE(pair_one(snap("t", 100, 900, "a", 1000), ledger("t", 100, 100, "b", 1300, false), false, true));
}
TEST(pairing_counter_alias_matches_without_time_or_turn) {
  ASSERT_TRUE(pair_one(snap(NULL, 100, 400, "a", 1000), ledger(NULL, 100, 400, "b", 90000, false), false, false));
  ASSERT_FALSE(pair_one(snap(NULL, 100, 900, "a", 1000), ledger(NULL, 100, 400, "b", 1100, false), false, false));
}
TEST(pairing_near_match_ignores_reasoning_but_alias_does_not) {
  PairSide l = ledger("t", 100, 100, "b", 1300, false);
  l.usage.reasoning = 5;
  ASSERT_TRUE(pair_one(snap("t", 100, 900, "a", 1000), l, false, false));
  PairSide aliased = ledger(NULL, 100, 400, "b", 90000, false);
  aliased.usage.reasoning = 5;
  ASSERT_FALSE(pair_one(snap(NULL, 100, 400, "a", 1000), aliased, false, false));
}
TEST(pairing_matches_near_pair_despite_counter_offset) {
  ASSERT_TRUE(pair_one(snap("t", 100, 100, "a", 5000), ledger("t", 100, 7100, "b", 1000, false), false, false));
  ASSERT_FALSE(pair_one(snap("t", 100, 100, "a", 6001), ledger("t", 100, 7100, "b", 1000, false), false, false));
}
TEST(pairing_replay_needs_alias_or_same_time) {
  ASSERT_FALSE(pair_one(snap("t", 100, 900, "a", 1000), ledger("t", 100, 100, "b", 1300, true), false, false));
  ASSERT_TRUE(pair_one(snap("t", 100, 900, "same", 1000), ledger("t", 100, 100, "same", 1000, true), false, false));
}
TEST(pairing_intervening_later_side_blocks_near_match) {
  /* S0 sets the snapshot counter at 100; a boundary separates it from the record. S1 then
   * advances the counter by 300 for a 100-token request (intervening) or by exactly 100 (control). */
  const int64_t later_totals[2] = {400, 200};
  const bool expected[2] = {false, true};
  for (size_t i = 0; i < 2; i++) {
    PairSide snaps[2] = {snap("t", 100, 100, "a", 0), snap("t", 100, later_totals[i], "c", 1300)};
    PairSide led = ledger("t", 100, 7000, "b", 1000, false);
    PairEvent events[4] = {{PAIR_SNAPSHOT, 1, 0}, {PAIR_BOUNDARY, 2, 0}, {PAIR_LEDGER, 3, 0}, {PAIR_SNAPSHOT, 4, 1}};
    bool matched[2];
    ASSERT_EQ(ERR_OK, request_pair_file(snaps, 2, &led, 1, events, 4, matched).code);
    ASSERT_FALSE(matched[0]);
    ASSERT_EQ(expected[i], matched[1]);
  }
}
TEST(pairing_delayed_exact_advances_pair_outside_window) {
  /* Ledger counters sit 1000 above snapshot counters, so only the delayed exact rule can pair S1. */
  PairSide snaps[2] = {snap("t", 50, 50, "a", 0), snap("t", 100, 150, "d", 40000)};
  PairSide leds[2] = {ledger("t", 50, 1050, "b", 0, false), ledger("t", 100, 1150, "c", 1000, false)};
  PairEvent events[4] = {{PAIR_LEDGER, 1, 0}, {PAIR_SNAPSHOT, 2, 0}, {PAIR_LEDGER, 3, 1}, {PAIR_SNAPSHOT, 4, 1}};
  bool matched[2];
  ASSERT_EQ(ERR_OK, request_pair_file(snaps, 2, leds, 2, events, 4, matched).code);
  ASSERT_TRUE(matched[0]);
  ASSERT_TRUE(matched[1]);
}
TEST(pairing_claims_one_snapshot_per_record) {
  PairSide snaps[2] = {snap("t", 100, 900, "a", 1100), snap("t", 100, 1000, "c", 1200)};
  PairSide led = ledger("t", 100, 100, "b", 1000, false);
  PairEvent events[3] = {{PAIR_LEDGER, 1, 0}, {PAIR_SNAPSHOT, 2, 0}, {PAIR_SNAPSHOT, 3, 1}};
  bool matched[2];
  ASSERT_EQ(ERR_OK, request_pair_file(snaps, 2, &led, 1, events, 3, matched).code);
  ASSERT_TRUE(matched[0]);
  ASSERT_FALSE(matched[1]);
}
TEST(pairing_earlier_near_claim_survives_later_exact_candidate) {
  PairSide snaps[2] = {snap("synthetic-turn", 100, 0, "03", 3000), snap("synthetic-turn", 100, 0, "02", 2000)};
  snaps[0].has_total = snaps[1].has_total = false;
  PairSide led = ledger("synthetic-turn", 100, 100, "02", 2000, false);
  PairEvent events[3] = {{PAIR_LEDGER, 1, 0}, {PAIR_SNAPSHOT, 2, 0}, {PAIR_SNAPSHOT, 3, 1}};
  bool matched[2];
  ASSERT_EQ(ERR_OK, request_pair_file(snaps, 2, &led, 1, events, 3, matched).code);
  ASSERT_TRUE(matched[0]);
  ASSERT_FALSE(matched[1]);
}
TEST(pairing_owned_repeat_preserves_other_pending_response) {
  PairSide ss[] = {snap("synthetic-turn",100,0,"03",3000), snap("synthetic-turn",100,0,"03",3000),
                  snap("synthetic-turn",100,0,"05",5000)};
  for (size_t i=0;i<3;i++) ss[i].has_total = false;
  PairSide ls[] = {ledger("synthetic-turn",100,100,"02",2000,false),
                  ledger("synthetic-turn",100,200,"04",4000,false)};
  ls[0].response_id = STR_LIT("synthetic-r1"); ls[1].response_id = STR_LIT("synthetic-r2");
  PairEvent events[] = {{PAIR_LEDGER,1,0},{PAIR_SNAPSHOT,2,0},{PAIR_LEDGER,3,1},
                        {PAIR_SNAPSHOT,4,1},{PAIR_SNAPSHOT,5,2}};
  bool matched[3];
  ASSERT_EQ(ERR_OK,request_pair_file(ss,3,ls,2,events,5,matched).code);
  ASSERT_TRUE(matched[0]); ASSERT_FALSE(matched[1]); ASSERT_TRUE(matched[2]);
}
TEST(pairing_replay_does_not_borrow_original_owned_near_alias) {
  PairSide ss[] = {snap("synthetic-turn",100,0,"03",3000), snap("synthetic-turn",100,0,"03",3000)};
  ss[0].has_total = ss[1].has_total = false;
  PairSide ls[] = {ledger("synthetic-turn",100,100,"02",2000,false),
                  ledger("synthetic-turn",100,100,"04",4000,true)};
  ls[0].response_id = ls[1].response_id = STR_LIT("synthetic-r1");
  PairEvent events[] = {{PAIR_LEDGER,1,0},{PAIR_SNAPSHOT,2,0},{PAIR_LEDGER,3,1},{PAIR_SNAPSHOT,4,1}};
  bool matched[2];
  ASSERT_EQ(ERR_OK,request_pair_file(ss,2,ls,2,events,4,matched).code);
  ASSERT_TRUE(matched[0]);
  ASSERT_FALSE(matched[1]);
}
TEST(pairing_exact_crosses_boundaries_in_both_orders) {
  PairSide s = snap("synthetic-turn", 100, 100, "same", 1000);
  PairSide l = ledger("synthetic-turn", 100, 100, "same", 1000, false);
  ASSERT_TRUE(pair_one(s, l, true, true));
  ASSERT_TRUE(pair_one(s, l, false, true));
  s.total.input = 400; s.total.output = 40;
  l.has_turn_total = true; l.turn_total = s.total;
  ASSERT_TRUE(pair_one(s, l, true, true));
  ASSERT_TRUE(pair_one(s, l, false, true));
  l.has_turn_total = false;
  ASSERT_FALSE(pair_one(s, l, true, true));
  s.has_total = false;
  ASSERT_TRUE(pair_one(s, l, true, true));
}
TEST(pairing_later_ledger_advance_blocks_near_and_restart_resets_it) {
  for (int restart = 0; restart < 2; restart++) {
    PairSide s = snap("synthetic-turn", 100, 900, "b", 1000);
    PairSide ls[2] = {ledger("synthetic-turn", 50, 50, "a", 0, false),
                     ledger("synthetic-turn", 100, 400, "c", 1300, false)};
    PairEvent events[] = {{PAIR_LEDGER,1,0}, {restart ? PAIR_RESTART : PAIR_BOUNDARY,2,0},
                          {PAIR_SNAPSHOT,3,0}, {PAIR_LEDGER,4,1}};
    bool matched;
    ASSERT_EQ(ERR_OK, request_pair_file(&s,1,ls,2,events,4,&matched).code);
    ASSERT_EQ(restart != 0, matched);
  }
}
TEST(pairing_restart_resets_snapshot_advance) {
  for (int restart = 0; restart < 2; restart++) {
    PairSide ss[2] = {snap("synthetic-turn",100,100,"a",0), snap("synthetic-turn",100,400,"c",1300)};
    PairSide l = ledger("synthetic-turn",100,7000,"b",1000,false);
    PairEvent events[] = {{PAIR_SNAPSHOT,1,0}, {restart ? PAIR_RESTART : PAIR_BOUNDARY,2,0},
                          {PAIR_LEDGER,3,0}, {PAIR_SNAPSHOT,4,1}};
    bool matched[2];
    ASSERT_EQ(ERR_OK, request_pair_file(ss,2,&l,1,events,4,matched).code);
    ASSERT_FALSE(matched[0]);
    ASSERT_EQ(restart != 0, matched[1]);
  }
}
TEST(pairing_replay_keeps_original_ledger_counter_history) {
  PairSide s = snap("synthetic-turn",100,900,"d",2000);
  PairSide ls[] = {ledger("synthetic-turn",50,50,"a",0,false),
                  ledger("synthetic-turn",50,5000,"b",500,true),
                  ledger("synthetic-turn",100,400,"e",2300,false)};
  PairEvent events[] = {{PAIR_LEDGER,1,0},{PAIR_LEDGER,2,1},{PAIR_BOUNDARY,3,0},
                        {PAIR_SNAPSHOT,4,0},{PAIR_LEDGER,5,2}};
  bool matched;
  ASSERT_EQ(ERR_OK, request_pair_file(&s,1,ls,3,events,5,&matched).code);
  ASSERT_FALSE(matched);
}
#define COUNT_LAST(ts, last) "{\"type\":\"event_msg\",\"timestamp\":\"2030-01-02T12:00:" ts "Z\",\"payload\":{\"type\":\"token_count\",\"info\":{\"last_token_usage\":" last "}}}"
TEST(compose_earlier_near_claim_suppresses_later_exact_candidate) {
  const char *lines[] = {META("synthetic-ledger", "synthetic-ledger"), STARTED("01", "synthetic-turn"),
      LEDGER("02", "synthetic-ledger", "", "\"response_id\":\"synthetic-r1\",", "\"turn_id\":\"synthetic-turn\",", USAGE(100,0,10), USAGE(100,0,10)),
      COUNT_LAST("03", USAGE(100,0,10)), COUNT_LAST("02", USAGE(100,0,10)), NULL};
  const char *const *files[] = {lines};
  LedgerFixture f; ledger_fixture(&f, files, 1, NULL);
  SessionModel *s = only_session(&f);
  ASSERT_EQ(1, s->unit_count);
  ASSERT_TRUE(str_equal(s->units[0].source, STR_LIT("record")));
  ASSERT_EQ(100, s->own_usage->input);
  ASSERT_EQ(0, s->own_usage->cached);
  ASSERT_EQ(10, s->own_usage->output);
  ledger_fixture_destroy(&f);
}
TEST(compose_owned_repeat_preserves_other_pending_response) {
  const char *lines[] = {META("synthetic-ledger", "synthetic-ledger"), STARTED("01", "synthetic-turn"),
      LEDGER("02", "synthetic-ledger", "", "\"response_id\":\"synthetic-r1\",", "\"turn_id\":\"synthetic-turn\",", USAGE(100,0,10), USAGE(100,0,10)),
      COUNT_LAST("03", USAGE(100,0,10)),
      LEDGER("04", "synthetic-ledger", "", "\"response_id\":\"synthetic-r2\",", "\"turn_id\":\"synthetic-turn\",", USAGE(100,0,10), USAGE(200,0,20)),
      COUNT_LAST("03", USAGE(100,0,10)), COUNT_LAST("05", USAGE(100,0,10)), NULL};
  const char *const *files[] = {lines};
  LedgerFixture f; ledger_fixture(&f,files,1,NULL);
  SessionModel *s = only_session(&f);
  ASSERT_EQ(2,s->unit_count);
  ASSERT_EQ(2,record_units(s));
  ASSERT_EQ(200,s->own_usage->input);
  ASSERT_EQ(0,s->own_usage->cached);
  ASSERT_EQ(20,s->own_usage->output);
  ledger_fixture_destroy(&f);
}
TEST(compose_counts_snapshot_only_request_in_ledgered_turn) {
  const char *lines[] = {META("synthetic-ledger", "synthetic-ledger"), STARTED("01", "synthetic-turn"),
      LEDGER("02", "synthetic-ledger", "", "\"response_id\":\"synthetic-r1\",", "\"turn_id\":\"synthetic-turn\",", USAGE(100, 40, 10), USAGE(100, 40, 10)),
      COUNT("03", USAGE(100, 40, 10), USAGE(100, 40, 10)),
      COUNT("09", USAGE(50, 0, 5), USAGE(150, 40, 15)), NULL};
  const char *const *files[] = {lines};
  LedgerFixture f; ledger_fixture(&f, files, 1, NULL);
  SessionModel *s = only_session(&f);
  ASSERT_EQ(2, s->unit_count);           /* the record, plus the snapshot-only request */
  ASSERT_EQ(150, s->own_usage->input);
  ASSERT_EQ(15, s->own_usage->output);
  ledger_fixture_destroy(&f);
}
TEST(compose_turn_context_breaks_adjacent_pair) {
  /* Thread total differs from the snapshot total, so only the near rule could pair them. */
  const char *paired[] = {META("synthetic-ledger", "synthetic-ledger"), STARTED("01", "synthetic-turn"),
      LEDGER("02", "synthetic-ledger", "", "\"response_id\":\"synthetic-r1\",", "\"turn_id\":\"synthetic-turn\",", USAGE(100, 0, 10), USAGE(7100, 0, 710)),
      COUNT("03", USAGE(100, 0, 10), USAGE(100, 0, 10)), NULL};
  const char *separated[] = {META("synthetic-ledger", "synthetic-ledger"), STARTED("01", "synthetic-turn"),
      LEDGER("02", "synthetic-ledger", "", "\"response_id\":\"synthetic-r1\",", "\"turn_id\":\"synthetic-turn\",", USAGE(100, 0, 10), USAGE(7100, 0, 710)),
      CONTEXT("02", "synthetic-turn"), COUNT("03", USAGE(100, 0, 10), USAGE(100, 0, 10)), NULL};
  const char *const *first[] = {paired}, *const *second[] = {separated};
  LedgerFixture f; ledger_fixture(&f, first, 1, NULL);
  ASSERT_EQ(1, only_session(&f)->unit_count);
  ledger_fixture_destroy(&f);
  ledger_fixture(&f, second, 1, NULL);
  ASSERT_EQ(2, only_session(&f)->unit_count);
  ledger_fixture_destroy(&f);
}
TEST(compose_mirror_in_one_copy_suppresses_other_copy_both_orders) {
  const char *with_record[] = {META("synthetic-ledger", "synthetic-ledger"), STARTED("01", "synthetic-turn"),
      LEDGER("02", "synthetic-ledger", "", "\"response_id\":\"synthetic-r1\",", "\"turn_id\":\"synthetic-turn\",", USAGE(100, 0, 10), USAGE(100, 0, 10)),
      COUNT("03", USAGE(100, 0, 10), USAGE(100, 0, 10)), NULL};
  const char *snapshot_only[] = {META("synthetic-ledger", "synthetic-ledger"), STARTED("01", "synthetic-turn"),
      COUNT("03", USAGE(100, 0, 10), USAGE(100, 0, 10)), NULL};
  const char *const *files[] = {with_record, snapshot_only};
  const long orders[2][2] = {{1700000000L, 1700000100L}, {1700000100L, 1700000000L}};
  for (size_t i = 0; i < 2; i++) {
    LedgerFixture f; ledger_fixture(&f, files, 2, orders[i]);
    SessionModel *s = only_session(&f);
    ASSERT_EQ(1, s->unit_count);
    ASSERT_TRUE(str_equal(s->units[0].source, STR_LIT("record")));
    ledger_fixture_destroy(&f);
  }
}
#define COUNT_TOTAL(ts, total) "{\"type\":\"event_msg\",\"timestamp\":\"2030-01-02T12:00:" ts "Z\",\"payload\":{\"type\":\"token_count\",\"info\":{\"total_token_usage\":" total "}}}"
TEST(compose_observation_key_suppresses_diverged_copy_snapshot) {
  /* Snapshots without last_token_usage. Copy A pairs its snapshot (total 100 at :03) with the record.
   * Copy B saw an extra snapshot first, so its :03 snapshot has delta 40, not 100: its snapshot key
   * differs, but its observation key (turn, no usage, total, timestamp) matches A's. Upstream drops it
   * (reconcileCodexRequestMirrors over requestMirrorKeys) and keeps B's unmatched first snapshot. */
  const char *paired[] = {META("synthetic-ledger", "synthetic-ledger"), STARTED("01", "synthetic-turn"),
      LEDGER("02", "synthetic-ledger", "", "\"response_id\":\"synthetic-r1\",", "\"turn_id\":\"synthetic-turn\",", USAGE(100, 0, 10), USAGE(100, 0, 10)),
      COUNT_TOTAL("03", USAGE(100, 0, 10)), NULL};
  const char *diverged[] = {META("synthetic-ledger", "synthetic-ledger"), STARTED("01", "synthetic-turn"),
      COUNT_TOTAL("02", USAGE(60, 0, 6)), COUNT_TOTAL("03", USAGE(100, 0, 10)), NULL};
  const char *const *files[] = {paired, diverged};
  const long orders[2][2] = {{1700000000L, 1700000100L}, {1700000100L, 1700000000L}};
  for (size_t i = 0; i < 2; i++) {
    LedgerFixture f; ledger_fixture(&f, files, 2, orders[i]);
    SessionModel *s = only_session(&f);
    ASSERT_EQ(2, s->unit_count);   /* the record, plus copy B's first snapshot */
    for (size_t u = 0; u < s->unit_count; u++) ASSERT_TRUE(s->units[u].input != 40);
    ledger_fixture_destroy(&f);
  }
}
TEST(compose_record_keys_suppress_same_time_snapshot_in_other_copy) {
  /* One copy has only the record; the other has only a snapshot carrying the record's exact key
   * (same turn, usage, thread total and timestamp text). Upstream's alias set drops that snapshot. */
  const char *record_only[] = {META("synthetic-ledger", "synthetic-ledger"), STARTED("01", "synthetic-turn"),
      LEDGER("02", "synthetic-ledger", "", "\"response_id\":\"synthetic-r1\",", "\"turn_id\":\"synthetic-turn\",", USAGE(100, 0, 10), USAGE(100, 0, 10)), NULL};
  const char *snapshot_only[] = {META("synthetic-ledger", "synthetic-ledger"), STARTED("01", "synthetic-turn"),
      COUNT("02", USAGE(100, 0, 10), USAGE(100, 0, 10)), NULL};
  const char *const *files[] = {record_only, snapshot_only};
  const long orders[2][2] = {{1700000000L, 1700000100L}, {1700000100L, 1700000000L}};
  for (size_t i = 0; i < 2; i++) {
    LedgerFixture f; ledger_fixture(&f, files, 2, orders[i]);
    SessionModel *s = only_session(&f);
    ASSERT_EQ(1, s->unit_count);
    ASSERT_TRUE(str_equal(s->units[0].source, STR_LIT("record")));
    ledger_fixture_destroy(&f);
  }
}
TEST(compose_replay_is_file_local_counting_is_session_wide) {
  const char *first[] = {META("synthetic-ledger","synthetic-ledger"), STARTED("01","synthetic-turn"),
      LEDGER("02","synthetic-ledger","","\"response_id\":\"synthetic-r1\",","\"turn_id\":\"synthetic-turn\",",USAGE(100,0,10),USAGE(7000,0,700)),
      COUNT("03",USAGE(100,0,10),USAGE(100,0,10)), NULL};
  const char *second[] = {META("synthetic-ledger","synthetic-ledger"), STARTED("01","synthetic-turn"),
      LEDGER("02","synthetic-ledger","","\"response_id\":\"synthetic-r1\",","\"turn_id\":\"synthetic-turn\",",USAGE(100,0,10),USAGE(7000,0,700)),
      COUNT("04",USAGE(100,0,10),USAGE(100,0,10)), NULL};
  const char *const *files[] = {first,second};
  const long orders[2][2] = {{1700000000L,1700000100L},{1700000100L,1700000000L}};
  for (size_t i=0;i<2;i++) {
    LedgerFixture f; ledger_fixture(&f,files,2,orders[i]);
    ASSERT_EQ(1,only_session(&f)->unit_count);
    ASSERT_EQ(100,only_session(&f)->own_usage->input);
    ledger_fixture_destroy(&f);
  }
}
