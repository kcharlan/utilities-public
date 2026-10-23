#include "corpus/provider.h"
#include "out/session_payload.h"
#include "price/compose.h"
#include "runner.h"
#include "yyjson.h"
#include <stdalign.h>

TEST(provider_ids_cover_every_provider) {
  ASSERT_TRUE(str_equal(provider_id(PROVIDER_CODEX), STR_LIT("codex")));
  ASSERT_TRUE(str_equal(provider_id(PROVIDER_CLAUDE), STR_LIT("claude")));
  ASSERT_TRUE(str_equal(provider_id(PROVIDER_OPENCODE), STR_LIT("opencode")));
  ASSERT_TRUE(str_equal(provider_id(PROVIDER_ANTIGRAVITY), STR_LIT("antigravity")));
}

TEST(compose_skips_opencode_and_prices_authored_units) {
  Corpus c = {0};
  PriorityTurns priority = {0};
  /* Even Codex-shaped records owned by another provider are excluded. */
  UsageRecord usage = {
      .line = 1,
      .response_id = {.kind = JS_STRING, .value.s = STR_LIT("synthetic-response")},
      .ts = {.kind = JS_STRING, .value.s = STR_LIT("2030-01-02T12:00:00Z")},
      .thread_usage = {.input = {.kind = JS_INT, .value.i = 99},
                       .output = {.kind = JS_INT, .value.i = 1}},
      .thread_id = {.kind = JS_STRING, .value.s = STR_LIT("synthetic-opencode")},
      .input = {.kind = JS_INT, .value.i = 99},
      .output = {.kind = JS_INT, .value.i = 1}};
  LogRecord record = {.key.path = STR_LIT("/synthetic/foreign-provider"),
                      .usage_records = &usage, .usage_count = 1,
                      .token_stream = {.has_prepass = true,
                        .prepass.session_id = STR_LIT("synthetic-opencode")}};
  const LogRecord *foreign[] = {&record};
  TurnModel turn = {.id = STR_LIT("synthetic-turn")};
  SessionModel s = {.id = STR_LIT("synthetic-opencode"),
                    .provider = PROVIDER_OPENCODE, .records = foreign,
                    .record_count = 1, .turns = &turn, .turn_count = 1};
  ASSERT_EQ(ERR_OK, omap_put(&c.sessions, s.id, &s).code);
  ASSERT_EQ(ERR_OK, compose_usage(&c, &priority).code);
  ASSERT_EQ(0, s.unit_count);
  UsageUnit units[] = {
      {.display_turn = turn.id, .model = STR_LIT("synthetic-model"),
       .input = 9, .output = 3, .has_cost = true, .cost_usd = 0.25},
      {.model = STR_LIT("synthetic-model"), .input = 4, .output = 2,
       .has_cost = true, .cost_usd = 0.0}};
  s.units = units; s.unit_count = 2;
  ASSERT_EQ(ERR_OK, compose_aggregate_session(&c, &s).code);
  ASSERT_EQ(ERR_OK, compose_refresh_costs(&c, false).code);
  ASSERT_EQ(13, s.own_usage->input);
  ASSERT_EQ(3, turn.usage->output);
  ASSERT_EQ(4, s.outside_usage->input);
  ASSERT_TRUE(s.own_usage->has_cost);
  ASSERT_TRUE(s.own_usage->cost_usd == 0.25);
  ASSERT_TRUE(s.outside_usage->has_cost);
  ASSERT_TRUE(s.outside_usage->cost_usd == 0.0);
  ASSERT_EQ(0, s.own_usage->unpriced_tokens);
  JsonWriter w = {0}; compose_buckets_json(&w, &s);
  ASSERT_EQ(ERR_OK, w.error.code);
  yyjson_doc *doc = yyjson_read(w.data, w.length, 0);
  ASSERT_TRUE(doc);
  yyjson_val *bucket = yyjson_arr_get_first(yyjson_doc_get_root(doc));
  ASSERT_STREQ("opencode", yyjson_get_str(yyjson_arr_get(bucket, 9)));
  ASSERT_STREQ("standard", yyjson_get_str(yyjson_arr_get(bucket, 2)));
  yyjson_doc_free(doc); jsonw_free(&w);
  units[1].has_cost = false;
  ASSERT_EQ(ERR_OK, compose_refresh_costs(&c, false).code);
  ASSERT_FALSE(s.own_usage->has_cost);
  ASSERT_EQ(6, s.own_usage->unpriced_tokens);
  corpus_destroy(&c);
}

TEST(provider_helpers_preserve_claude) {
  Corpus c = {0};
  TurnModel turns[2] = {
      {.start_ms = {true, {.i = 10}}, .end_ms = {true, {.i = 30}},
       .duration_ms = {true, {.i = 20}}, .status = STR_LIT("completed")},
      {.start_ms = {true, {.i = 20}}, .end_ms = {true, {.i = 40}},
       .duration_ms = {true, {.i = 20}}, .status = STR_LIT("completed")}};
  SessionModel s = {.provider = PROVIDER_CLAUDE, .turns = turns, .turn_count = 2,
                    .start_ms = {true, 0}, .end_ms = {true, 100},
                    .flags = F_RETAINED};
  ASSERT_EQ(ERR_OK, omap_put(&c.sessions, STR_LIT("synthetic"), &s).code);
  __int128 wide = (__int128)INT64_MAX + 1;
  CorpusTools tools = {.shell = 2, .shell_failed = 1, .file_edits = 3, .web = 4};
  ASSERT_EQ(ERR_OK, omap_put(&tools.mcp, STR_LIT("synthetic-mcp"), &wide).code);
  ASSERT_EQ(ERR_OK, omap_put(&tools.other, STR_LIT("synthetic-tool"), &wide).code);
  for (size_t i = 0; i < 2; i++)
    ASSERT_EQ(ERR_OK, corpus_turn_tools_adopt(&c.arena, &s, &turns[i], &tools).code);
  ASSERT_EQ(4, s.tools.shell); ASSERT_EQ(2, s.tools.shell_failed);
  ASSERT_EQ(6, s.tools.file_edits); ASSERT_EQ(8, s.tools.web);
  __int128 *copied = omap_get(&turns[0].tools.mcp, STR_LIT("synthetic-mcp"));
  ASSERT_TRUE(copied != &wide); ASSERT_EQ(wide, *copied);
  ASSERT_EQ(0, (uintptr_t)copied % alignof(__int128));
  ASSERT_EQ(wide * 2, *(__int128 *)omap_get(&s.tools.other, STR_LIT("synthetic-tool")));
  const char *statuses[] = {"running", "abandoned", "aborted", "interrupted", "completed"};
  for (size_t i = 0; i < 5; i++)
    corpus_status_flags(&s, (Str){statuses[i], (uint32_t)strlen(statuses[i])});
  ASSERT_EQ(F_RETAINED | F_LIVE | F_ABANDONED | F_ABORTED | F_INTERRUPTED, s.flags);
  ASSERT_EQ(ERR_OK, corpus_session_idle(&c.arena, &s).code);
  ASSERT_TRUE(s.idle_ms.present); ASSERT_EQ(70, s.idle_ms.value.i);
  s.start_ms.present = false; s.idle_ms = (MaybeNum){0};
  ASSERT_EQ(ERR_OK, corpus_session_idle(&c.arena, &s).code);
  ASSERT_FALSE(s.idle_ms.present);
  corpus_destroy(&c);
  ASSERT_EQ(wide, *(__int128 *)omap_get(&tools.other, STR_LIT("synthetic-tool")));
  omap_destroy(&tools.mcp); omap_destroy(&tools.other);
}

TEST(payload_sessions_emits_opencode_provider) {
  Corpus c = {0}; PayloadIds ids = {0};
  SessionModel s = {.id = STR_LIT("synthetic-opencode"), .provider = PROVIDER_OPENCODE,
                    .kind = STR_LIT("orphan"), .is_subagent = true,
                    .parent_id = STR_LIT("synthetic-parent"),
                    .agent_label = STR_LIT("Synthetic agent")};
  ASSERT_EQ(ERR_OK, omap_put(&c.sessions, s.id, &s).code);
  JsonWriter w = {0}; payload_sessions(&w, &c, &ids);
  ASSERT_EQ(ERR_OK, w.error.code);
  yyjson_doc *doc = yyjson_read(w.data, w.length, 0); ASSERT_TRUE(doc);
  yyjson_val *row = yyjson_arr_get_first(yyjson_doc_get_root(doc));
  ASSERT_STREQ("opencode", yyjson_get_str(yyjson_obj_get(row, "provider")));
  ASSERT_STREQ("Synthetic agent", yyjson_get_str(yyjson_obj_get(row, "label")));
  ASSERT_STREQ("synthetic-parent", yyjson_get_str(yyjson_obj_get(row, "parent_id")));
  yyjson_doc_free(doc); jsonw_free(&w); corpus_destroy(&c);
}

TEST(provider_archive_reason_is_additive) {
  for (Provider p = PROVIDER_CODEX; p <= PROVIDER_OPENCODE; p++) {
    Corpus c = {0}; PayloadIds ids = {0};
    SessionModel s = {.id = STR_LIT("synthetic"), .provider = p};
    ASSERT_FALSE(s.archive_reason.p);
    if (p == PROVIDER_OPENCODE) {
      s.archived = true;
      ASSERT_EQ(ERR_OK, str_copy(&c.arena, STR_LIT("session"), &s.archive_reason).code);
    }
    ASSERT_EQ(ERR_OK, omap_put(&c.sessions, s.id, &s).code);
    JsonWriter w = {0}; payload_sessions(&w, &c, &ids);
    ASSERT_EQ(ERR_OK, w.error.code);
    yyjson_doc *doc = yyjson_read(w.data, w.length, 0); ASSERT_TRUE(doc);
    yyjson_val *row = yyjson_arr_get_first(yyjson_doc_get_root(doc));
    ASSERT_EQ(p == PROVIDER_OPENCODE, yyjson_is_true(yyjson_obj_get(row, "archived")));
    yyjson_val *reason = yyjson_obj_get(row, "archive_reason");
    if (p == PROVIDER_OPENCODE) ASSERT_STREQ("session", yyjson_get_str(reason));
    else ASSERT_TRUE(yyjson_is_null(reason));
    yyjson_doc_free(doc); jsonw_free(&w); corpus_destroy(&c);
  }
}
