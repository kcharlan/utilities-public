#include "claude/compose.h"
#include "runner.h"
#include <stdio.h>
#include <stdlib.h>
static void line(ClaudeRecord *r, const char *s) {
  ReaderRawLine raw = {.bytes = {s, (uint32_t)strlen(s)}, .terminated = true};
  ASSERT_EQ(ERR_OK, claude_usage_line(r, &raw, STR_LIT("synthetic-turn")).code);
}
#define ROW_PREFIX                                                             \
  "{\"type\":\"assistant\",\"timestamp\":\"2001-01-01T00:00:00Z\","            \
  "\"sessionId\":\"synthetic-session\",\"requestId\":\"synthetic-request\","   \
  "\"message\":{\"id\":\"synthetic-message\",\"model\":\"synthetic-model\","
static void composed(ClaudeRecord *records, size_t n, ClaudeScan *scan,
                     Corpus *c) {
  *scan = (ClaudeScan){.records = records, .count = n};
  CorpusStrings collisions = {0};
  ASSERT_EQ(ERR_OK, claude_corpus_add(records, n, 0, c, &collisions).code);
  PriorityTurns priority = {0};
  ASSERT_EQ(ERR_OK, compose_usage(c, &priority).code);
  for (OmapEntry *p = c->sessions.first; p; p = p->next)
    if (((SessionModel *)p->value)->provider == PROVIDER_CLAUDE)
      ASSERT_TRUE(((SessionModel *)p->value)->own_usage == NULL);
  ASSERT_EQ(ERR_OK, claude_compose(scan, c).code);
}
TEST(claude_usage_extraction_mapping_and_original_line_gate) {
  ClaudeRecord r = {.id = STR_LIT("synthetic-session")};
  line(&r, ROW_PREFIX
       "\"usage\":{\"input_tokens\":17,\"cache_read_input_tokens\":13,\"cache_"
       "creation_input_tokens\":11,\"output_tokens\":7,\"cache_creation\":{"
       "\"ephemeral_1h_input_tokens\":99},\"speed\":\"fast\",\"output_tokens_"
       "details\":{\"thinking_tokens\":3}}}}");
  ASSERT_EQ(1, r.usage_count);
  ASSERT_EQ(0, (uintptr_t)r.usage_rows % _Alignof(ClaudeUsageRow));
  const UsageUnit *u = &r.usage_rows[0].unit;
  ASSERT_EQ(41, u->input);
  ASSERT_EQ(13, u->cached);
  ASSERT_EQ(11, u->cache_write);
  ASSERT_EQ(11, u->cache_write_1h);
  ASSERT_EQ(7, u->output);
  ASSERT_EQ(3, u->reasoning.value);
  ASSERT_TRUE(u->reasoning.present);
  ASSERT_TRUE(u->fast);
  line(&r, "{\"type\": \"assistant\",\"usage\":{}}");
  line(&r, "synthetic-prefix " ROW_PREFIX "\"usage\":{\"input_tokens\":1}}}");
  line(&r,
       ROW_PREFIX "\"usage\":{\"input_tokens\":-2,\"output_tokens\":false}}}");
  ASSERT_EQ(1, r.usage_count);
  ASSERT_EQ(1, *(uint64_t *)omap_get(&r.rows_dropped, STR_LIT("line_filter")));
  ASSERT_EQ(1, *(uint64_t *)omap_get(&r.rows_dropped, STR_LIT("invalid_json")));
  ASSERT_EQ(1, *(uint64_t *)omap_get(&r.rows_dropped, STR_LIT("zero_usage")));
  char *large = malloc(512 * 1024 + 2);
  ASSERT_TRUE(large);
  memset(large, 'x', 512 * 1024 + 1);
  ReaderRawLine raw = {.bytes = {large, 512 * 1024 + 1}, .terminated = true};
  ASSERT_EQ(ERR_OK, claude_usage_line(&r, &raw, (Str){0}).code);
  free(large);
  ASSERT_EQ(1, *(uint64_t *)omap_get(&r.rows_dropped, STR_LIT("line_cap")));
  claude_record_destroy(&r);
}
TEST(claude_usage_vertex_filter_and_drop_reasons) {
  ClaudeRecord r = {0};
  line(&r, ROW_PREFIX "\"usage\":{\"input_tokens\":1},\"metadata\":{"
                      "\"provider\":\"Vertex AI\"}}}");
  line(&r, "{\"type\":\"assistant\",\"timestamp\":\"2001-01-01T00:00:00Z\","
           "\"message\":{\"model\":\"claude-synthetic@1\",\"usage\":{\"input_"
           "tokens\":1}}}");
  line(&r, ROW_PREFIX
       "\"usage\":{\"input_tokens\":1}},\"requestId\":\"req_vrtx_synthetic\"}");
  ASSERT_EQ(0, r.usage_count);
  ASSERT_TRUE(omap_get(&r.rows_dropped, STR_LIT("vertex_ai")));
  ASSERT_EQ(3, *(uint64_t *)omap_get(&r.rows_dropped, STR_LIT("vertex_ai")));
  line(&r, "{\"type\":\"assistant\",\"usage\":{}}");
  line(&r, "{\"type\":\"assistant\",\"timestamp\":\"2001-01-01T00:00:00Z\","
           "\"usage\":{}}");
  line(&r, "{\"type\":\"assistant\",\"timestamp\":\"2001-01-01T00:00:00Z\","
           "\"message\":{},\"usage\":{}}");
  line(&r, ROW_PREFIX "\"usage\":null}}");
  ASSERT_EQ(1, *(uint64_t *)omap_get(&r.rows_dropped, STR_LIT("timestamp")));
  ASSERT_EQ(1, *(uint64_t *)omap_get(&r.rows_dropped, STR_LIT("message")));
  ASSERT_EQ(1, *(uint64_t *)omap_get(&r.rows_dropped, STR_LIT("model")));
  ASSERT_EQ(1, *(uint64_t *)omap_get(&r.rows_dropped, STR_LIT("usage")));
  claude_record_destroy(&r);
}
TEST(claude_usage_local_replacement_then_copy_winners_incomplete_and_advisor) {
  ClaudeRecord r[2] = {{.id = STR_LIT("synthetic-session"),
                        .key = {.path = STR_LIT("/synthetic/a.jsonl")}},
                       {.id = STR_LIT("synthetic-other"),
                        .key = {.path = STR_LIT("/synthetic/b.jsonl")}}};
  line(&r[0],
       ROW_PREFIX "\"stop_reason\":null,\"usage\":{\"input_tokens\":99}}}");
  line(&r[0], ROW_PREFIX
       "\"usage\":{\"input_tokens\":2,\"output_tokens\":3,\"iterations\":[{"
       "\"type\":\"advisor_message\",\"model\":\"synthetic-advisor\",\"input_"
       "tokens\":5,\"output_tokens\":7}]}}}");
  line(&r[0],
       ROW_PREFIX "\"stop_reason\":null,\"usage\":{\"input_tokens\":100}}}");
  line(&r[1], ROW_PREFIX
       "\"usage\":{\"input_tokens\":200,\"output_tokens\":300,\"iterations\":[{"
       "\"type\":\"advisor_message\",\"model\":\"synthetic-advisor\",\"input_"
       "tokens\":500,\"output_tokens\":700}]}}}");
  line(&r[1], "{\"type\":\"assistant\",\"timestamp\":\"2001-01-01T00:00:00Z\","
              "\"message\":{\"model\":\"synthetic-model\",\"stop_reason\":null,"
              "\"usage\":{\"input_tokens\":11}}}");
  Corpus c = {0};
  ClaudeScan scan;
  composed(r, 2, &scan, &c);
  SessionModel *s = omap_get(&c.sessions, r[0].id),
               *other = omap_get(&c.sessions, r[1].id);
  ASSERT_EQ(2, s->unit_count);
  ASSERT_EQ(7, s->own_usage->input);
  ASSERT_EQ(10, s->own_usage->output);
  ASSERT_EQ(0, (uintptr_t)s->units % _Alignof(UsageUnit));
  ASSERT_EQ(0, other->unit_count);
  ASSERT_EQ(1, scan.incomplete_requests);
  ASSERT_EQ(2, scan.duplicate_keys);
  ASSERT_EQ(4, scan.duplicate_rows);
  corpus_destroy(&c);
  for (size_t i = 0; i < 2; i++)
    claude_record_destroy(&r[i]);
}
TEST(claude_usage_session_fallback_unkeyed_and_advisor_ids) {
  ClaudeRecord r = {.id = STR_LIT("synthetic-session"),
                    .key = {.path = STR_LIT("/synthetic/c.jsonl")}};
  const char *keyed = "{\"type\":\"assistant\",\"timestamp\":\"2001-01-01T00:"
                      "00:00Z\",\"session_id\":\"synthetic-alias\",\"message\":"
                      "{\"id\":\"synthetic-fallback\",\"model\":\"synthetic-"
                      "model\",\"usage\":{\"input_tokens\":2}}}";
  line(&r, keyed);
  line(&r, keyed);
  const char *unkeyed =
      "{\"type\":\"assistant\",\"timestamp\":\"2001-01-01T00:00:00Z\","
      "\"message\":{\"model\":\"synthetic-model\",\"usage\":{\"input_tokens\":"
      "3,\"iterations\":[{\"type\":\"other\",\"model\":\"ignored\",\"input_"
      "tokens\":0,\"output_tokens\":0},{\"type\":\"advisor_message\",\"model\":"
      "\"\",\"input_tokens\":0,\"output_tokens\":0},{\"type\":\"advisor_"
      "message\",\"model\":\"synthetic-advisor\",\"input_tokens\":0,\"output_"
      "tokens\":5}]}}}";
  line(&r, unkeyed);
  line(&r, unkeyed);
  ASSERT_EQ(6, r.usage_count);
  ASSERT_FALSE(r.usage_rows[3].message_id.p);
  Corpus c = {0};
  ClaudeScan scan;
  composed(&r, 1, &scan, &c);
  SessionModel *s = omap_get(&c.sessions, r.id);
  ASSERT_EQ(5, s->unit_count);
  ASSERT_EQ(8, s->own_usage->input);
  ASSERT_EQ(10, s->own_usage->output);
  ASSERT_EQ(1, scan.duplicate_keys);
  ASSERT_EQ(1, scan.duplicate_rows);
  corpus_destroy(&c);
  claude_record_destroy(&r);
}
TEST(claude_usage_winner_precedence_and_complete_cumulative_chunks) {
  for (size_t mode = 0; mode < 5; mode++) {
    ClaudeRecord r[2] = {{.id = STR_LIT("synthetic-a"),
                          .key = {.path = STR_LIT("/synthetic/a.jsonl")}},
                         {.id = STR_LIT("synthetic-b"),
                          .key = {.path = STR_LIT("/synthetic/b.jsonl")}}};
    if (mode == 2)
      r[0].key.path = STR_LIT("/synthetic/a/subagents/agent-synthetic.jsonl");
    line(&r[0], mode == 0 ? ROW_PREFIX
                    "\"stop_reason\":null,\"usage\":{\"input_tokens\":99}}}"
                : mode == 1 ? ROW_PREFIX
                    "\"usage\":{\"input_tokens\":99}},\"isSidechain\":true}"
                            : ROW_PREFIX "\"usage\":{\"input_tokens\":99}}}");
    line(&r[1], ROW_PREFIX "\"usage\":{\"input_tokens\":2}}}");
    if (mode == 3) {
      r[0].key.path = STR_LIT("/synthetic/z.jsonl");
      r[1].key.path = STR_LIT("/synthetic/a.jsonl");
    }
    if (mode == 4) {
      r[0].key.path = STR_LIT("/synthetic/e\xcc\x81.jsonl");
      r[1].key.path = STR_LIT("/synthetic/z.jsonl");
    }
    Corpus c = {0};
    ClaudeScan scan;
    composed(r, 2, &scan, &c);
    ASSERT_EQ(0, ((SessionModel *)omap_get(&c.sessions, r[0].id))->unit_count);
    ASSERT_EQ(
        2, ((SessionModel *)omap_get(&c.sessions, r[1].id))->own_usage->input);
    ASSERT_EQ(0, scan.incomplete_requests);
    corpus_destroy(&c);
    for (size_t i = 0; i < 2; i++)
      claude_record_destroy(&r[i]);
  }
  ClaudeRecord r = {.id = STR_LIT("synthetic-cumulative")};
  line(&r, ROW_PREFIX "\"usage\":{\"input_tokens\":99}}}");
  line(&r, ROW_PREFIX "\"usage\":{\"input_tokens\":2}}}");
  Corpus c = {0};
  ClaudeScan scan;
  composed(&r, 1, &scan, &c);
  ASSERT_EQ(2, ((SessionModel *)omap_get(&c.sessions, r.id))->own_usage->input);
  corpus_destroy(&c);
  claude_record_destroy(&r);
}
TEST(claude_usage_zero_parent_keeps_keyed_and_unkeyed_advisors) {
  ClaudeRecord r = {.id = STR_LIT("synthetic-zero-parent")};
  const char *keyed = ROW_PREFIX
      "\"usage\":{\"input_tokens\":0,\"output_tokens\":0,\"iterations\":[{"
      "\"type\":\"advisor_message\",\"model\":\"synthetic-advisor\",\"input_"
      "tokens\":3,\"output_tokens\":5}]}}}";
  const char *unkeyed =
      "{\"type\":\"assistant\",\"timestamp\":\"2001-01-01T00:00:00Z\","
      "\"message\":{\"model\":\"synthetic-model\",\"usage\":{\"input_tokens\":"
      "0,\"output_tokens\":0,\"iterations\":[{\"type\":\"advisor_message\","
      "\"model\":\"synthetic-advisor\",\"input_tokens\":7,\"output_tokens\":11}"
      "]}}}";
  line(&r, keyed);
  line(&r, keyed);
  line(&r, unkeyed);
  line(&r, unkeyed);
  ASSERT_EQ(4, r.usage_count);
  ASSERT_TRUE(str_equal(r.usage_rows[0].message_id,
                        STR_LIT("synthetic-message:advisor:0")));
  Corpus c = {0};
  ClaudeScan scan;
  composed(&r, 1, &scan, &c);
  SessionModel *s = omap_get(&c.sessions, r.id);
  ASSERT_EQ(3, s->unit_count);
  ASSERT_EQ(17, s->own_usage->input);
  ASSERT_EQ(27, s->own_usage->output);
  ASSERT_EQ(1, scan.duplicate_keys);
  ASSERT_EQ(1, scan.duplicate_rows);
  ASSERT_EQ(4, *(uint64_t *)omap_get(&r.rows_dropped, STR_LIT("zero_usage")));
  corpus_destroy(&c);
  claude_record_destroy(&r);
}
TEST(claude_usage_vector_alignment_at_every_arena_offset) {
  for (size_t offset = 0; offset < 32; offset++) {
    ClaudeRecord r = {.id = STR_LIT("synthetic-alignment")};
    void *padding;
    ASSERT_EQ(ERR_OK, arena_alloc(&r.arena, offset, 1, &padding).code);
    line(&r, ROW_PREFIX "\"usage\":{\"input_tokens\":1}}}");
    ASSERT_EQ(0, (uintptr_t)r.usage_rows % _Alignof(ClaudeUsageRow));
    Corpus c = {0};
    ClaudeScan scan;
    composed(&r, 1, &scan, &c);
    ASSERT_EQ(0,
              (uintptr_t)((SessionModel *)omap_get(&c.sessions, r.id))->units %
                  _Alignof(UsageUnit));
    corpus_destroy(&c);
    claude_record_destroy(&r);
  }
}
TEST(claude_usage_numbers_vertex_case_and_json_serialization_boundary) {
  ClaudeRecord r = {0};
  line(&r, ROW_PREFIX "\"usage\":{\"input_tokens\":true,\"output_tokens\":3.9},"
                      "\"metadata\":{\"provider\":\"VERTEX\"}}}");
  ASSERT_EQ(0, r.usage_count);
  line(&r, ROW_PREFIX "\"usage\":{\"input_tokens\":true,\"output_tokens\":3.9}}"
                      ",\"isSidechain\":0.5}");
  ASSERT_EQ(1, r.usage_count);
  ASSERT_EQ(1, r.usage_rows[0].unit.input);
  ASSERT_EQ(3, r.usage_rows[0].unit.output);
  ASSERT_TRUE(r.usage_rows[0].sidechain);
  line(&r, ROW_PREFIX "\"usage\":{\"input_tokens\":3,\"output_tokens\":NaN}}}");
  ASSERT_EQ(1, r.usage_count);
  line(&r, ROW_PREFIX "\"usage\":{\"input_tokens\":18446744073709551615,"
                      "\"output_tokens\":1}}}");
  ASSERT_EQ(2, r.usage_count);
  ASSERT_EQ(0, r.usage_rows[1].unit.input);
  claude_record_destroy(&r);
}
TEST(claude_usage_incomplete_predicate_and_key_identity_branches) {
  ClaudeRecord r = {.id = STR_LIT("synthetic-key-branches")};
  line(&r, ROW_PREFIX
       "\"usage\":{\"input_tokens\":2}}}"); /* Missing stop is complete. */
  line(&r, ROW_PREFIX "\"stop_reason\":null,\"usage\":{\"input_tokens\":3,"
                      "\"cache_read_input_tokens\":null}}}");
  ASSERT_FALSE(r.usage_rows[0].incomplete);
  ASSERT_FALSE(r.usage_rows[1].incomplete);
  const char *empty =
      "{\"type\":\"assistant\",\"timestamp\":\"2001-01-01T00:00:00Z\","
      "\"requestId\":\"\",\"message\":{\"id\":\"\",\"model\":\"synthetic-"
      "model\",\"usage\":{\"input_tokens\":5}}}";
  line(&r, empty);
  line(&r, empty);
  const char *blank = "{\"type\":\"assistant\",\"timestamp\":\"2001-01-01T00:"
                      "00:00Z\",\"sessionId\":\" "
                      "\",\"message\":{\"id\":\"synthetic-message\",\"model\":"
                      "\"synthetic-model\",\"usage\":{\"input_tokens\":7}}}";
  line(&r, blank);
  line(&r, blank);
  Corpus c = {0};
  ClaudeScan scan;
  composed(&r, 1, &scan, &c);
  SessionModel *s = omap_get(&c.sessions, r.id);
  ASSERT_EQ(4, s->unit_count);
  ASSERT_EQ(22, s->own_usage->input);
  ASSERT_EQ(2, scan.duplicate_keys);
  ASSERT_EQ(2, scan.duplicate_rows);
  corpus_destroy(&c);
  claude_record_destroy(&r);
}
TEST(claude_usage_historical_foundation_timestamp_and_marker_boundaries) {
  const struct {
    const char *timestamp;
    int64_t ms;
    bool valid;
  } cases[] = {{"2001-01-01T00:00:00.123456789Z", 978307200123, true},
               {"2001-01-01T00:00:00.123456789012Z", 978307199999, true},
               {"2001-01-01T00:00:00+0000", 978307200000, true},
               {"2001-01-01T00:00:00+00", 978307200000, true},
               {"1899-01-01T00:00:00.9999Z", -2240524799001, true},
               {"2001-02-30T00:00:00Z", 983491200000, true},
               {"2001-01-01T24:00:00Z", 978393600000, true},
               {"2001-01-01T00:00:00Zsynthetic-tail", 978307200000, true},
               {"2001-01-01t00:00:00Z", 0, false},
               {"2001-01-01T00:00:60Z", 0, false}};
  for (size_t i = 0; i < sizeof cases / sizeof *cases; i++) {
    char bytes[512];
    snprintf(bytes, sizeof bytes,
             "{\"type\":\"assistant\",\"timestamp\":\"%s\",\"message\":{"
             "\"model\":\"synthetic-model\",\"usage\":{\"input_tokens\":1}}}",
             cases[i].timestamp);
    ClaudeRecord r = {0};
    line(&r, bytes);
    ASSERT_EQ(cases[i].valid ? 1 : 0, r.usage_count);
    if (cases[i].valid)
      ASSERT_EQ(cases[i].ms, r.usage_rows[0].unit.at_ms.value);
    claude_record_destroy(&r);
  }
  ClaudeRecord r = {0};
  line(&r, ROW_PREFIX "\"usage\":{\"input_tokens\":1},\"metadata\":{"
                      "\"provider\":\"vertex\\u0301\"}}}");
  ASSERT_EQ(1,
            r.usage_count); /* Swift substring matching respects graphemes. */
  claude_record_destroy(&r);
}
TEST(claude_usage_accounting_keys_use_swift_canonical_equivalence) {
  ClaudeRecord r = {.id = STR_LIT("synthetic-exact-owner")};
  const char *composed_row =
      "{\"type\":\"assistant\",\"timestamp\":\"2001-01-01T00:00:00Z\","
      "\"requestId\":\"synthetic-réquest\",\"message\":{\"id\":\"synthetic-"
      "méssage\",\"model\":\"synthetic-model\",\"usage\":{\"input_tokens\":3}}"
      "}";
  const char *decomposed =
      "{\"type\":\"assistant\",\"timestamp\":\"2001-01-01T00:00:00Z\","
      "\"requestId\":\"synthetic-re\\u0301quest\",\"message\":{\"id\":"
      "\"synthetic-me\\u0301ssage\",\"model\":\"synthetic-model\",\"usage\":{"
      "\"input_tokens\":5}}}";
  const char *session_composed =
      "{\"type\":\"assistant\",\"timestamp\":\"2001-01-01T00:00:00Z\","
      "\"sessionId\":\"synthetic-séssion\",\"message\":{\"id\":\"synthetic-"
      "fallback\",\"model\":\"synthetic-model\",\"usage\":{\"input_tokens\":7}}"
      "}";
  const char *session_decomposed =
      "{\"type\":\"assistant\",\"timestamp\":\"2001-01-01T00:00:00Z\","
      "\"sessionId\":\"synthetic-se\\u0301ssion\",\"message\":{\"id\":"
      "\"synthetic-fallback\",\"model\":\"synthetic-model\",\"usage\":{\"input_"
      "tokens\":11}}}";
  line(&r, composed_row);
  line(&r, decomposed);
  line(&r, session_composed);
  line(&r, session_decomposed);
  ASSERT_FALSE(
      str_equal(r.usage_rows[0].message_id, r.usage_rows[1].message_id));
  ASSERT_FALSE(
      str_equal(r.usage_rows[2].session_id, r.usage_rows[3].session_id));
  Corpus c = {0};
  ClaudeScan scan;
  composed(&r, 1, &scan, &c);
  SessionModel *s = omap_get(&c.sessions, r.id);
  ASSERT_EQ(2, s->unit_count);
  ASSERT_EQ(16, s->own_usage->input);
  ASSERT_EQ(2, scan.duplicate_keys);
  ASSERT_EQ(2, scan.duplicate_rows);
  ASSERT_TRUE(
      str_equal(r.usage_rows[0].message_id, STR_LIT("synthetic-méssage")));
  corpus_destroy(&c);
  claude_record_destroy(&r);
}
TEST(claude_usage_foundation_large_integer_decimal_rounding_and_rejection) {
  const struct {
    const char *n;
    int64_t expected;
    bool valid;
  } cases[] = {{"18446744073709551617", 1, true},
               {"3.9999999999999999999999999999999999999999", 0, true},
               {"9223372036854775806.9", 0, true},
               {"-9223372036854775809", INT64_MAX, true},
               {"12345678901234567890123456789012345678901234567890", 0, true},
               {"-12345678901234567890123456789012345678901234567890",
                INT64_C(520181603164944384), true},
               {"1e30", INT64_MAX, true},
               {"1e400", 0, false},
               {"1e-400", 0, true}};
  for (size_t i = 0; i < sizeof cases / sizeof *cases; i++) {
    char bytes[512];
    snprintf(bytes, sizeof bytes,
             "{\"type\":\"assistant\",\"timestamp\":\"2001-01-01T00:00:00Z\","
             "\"message\":{\"model\":\"synthetic-model\",\"usage\":{\"input_"
             "tokens\":%s,\"output_tokens\":1}}}",
             cases[i].n);
    ClaudeRecord r = {0};
    line(&r, bytes);
    ASSERT_EQ(cases[i].valid ? 1 : 0, r.usage_count);
    if (cases[i].valid)
      ASSERT_EQ(cases[i].expected, r.usage_rows[0].unit.input);
    claude_record_destroy(&r);
  }
}
TEST(claude_usage_vertex_metadata_dictionary_array_and_identifier_branches) {
  const char *tails[] = {
      "\"usage\":{\"input_tokens\":1}},\"metadata\":{\"nested\":{\"provider\":"
      "\"Vertex\"}}}",
      "\"usage\":{\"input_tokens\":1}},\"metadata\":[{\"backend\":\"vertex\"}]"
      "}",
      "\"usage\":{\"input_tokens\":1}},\"metadata\":[[{\"backend\":\"vertex\"}]"
      "]}",
      "\"usage\":{\"input_tokens\":1}},\"metadata\":{\"gcpSynthetic\":42}}",
      "\"usage\":{\"input_tokens\":1},\"id\":\"msg_vrtx_synthetic\"}}",
      "\"usage\":{\"input_tokens\":1}},\"metadata\":{\"provider\":\"GCP\"}}",
      "\"usage\":{\"input_tokens\":1}},\"metadata\":{\"p\\u0072ovider\":"
      "\"\\u0076ertex\"}}"};
  for (size_t i = 0; i < sizeof tails / sizeof *tails; i++) {
    char bytes[768];
    snprintf(bytes, sizeof bytes, "%s%s", ROW_PREFIX, tails[i]);
    ClaudeRecord r = {0};
    line(&r, bytes);
    ASSERT_EQ(i == 2 || i == 5 ? 1 : 0, r.usage_count);
    claude_record_destroy(&r);
  }
  ClaudeRecord r = {0};
  line(&r,
       "{\"type\":\"user\",\"nested\":{\"type\":\"assistant\"},\"usage\":{}}");
  ASSERT_TRUE(omap_get(&r.rows_dropped, STR_LIT("type")));
  claude_record_destroy(&r);
}
TEST(claude_usage_primary_vertex_checks_respect_swift_grapheme_boundaries) {
  const char *message_fields[] = {
      "\"id\":\"msg_vrtx_\\u0301synthetic\",\"model\":\"synthetic-model\"",
      "\"id\":\"synthetic-message\",\"model\":\"claude-\\u0301synthetic@1\"",
      ("\"id\":\"synthetic-message\",\"model\":\"claude-synthetic@"
       "\\u0301version\"")};
  for (size_t i = 0; i < sizeof message_fields / sizeof *message_fields; i++) {
    char bytes[768];
    snprintf(bytes, sizeof bytes,
             "{\"type\":\"assistant\",\"timestamp\":\"2001-01-01T00:00:00Z\","
             "\"message\":{%s,\"usage\":{\"input_tokens\":3}}}",
             message_fields[i]);
    ClaudeRecord r = {0};
    line(&r, bytes);
    ASSERT_EQ(1, r.usage_count);
    ASSERT_EQ(3, r.usage_rows[0].unit.input);
    claude_record_destroy(&r);
  }
  ClaudeRecord r = {0};
  line(&r, ROW_PREFIX "\"usage\":{\"input_tokens\":5}},\"requestId\":\"req_"
                      "vrtx_\\u0301synthetic\"}");
  ASSERT_EQ(1, r.usage_count);
  claude_record_destroy(&r);
}
TEST(claude_usage_path_role_uses_complete_graphemes_for_winning_owner) {
  ClaudeRecord records[2] = {
      {.id = STR_LIT("synthetic-first-owner"),
       .key = {.path = STR_LIT("/synthetic/subagents/\xcc\x81"
                               "agent.jsonl")}},
      {.id = STR_LIT("synthetic-second-owner"),
       .key = {.path = STR_LIT("/synthetic/z.jsonl")}}};
  line(&records[0], ROW_PREFIX "\"usage\":{\"input_tokens\":3}}}");
  line(&records[1], ROW_PREFIX "\"usage\":{\"input_tokens\":7}}}");
  Corpus c = {0};
  ClaudeScan scan;
  composed(records, 2, &scan, &c);
  SessionModel *first = omap_get(&c.sessions, records[0].id),
               *second = omap_get(&c.sessions, records[1].id);
  ASSERT_EQ(1, first->unit_count);
  ASSERT_EQ(3, first->own_usage->input);
  ASSERT_EQ(0, second->unit_count);
  ASSERT_FALSE(records[0].usage_rows[0].subagent);
  ASSERT_EQ(1, scan.duplicate_keys);
  ASSERT_EQ(1, scan.duplicate_rows);
  corpus_destroy(&c);
  for (size_t i = 0; i < 2; i++)
    claude_record_destroy(&records[i]);
}
TEST(claude_usage_advisor_typed_envelope_and_nested_cache_creation) {
  ClaudeRecord r = {0};
  line(&r, ROW_PREFIX
       "\"usage\":{\"input_tokens\":1,\"iterations\":[{\"type\":\"advisor_"
       "message\",\"model\":\"synthetic-advisor\",\"input_tokens\":7,\"output_"
       "tokens\":11,\"cache_read_input_tokens\":13,\"cache_creation_input_"
       "tokens\":999,\"cache_creation\":{\"ephemeral_5m_input_tokens\":17,"
       "\"ephemeral_1h_input_tokens\":19}}]}}}");
  ASSERT_EQ(2, r.usage_count);
  ASSERT_EQ(56, r.usage_rows[1].unit.input);
  ASSERT_EQ(36, r.usage_rows[1].unit.cache_write);
  ASSERT_EQ(19, r.usage_rows[1].unit.cache_write_1h);
  line(&r, ROW_PREFIX "\"usage\":{\"input_tokens\":1,\"iterations\":[{\"type\":"
                      "\"advisor_message\",\"model\":\"synthetic-advisor\","
                      "\"input_tokens\":1,\"output_tokens\":2},{\"type\":"
                      "\"other\",\"input_tokens\":-1,\"output_tokens\":0}]}}}");
  ASSERT_EQ(3,
            r.usage_count); /* Invalid unrelated iteration rejects advisors. */
  line(&r, ROW_PREFIX
       "\"usage\":{\"input_tokens\":1,\"iterations\":[{\"type\":\"advisor_"
       "message\",\"model\":\"synthetic-advisor\",\"input_tokens\":0,\"output_"
       "tokens\":0,\"cache_creation\":{\"ephemeral_5m_input_tokens\":"
       "18446744073709551615,\"ephemeral_1h_input_tokens\":3}}]}}}");
  ASSERT_EQ(5, r.usage_count);
  ASSERT_EQ((__int128)UINT64_MAX, r.usage_rows[4].unit.cache_write);
  ASSERT_EQ(3, r.usage_rows[4].unit.cache_write_1h);
  line(&r, ROW_PREFIX
       "\"usage\":{\"input_tokens\":1,\"iterations\":[{\"type\":\"other\","
       "\"type\":\"advisor_message\",\"model\":\"synthetic-advisor\",\"input_"
       "tokens\":1,\"output_tokens\":2}]}}}");
  ASSERT_EQ(6, r.usage_count); /* Serde rejects duplicate recognized fields. */
  claude_record_destroy(&r);
}
