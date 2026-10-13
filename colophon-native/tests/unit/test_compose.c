#define _DARWIN_C_SOURCE
#include "cache/codec.h"
#include "corpus/subagents.h"
#include "parse/record.h"
#include "price/compose.h"
#include "runner.h"
#include "util/events.h"
#include <stdalign.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

TEST(compose_borrows_immutable_cached_stream_and_priority_until_destroy) {
  Intern intern;
  ASSERT_EQ(ERR_OK, intern_init(&intern).code);
  UsageRecord usage = {
      .line = 3,
      .response_id = {.kind = JS_STRING, .value.s = STR_LIT("synthetic-response")},
      .ts = {.kind = JS_STRING, .value.s = STR_LIT("2030-01-02T12:00:00Z")},
      .thread_usage = {.input = {.kind = JS_INT, .value.i = 7},
                       .output = {.kind = JS_INT, .value.i = 2}},
      .thread_id = {.kind = JS_STRING, .value.s = STR_LIT("synthetic")},
      .turn_id = {.kind = JS_STRING, .value.s = STR_LIT("synthetic-turn")},
      .input = {.kind = JS_INT, .value.i = 7},
      .output = {.kind = JS_INT, .value.i = 2}};
  TokenObservation context = {
      .tag = TOKEN_C,
      .line = 1,
      .model_state = {.kind = MODEL_SET, .model = STR_LIT("gpt-5")}};
  LogRecord raw = {
      .status = STR_LIT("ok"),
      .has_meta = true,
      .meta = {.id = STR_LIT("synthetic")},
      .key = {.path = STR_LIT("/synthetic/cache.jsonl")},
      .usage_records = &usage,
      .usage_count = 1,
      .token_stream = {.has_prepass = true,
                       .prepass = {.session_id = STR_LIT("synthetic")},
                       .observations = &context,
                       .count = 1}};
  unsigned char *bytes = NULL;
  size_t length;
  ASSERT_EQ(ERR_OK, codec_encode(&raw, &bytes, &length).code);
  LogRecord cached = {0};
  ASSERT_EQ(ERR_OK, codec_decode(bytes, length, &raw.key,
                                 raw.reader.tail_sha256, &intern, &cached)
                        .code);
  free(bytes);
  unsigned char *before = NULL, *after = NULL;
  size_t before_length, after_length;
  ASSERT_EQ(ERR_OK, codec_encode(&cached, &before, &before_length).code);
  AssemblyRecord input = assembly_record(&cached);
  Corpus corpus = {0};
  CodexMetadata metadata = {0};
  ASSERT_EQ(ERR_OK,
            corpus_build(&input, 1, &metadata, 0, &intern, &corpus).code);
  PriorityTurns priority = {0};
  PriorityEntry *entry = NULL;
  ASSERT_EQ(ERR_OK, arena_alloc(&priority.arena, sizeof *entry,
                                alignof(PriorityEntry), (void **)&entry)
                        .code);
  *entry = (PriorityEntry){.thread_id = STR_LIT("synthetic"),
                           .model = STR_LIT("gpt-5"),
                           .first_seen_ms = 1};
  ASSERT_EQ(ERR_OK,
            omap_put(&priority.turns, STR_LIT("synthetic-turn"), entry).code);
  ASSERT_EQ(ERR_OK, compose_usage(&corpus, &priority).code);
  SessionModel *s = corpus.sessions.first->value;
  ASSERT_EQ(1, s->unit_count);
  ASSERT_EQ(7, s->units[0].input);
  ASSERT_TRUE(s->units[0].priority == entry);
  ASSERT_TRUE(str_equal(s->units[0].model_raw, STR_LIT("gpt-5")));
  ASSERT_TRUE(s->units[0].model_raw.p ==
              cached.token_stream.observations[0].model_state.model.p);
  ASSERT_EQ(0, (uintptr_t)s->units % alignof(UsageUnit));
  ASSERT_EQ(0, (uintptr_t)s->own_usage % alignof(UsageSummary));
  ASSERT_EQ(0, (uintptr_t)s->buckets % alignof(UsageBucket));
  ASSERT_EQ(7, s->own_usage->input);
  ASSERT_EQ(ERR_OK, compose_usage(&corpus, &priority).code);
  ASSERT_EQ(1, s->unit_count);
  ASSERT_EQ(7, s->units[0].input);
  ASSERT_TRUE(s->units[0].priority == entry);
  ASSERT_TRUE(str_equal(s->units[0].model_raw, STR_LIT("gpt-5")));
  ASSERT_TRUE(s->units[0].model_raw.p ==
              cached.token_stream.observations[0].model_state.model.p);
  ASSERT_EQ(ERR_OK, codec_encode(&cached, &after, &after_length).code);
  ASSERT_EQ(before_length, after_length);
  ASSERT_EQ(0, memcmp(before, after, before_length));
  free(before);
  free(after);
  corpus_destroy(&corpus);
  priority_destroy(&priority);
  record_destroy(&cached);
  intern_destroy(&intern);
}

TEST(compose_unit_alignment_for_different_identifier_lengths) {
  for (size_t length = 1; length <= 32; length++) {
    char identifier[33];
    memset(identifier, 's', length);
    identifier[length] = 0;
    Str id = {identifier, (uint32_t)length};
    UsageRecord usage = {.line = 1,
                         .response_id = {.kind = JS_STRING, .value.s = STR_LIT("synthetic-response")},
                         .ts = {.kind = JS_STRING, .value.s = STR_LIT("2030-01-02T12:00:00Z")},
                         .thread_usage = {.input = {.kind = JS_INT, .value.i = 1},
                                          .output = {.kind = JS_INT, .value.i = 0}},
                         .output = {.kind = JS_INT, .value.i = 0},
                         .thread_id = {.kind = JS_STRING, .value.s = id},
                         .input = {.kind = JS_INT, .value.i = 1}};
    LogRecord raw = {
        .key = {.path = STR_LIT("/synthetic/alignment")},
        .usage_records = &usage,
        .usage_count = 1,
        .token_stream = {.has_prepass = true, .prepass = {.session_id = id}}};
    const LogRecord *records[] = {&raw};
    SessionModel session = {.id = id, .records = records, .record_count = 1};
    Corpus corpus = {0};
    PriorityTurns priority = {0};
    ASSERT_EQ(ERR_OK, omap_put(&corpus.sessions, id, &session).code);
    ASSERT_EQ(ERR_OK, compose_usage(&corpus, &priority).code);
    ASSERT_EQ(1, session.unit_count);
    ASSERT_EQ(0, (uintptr_t)session.units % alignof(UsageUnit));
    corpus_destroy(&corpus);
    priority_destroy(&priority);
  }
}

TEST(independent_session_meta_clock_feeds_linker) {
  JScalar values[] = {
      {.kind = JS_INT, .value.i = 123},
      {.kind = JS_FLOAT, .value.f = 123.5},
      {.kind = JS_NULL},
      {.kind = JS_STRING, .value.s = STR_LIT("synthetic invalid clock")}};
  for (size_t i = 0; i < sizeof values / sizeof *values; i++) {
    LogRecord record = {0};
    AssemblyRecord selected = {.record = &record,
                               .typed_clocks = true,
                               .creation = {.kind = JS_INT, .value.i = 456}};
    SessionModel session = {.id = STR_LIT("synthetic"),
                            .record = &record,
                            .input = &selected,
                            .meta_input = {.record = &record,
                                           .typed_clocks = true,
                                           .creation = values[i]}};
    Corpus corpus = {0};
    CodexMetadata metadata = {0};
    ASSERT_EQ(ERR_OK, omap_put(&corpus.sessions, session.id, &session).code);
    ASSERT_EQ(ERR_OK, corpus_link_subagents(&corpus, &metadata, 0).code);
    ASSERT_EQ(i < 2, session.created_at_ms.present);
    if (i == 0) {
      ASSERT_FALSE(session.created_at_ms.value.is_float);
      ASSERT_EQ(123, session.created_at_ms.value.i);
    }
    if (i == 1) {
      ASSERT_TRUE(session.created_at_ms.value.is_float);
      ASSERT_TRUE(session.created_at_ms.value.f == 123.5);
    }
    corpus_destroy(&corpus);
  }
}

/* Authored Session facts may differ from the selected grouping record. */
static void independent_link(bool independent_subagent, bool record_subagent,
                             JScalar parent_id, JScalar child_id,
                             bool has_meta, bool linked) {
  Intern intern;
  ASSERT_EQ(ERR_OK, intern_init(&intern).code);
  LogRecord records[2] = {
      {.status = STR_LIT("ok"), .has_meta = true,
       .key = {.path = STR_LIT("/synthetic/parent.jsonl")},
       .meta = {.id = STR_LIT("selected-parent")}},
      {.status = STR_LIT("ok"), .has_meta = true,
       .key = {.path = STR_LIT("/synthetic/child.jsonl")},
       .meta = {.id = STR_LIT("selected-child"),
                .is_subagent = record_subagent}}};
  ActivityLink activity = {.kind = STR_LIT("started"),
                           .child_id = STR_LIT("selected-child"),
                           .turn_key = STR_LIT("synthetic-spawn-turn")};
  records[0].activities = &activity;
  records[0].activity_count = 1;
  unsigned char *before[2] = {0}, *after[2] = {0};
  size_t before_n[2], after_n[2];
  AssemblyRecord input[2];
  for (size_t i = 0; i < 2; i++) {
    ASSERT_EQ(ERR_OK, codec_encode(&records[i], &before[i], &before_n[i]).code);
    input[i] = assembly_record(&records[i]);
  }
  Corpus corpus = {0};
  CodexMetadata metadata = {0};
  ASSERT_EQ(ERR_OK, corpus_build(input, 2, &metadata, 0, &intern, &corpus).code);
  SessionModel *parent = omap_get(&corpus.sessions, STR_LIT("selected-parent"));
  SessionModel *child = omap_get(&corpus.sessions, STR_LIT("selected-child"));
  ASSERT_TRUE(parent && child);
  TurnModel parent_turn = {.id = STR_LIT("synthetic-spawn-turn")};
  parent->turns = &parent_turn;
  parent->turn_count = 1;
  parent->meta_input.meta_id = parent_id;
  parent->meta.id = parent_id.kind == JS_STRING ? parent_id.value.s : (Str){0};
  child->meta_input.meta_id = child_id;
  child->meta.id = child_id.kind == JS_STRING ? child_id.value.s : (Str){0};
  child->has_meta = has_meta;
  child->is_subagent = independent_subagent;
  child->meta.parent_thread_id = (JScalar){.kind = JS_STRING,
                                          .value.s = STR_LIT("selected-parent")};
  child->meta.forked_from_id = parent_id.value.s;
  if (!has_meta) {
    child->meta = (SessionMeta){0};
    child->meta_input = (AssemblyRecord){0};
  }
  Str edge = parent_id.value.s;
  if (child_id.kind == JS_STRING)
    ASSERT_EQ(ERR_OK, omap_put(&metadata.spawn_parents, child_id.value.s, &edge).code);
  ASSERT_EQ(ERR_OK, corpus_link_subagents(&corpus, &metadata, 0).code);
  ASSERT_TRUE(str_equal(child->kind, independent_subagent
      ? (linked ? STR_LIT("subagent") : STR_LIT("orphan")) : STR_LIT("session")));
  ASSERT_EQ(independent_subagent, child->has_link);
  ASSERT_EQ(independent_subagent && !linked, !!(child->flags & F_ORPHAN));
  ASSERT_EQ(independent_subagent && !linked, corpus.orphaned_subagents.count);
  ASSERT_EQ(independent_subagent && linked, parent->children.count);
  ASSERT_EQ(independent_subagent && linked, parent_turn.spawned.count);
  ASSERT_TRUE(str_equal(child->spawn_turn, independent_subagent && linked
      ? STR_LIT("synthetic-spawn-turn") : (Str){0}));
  ASSERT_TRUE(str_equal(child->link_method, independent_subagent && linked
      ? STR_LIT("activity") : (Str){0}));
  ASSERT_EQ(independent_subagent && has_meta, !!(child->flags & F_FORKED));
  ASSERT_EQ(!independent_subagent, child->forked_from.p != NULL);
  ASSERT_TRUE(str_equal(child->identity, STR_LIT("selected-child")));
  ASSERT_TRUE(str_equal(parent->identity, STR_LIT("selected-parent")));
  if (independent_subagent && has_meta)
    ASSERT_TRUE(str_equal(child->parent_id, parent_id.value.s));
  else
    ASSERT_FALSE(child->parent_id.p);
  for (size_t i = 0; i < 2; i++) {
    ASSERT_EQ(ERR_OK, codec_encode(&records[i], &after[i], &after_n[i]).code);
    ASSERT_EQ(before_n[i], after_n[i]);
    ASSERT_EQ(0, memcmp(before[i], after[i], before_n[i]));
    free(before[i]); free(after[i]);
  }
  omap_destroy(&metadata.spawn_parents);
  corpus_destroy(&corpus);
  intern_destroy(&intern);
}
#define STRING_ID(literal) ((JScalar){.kind = JS_STRING, .value.s = STR_LIT(literal)})
TEST(linker_independent_subagent_true_selected_false) {
  independent_link(true, false, STRING_ID("selected-parent"),
                   STRING_ID("selected-child"), true, true);
}
TEST(linker_independent_subagent_false_selected_true) {
  independent_link(false, true, STRING_ID("selected-parent"),
                   STRING_ID("selected-child"), true, false);
}
TEST(linker_independent_raw_ids_replace_grouping_ids) {
  independent_link(true, true, STRING_ID("  independent-parent  "),
                   STRING_ID("independent-child"), true, true);
}
TEST(linker_independent_missing_invalid_or_blank_id_is_orphan) {
  JScalar ids[] = {{.kind = JS_NULL}, {.kind = JS_BOOL, .value.b = true},
                  STRING_ID(""), STRING_ID("\x1c\xc2\xa0")};
  for (size_t i = 0; i < sizeof ids / sizeof *ids; i++)
    independent_link(true, true, STRING_ID("selected-parent"), ids[i], true, false);
  independent_link(true, true, STRING_ID("selected-parent"),
                   STRING_ID("selected-child"), false, false);
}
TEST(linker_independent_raw_nfc_distinct_ids_are_preserved) {
  independent_link(true, true, STRING_ID("synthetic-cafe\xcc\x81"),
                   STRING_ID("synthetic-caf\xc3\xa9"), true, true);
}
TEST(linker_canonical_producer_initialized_control) {
  independent_link(true, true, STRING_ID("selected-parent"),
                   STRING_ID("selected-child"), true, true);
}
