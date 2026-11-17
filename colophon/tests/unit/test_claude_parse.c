#define _DARWIN_C_SOURCE
#include "parse/classify.h"

#include "claude/parse.h"
#include "claude/scan.h"
#include "runner.h"
#include "testing/hooks.h"
#include "util/fileio.h"
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>
static void parse_text(const char *bytes, ClaudeRecord *out) {
  char path[1024];
  snprintf(path, sizeof path, "%s/synthetic-claude-XXXXXX.jsonl",
           getenv("COLOPHON_HOME"));
  int fd = mkstemps(path, 6);
  ASSERT_TRUE(fd >= 0);
  ASSERT_EQ(strlen(bytes), (size_t)write(fd, bytes, strlen(bytes)));
  ASSERT_EQ(0, close(fd));
  DiscoveredLog key = {.path = {path, (uint32_t)strlen(path)},
                       .size = (int64_t)strlen(bytes)};
  ASSERT_EQ(
      ERR_OK,
      claude_parse(&key, STR_LIT("/synthetic/projects"), (Str){0}, out).code);
  ASSERT_EQ(0, unlink(path));
}
TEST(claude_turn_allocation_failure_is_unpublished_and_safe) {
  const char *bytes = "{\"type\":\"user\",\"message\":{\"content\":\"Synthetic first\"}}\n"
      "{\"type\":\"assistant\",\"message\":{\"stop_reason\":\"end_turn\"}}\n"
      "{\"type\":\"user\",\"message\":{\"content\":\"Synthetic second\"}}\n";
  char path[1024];
  snprintf(path, sizeof path, "%s/synthetic-allocation.jsonl", getenv("TMPDIR"));
  FILE *f = fopen(path, "w"); ASSERT_TRUE(f);
  ASSERT_TRUE(fputs(bytes, f) >= 0); ASSERT_EQ(0, fclose(f));
  DiscoveredLog key = {.path = {path, (uint32_t)strlen(path)}, .size = (int64_t)strlen(bytes)};
  for (size_t n = 1; n <= 2; n++) {
    char fault[64]; snprintf(fault, sizeof fault, "claude_turn_alloc:%zu", n);
    ASSERT_EQ(0, setenv("COLOPHON_TEST_FAULT", fault, 1));
    ClaudeRecord r = {0}; Err e = claude_parse(&key, STR_LIT("/synthetic/projects"), (Str){0}, &r);
    ASSERT_EQ(0, unsetenv("COLOPHON_TEST_FAULT")); (void)cp_fault("reset");
    ASSERT_EQ(ERR_NOMEM, e.code); ASSERT_EQ(n - 1, r.turn_count);
    if (r.turn_count) ASSERT_TRUE(str_equal(r.turns[0]->end_kind, STR_LIT("completed")));
    claude_record_destroy(&r);
  }
  ASSERT_EQ(0, unlink(path));
}
TEST(claude_prompt_classification_and_end_kinds) {
  const char *rows =
      "{\"type\":\"user\",\"message\":{\"content\":\"Quoted <system-reminder> "
      "is a prompt\"}}\n"
      "{\"type\":\"user\",\"message\":{\"content\":\"[Request interrupted by "
      "user]\"}}\n"
      "{\"type\":\"user\",\"message\":{\"content\":\"<command-name>/synthetic</"
      "command-name>\"}}\n"
      "{\"type\":\"system\",\"subtype\":\"api_error\"}\n"
      "{\"type\":\"user\",\"message\":{\"content\":\"<bash-input>synthetic</"
      "bash-input>\"}}\n"
      "{\"type\":\"assistant\",\"message\":{\"stop_reason\":\"end_turn\","
      "\"content\":[]}}\n"
      "{\"type\":\"user\",\"message\":{\"content\":[{\"type\":\"image\"}]}}\n"
      "{\"type\":\"user\",\"isMeta\":true,\"message\":{\"content\":\"hidden\"}}"
      "\n"
      "{\"type\":\"user\",\"isCompactSummary\":true,\"message\":{\"content\":"
      "\"hidden\"}}\n"
      "{\"type\":\"user\",\"message\":{\"content\":[{\"type\":\"tool_result\"},"
      "{\"type\":\"text\",\"text\":\"hidden\"}]}}\n"
      "{\"type\":\"user\",\"message\":{\"content\":\"<system-reminder>hidden\"}"
      "}\n"
      "{\"type\":\"user\",\"message\":{\"content\":\"<task-notification>"
      "hidden\"}}\n"
      "{\"type\":\"user\",\"message\":{\"content\":\"<local-command-stdout>"
      "hidden\"}}\n"
      "{\"type\":\"synthetic-unknown\"}\n";
  ClaudeRecord r = {0};
  parse_text(rows, &r);
  ASSERT_EQ(4, r.turn_count);
  ASSERT_TRUE(str_equal(r.turns[0]->end_kind, STR_LIT("interrupted")));
  ASSERT_TRUE(str_equal(r.turns[1]->end_kind, STR_LIT("aborted")));
  ASSERT_TRUE(str_equal(r.turns[2]->end_kind, STR_LIT("completed")));
  ASSERT_TRUE(str_equal(r.turns[3]->end_kind, STR_LIT("open")));
  ASSERT_TRUE(str_equal(r.requests[0].kind, STR_LIT("text")));
  ASSERT_TRUE(str_equal(r.requests[1].kind, STR_LIT("command")));
  ASSERT_EQ(1, r.requests[3].images);
  ASSERT_EQ(1, r.reader.unknown_types.size);
  claude_record_destroy(&r);
}
TEST(claude_history_aliases_preserve_exact_unicode_strings) {
  ClaudeRecord r;
  parse_text("{\"type\":\"user\",\"sessionId\":\"synthetic-séssion\",\"message\":{\"content\":\"Invent a synthetic kite\"}}\n"
             "{\"type\":\"user\",\"sessionId\":\"synthetic-se\\u0301ssion\",\"message\":{\"content\":\"Invent a synthetic lantern\"}}\n",&r);
  ASSERT_EQ(2,r.aliases.count);
  ASSERT_FALSE(str_equal(r.aliases.items[0],r.aliases.items[1]));
  claude_record_destroy(&r);
}
TEST(claude_legacy_copy_reader_fallback_preserves_counts_and_raw_facts) {
  const char *rows = "{\"type\":\"user\",\"message\":{\"content\":\"Synthetic legacy prompt\"}}\n"
      "{\"type\":\"assistant\",\"message\":{\"content\":[{\"type\":\"tool_use\",\"id\":\"synthetic-tool\",\"name\":\"Bash\"}]}}\n";
  ClaudeRecord records[2] = {0};
  parse_text(rows, &records[0]); parse_text(rows, &records[1]);
  for (size_t i = 0; i < 2; i++) {
    records[i].id = STR_LIT("synthetic-legacy-session");
    records[i].reader_facts = false;
  }
  records[1].tools[0].shell = 2;
  records[0].answers[0] = STR_LIT("Synthetic earlier legacy answer");
  records[1].answers[0] = STR_LIT("Synthetic later legacy answer");
  records[0].answer_ms[0] = records[1].answer_ms[0] = (MaybeMs){0};
  records[0].turns[0]->last_ms = (MaybeMs){true, 1000};
  records[1].turns[0]->last_ms = (MaybeMs){true, 2000};
  Corpus c = {0}; CorpusStrings collisions = {0};
  ASSERT_EQ(ERR_OK, claude_corpus_add(records, 2, 0, &c, &collisions).code);
  SessionModel *s = omap_get(&c.sessions, records[0].id);
  ASSERT_EQ(1, s->turn_count); ASSERT_EQ(2, s->tools.shell);
  ASSERT_TRUE(str_equal(s->turns[0].final_answer, records[1].answers[0]));
  ASSERT_TRUE(str_equal(records[0].turns[0]->key, STR_LIT("claude-turn-1")));
  ASSERT_EQ(1, records[0].tools[0].shell); ASSERT_EQ(2, records[1].tools[0].shell);
  ASSERT_EQ(1, records[0].canonical_turns.size);
  corpus_destroy(&c);
  claude_record_destroy(&records[0]); claude_record_destroy(&records[1]);
}
TEST(claude_anonymous_repeated_tools_survive_reader_reconciliation) {
  ClaudeRecord r[2]={0};
  const char *rows="{\"type\":\"user\",\"message\":{\"content\":\"Synthetic anonymous tools\"}}\n"
      "{\"type\":\"assistant\",\"message\":{\"content\":[{\"type\":\"tool_use\",\"name\":\"Bash\"}]}}\n"
      "{\"type\":\"assistant\",\"message\":{\"content\":[{\"type\":\"tool_use\",\"name\":\"Bash\"}]}}\n";
  parse_text(rows,&r[0]);parse_text(rows,&r[1]); r[1].id=r[0].id;
  Corpus c={0}; CorpusStrings collisions={0};
  ASSERT_EQ(ERR_OK,claude_corpus_add(r,2,0,&c,&collisions).code);
  SessionModel *s=omap_get(&c.sessions,r[0].id);
  ASSERT_EQ(2,s->tools.shell);
  corpus_destroy(&c); claude_record_destroy(&r[0]);claude_record_destroy(&r[1]);
}

TEST(claude_tools_match_results_and_map_servers) {
  ClaudeRecord r = {0};
  parse_text(
      "{\"type\":\"user\",\"message\":{\"content\":\"Synthetic tools\"}}\n"
      "{\"type\":\"assistant\",\"message\":{\"stop_reason\":\"tool_use\","
      "\"content\":["
      "{\"type\":\"tool_use\",\"name\":\"Bash\",\"id\":\"synthetic-shell\"},"
      "{\"type\":\"tool_use\",\"name\":\"Edit\"},{\"type\":\"tool_use\","
      "\"name\":\"Write\"},"
      "{\"type\":\"tool_use\",\"name\":\"MultiEdit\"},{\"type\":\"tool_use\","
      "\"name\":\"NotebookEdit\"},"
      "{\"type\":\"tool_use\",\"name\":\"WebFetch\"},{\"type\":\"tool_use\","
      "\"name\":\"WebSearch\"},"
      "{\"type\":\"tool_use\",\"name\":\"mcp__synthetic__lookup\"},"
      "{\"type\":\"tool_use\",\"name\":\"SyntheticOther\"}]}}\n"
      "{\"type\":\"user\",\"message\":{\"content\":[{\"type\":\"tool_result\","
      "\"tool_use_id\":\"synthetic-other\",\"is_error\":true},{\"type\":\"tool_"
      "result\",\"tool_use_id\":\"synthetic-shell\",\"is_error\":true}]}}\n",
      &r);
  ASSERT_EQ(1, r.turn_count);
  ASSERT_TRUE(str_equal(r.turns[0]->end_kind, STR_LIT("open")));
  ASSERT_EQ(1, r.tools[0].shell);
  ASSERT_EQ(1, r.tools[0].shell_failed);
  ASSERT_EQ(4, r.tools[0].file_edits);
  ASSERT_EQ(2, r.tools[0].web);
  ASSERT_EQ(1, *(__int128 *)omap_get(&r.tools[0].mcp, STR_LIT("synthetic")));
  ASSERT_EQ(
      1, *(__int128 *)omap_get(&r.tools[0].other, STR_LIT("SyntheticOther")));
  claude_record_destroy(&r);
}
TEST(claude_command_message_unknown_tag_and_last_assistant_end_reason) {
  ClaudeRecord r = {0};
  parse_text("{\"type\":\"user\",\"message\":{\"content\":\"<command-message>"
             "synthetic</command-message>\"}}\n"
             "{\"type\":\"assistant\",\"message\":{\"stop_reason\":\"end_"
             "turn\",\"content\":[]}}\n"
             "{\"type\":\"assistant\",\"message\":{\"stop_reason\":\"tool_"
             "use\",\"content\":[]}}\n"
             "{\"type\":\"user\",\"message\":{\"content\":\"<synthetic-"
             "unlisted>prompt\"}}\n"
             "{\"type\":\"assistant\",\"message\":{\"stop_reason\":null,"
             "\"content\":[]}}\n"
             "{\"type\":\"system\",\"subtype\":\"api_error\"}\n"
             "{\"type\":\"progress\"}\n",
             &r);
  ASSERT_EQ(2, r.turn_count);
  /* CorpusTools contains __int128; its consumers require native alignment. */
  ASSERT_EQ(0, (uintptr_t)r.tools % _Alignof(CorpusTools));
  ASSERT_TRUE(str_equal(r.requests[0].kind, STR_LIT("command")));
  ASSERT_TRUE(str_equal(r.requests[1].kind, STR_LIT("text")));
  ASSERT_TRUE(str_equal(r.turns[0]->end_kind, STR_LIT("open")));
  ASSERT_TRUE(str_equal(r.turns[1]->end_kind, STR_LIT("open")));
  claude_record_destroy(&r);
}
TEST(reader_null_predicate_retains_codex_known_types) {
  char path[1024];
  snprintf(path, sizeof path, "%s/synthetic-reader-XXXXXX",
           getenv("COLOPHON_HOME"));
  int fd = mkstemp(path);
  ASSERT_TRUE(fd >= 0);
  const char bytes[] = "{\"type\":\"session_meta\"}\n{\"type\":\"user\"}\n";
  ASSERT_EQ(sizeof bytes - 1, (size_t)write(fd, bytes, sizeof bytes - 1));
  ASSERT_EQ(0, close(fd));
  DiscoveredLog key = {.path = {path, (uint32_t)strlen(path)},
                       .size = sizeof bytes - 1};
  ReaderResult result = {0};
  ReaderCallbacks callbacks = {0};
  ASSERT_EQ(ERR_OK, reader_read_log(&key, &callbacks, &result).code);
  ASSERT_EQ(1, result.unknown_types.size);
  ASSERT_TRUE(omap_get(&result.unknown_types, STR_LIT("user")));
  ASSERT_FALSE(omap_get(&result.unknown_types, STR_LIT("session_meta")));
  reader_result_destroy(&result);
  ASSERT_EQ(0, unlink(path));
}
TEST(claude_filename_identity_collisions_same_stem_and_aliases) {
  char path[1024];
  snprintf(path, sizeof path, "%s/synthetic-canonical.jsonl",
           getenv("COLOPHON_HOME"));
  FILE *f = fopen(path, "w");
  ASSERT_TRUE(f);
  const char *bytes = "{\"type\":\"user\",\"sessionId\":\"  synthetic-foreign  "
                      "\",\"message\":{\"content\":\"Synthetic identity\"}}\n";
  ASSERT_TRUE(fputs(bytes, f) >= 0);
  ASSERT_EQ(0, fclose(f));
  DiscoveredLog key = {.path = {path, (uint32_t)strlen(path)},
                       .size = (int64_t)strlen(bytes)};
  ClaudeRecord r[2] = {{0}, {0}};
  ASSERT_EQ(
      ERR_OK,
      claude_parse(&key, STR_LIT("/synthetic/root"), (Str){0}, &r[0]).code);
  ASSERT_TRUE(str_equal(r[0].id, STR_LIT("synthetic-canonical")));
  ASSERT_EQ(1, r[0].aliases.count);
  ASSERT_TRUE(
      str_equal(r[0].aliases.items[0], STR_LIT("  synthetic-foreign  ")));
  ASSERT_EQ(ERR_OK,
            claude_parse(&key, STR_LIT("/synthetic/root-copy"), (Str){0}, &r[1])
                .code);
  Corpus c = {0};
  CorpusStrings collisions = {0};
  ASSERT_EQ(ERR_OK, claude_corpus_add(r, 2, 0, &c, &collisions).code);
  ASSERT_EQ(1, c.sessions.size);
  SessionModel *s = omap_get(&c.sessions, STR_LIT("synthetic-canonical"));
  ASSERT_TRUE(s && s->provider == PROVIDER_CLAUDE);
  ASSERT_TRUE(!s->record && !s->records && !s->record_count);
  ASSERT_FALSE(s->flags & F_NO_META);
  corpus_destroy(&c);
  SessionModel codex = {.id = STR_LIT("synthetic-canonical")};
  c = (Corpus){0};
  ASSERT_EQ(ERR_OK, omap_put(&c.sessions, codex.id, &codex).code);
  collisions = (CorpusStrings){0};
  ASSERT_EQ(ERR_OK, claude_corpus_add(r, 2, 0, &c, &collisions).code);
  ASSERT_EQ(1, c.sessions.size);
  ASSERT_TRUE(omap_get(&c.sessions, codex.id) == &codex);
  ASSERT_EQ(2, collisions.count);
  corpus_destroy(&c);
  claude_record_destroy(&r[0]);
  claude_record_destroy(&r[1]);
  ASSERT_EQ(0, unlink(path));
}
TEST(claude_subagent_filename_uses_parent_identity) {
  char directory[1024], path[1200];
  snprintf(directory, sizeof directory, "%s/synthetic-parent",
           getenv("COLOPHON_HOME"));
  ASSERT_EQ(0, mkdir(directory, 0700));
  strcat(directory, "/subagents");
  ASSERT_EQ(0, mkdir(directory, 0700));
  snprintf(path, sizeof path, "%s/agent-synthetic-child.jsonl", directory);
  FILE *f = fopen(path, "w");
  ASSERT_TRUE(f);
  const char *bytes = "{\"type\":\"user\",\"sessionId\":\"synthetic-foreign\","
                      "\"message\":{\"content\":\"Synthetic agent\"}}\n";
  ASSERT_TRUE(fputs(bytes, f) >= 0);
  ASSERT_EQ(0, fclose(f));
  ClaudeRecord r = {0};
  DiscoveredLog key = {.path = {path, (uint32_t)strlen(path)},
                       .size = (int64_t)strlen(bytes)};
  ASSERT_EQ(
      ERR_OK,
      claude_parse(&key, STR_LIT("/synthetic/projects"), (Str){0}, &r).code);
  ASSERT_TRUE(
      str_equal(r.id, STR_LIT("synthetic-parent/agent-synthetic-child")));
  ASSERT_EQ(0, r.aliases.count);
  claude_record_destroy(&r);
  ASSERT_EQ(0, unlink(path));
  ASSERT_EQ(0, rmdir(directory));
  *strrchr(directory, '/') = 0;
  ASSERT_EQ(0, rmdir(directory));
}

static void parse_subagent_text(const char *bytes, ClaudeRecord *out) {
  char root[1024], parent[1200], dir[1300], path[1400];
  snprintf(root, sizeof root, "%s/synthetic-handback-XXXXXX", getenv("COLOPHON_HOME"));
  ASSERT_TRUE(mkdtemp(root));
  snprintf(parent, sizeof parent, "%s/synthetic-parent", root);
  snprintf(dir, sizeof dir, "%s/subagents", parent);
  snprintf(path, sizeof path, "%s/agent-synthetic-child.jsonl", dir);
  ASSERT_EQ(0, mkdir(parent, 0700)); ASSERT_EQ(0, mkdir(dir, 0700));
  FILE *f = fopen(path, "w"); ASSERT_TRUE(f);
  ASSERT_TRUE(fputs(bytes, f) >= 0); ASSERT_EQ(0, fclose(f));
  DiscoveredLog key = {.path = {path, (uint32_t)strlen(path)}, .size = (int64_t)strlen(bytes)};
  ASSERT_EQ(ERR_OK, claude_parse(&key, STR_LIT("/synthetic/projects"), (Str){0}, out).code);
  ASSERT_EQ(0, unlink(path)); ASSERT_EQ(0, rmdir(dir));
  ASSERT_EQ(0, rmdir(parent)); ASSERT_EQ(0, rmdir(root));
}
#define HB_PROMPT "{\"type\":\"user\",\"timestamp\":\"2020-01-01T00:00:00Z\",\"message\":{\"content\":\"Synthetic request\"}}\n"
#define HB_CALL(stop, msg) "{\"type\":\"assistant\",\"timestamp\":\"2020-01-01T00:00:01Z\",\"message\":{\"stop_reason\":" stop ",\"content\":[{\"type\":\"tool_use\",\"id\":\"synthetic-hb\",\"name\":\"SubagentHandback\",\"input\":{" msg "}}]}}\n"
#define HB_RESULT(id, err) "{\"type\":\"user\",\"timestamp\":\"2020-01-01T00:00:02Z\",\"message\":{\"content\":[{\"type\":\"tool_result\",\"tool_use_id\":\"" id "\",\"is_error\":" err "}]}}\n"
#define HB_TEXT "{\"type\":\"assistant\",\"timestamp\":\"2020-01-01T00:00:03Z\",\"message\":{\"stop_reason\":\"end_turn\",\"content\":[{\"type\":\"text\",\"text\":\"Synthetic later answer\"}]}}\n"
#define HB_UNRESOLVED "{\"type\":\"assistant\",\"timestamp\":\"2020-01-01T00:00:03Z\",\"message\":{\"stop_reason\":\"tool_use\",\"content\":[{\"type\":\"tool_use\",\"id\":\"synthetic-other\",\"name\":\"Read\"}]}}\n"
#define HB_TEXT_AFTER_NEW "{\"type\":\"assistant\",\"timestamp\":\"2020-01-01T00:00:05Z\",\"message\":{\"stop_reason\":\"end_turn\",\"content\":[{\"type\":\"text\",\"text\":\"Synthetic later answer\"}]}}\n"
#define HB_NEW "{\"type\":\"user\",\"timestamp\":\"2020-01-01T00:00:04Z\",\"message\":{\"content\":\"Synthetic next request\"}}\n"
#define HB_CALL_TEXT HB_CALL("\"tool_use\"", "\"message\":\"Synthetic handback report\"")
#define HB_SUCCESS HB_PROMPT HB_CALL_TEXT HB_RESULT("synthetic-hb", "false")
static void handback_check(const char *rows, size_t turn, const char *kind, int64_t end) {
  ClaudeRecord r = {0}; parse_subagent_text(rows, &r);
  ASSERT_TRUE(str_equal(r.turns[turn]->end_kind, (Str){kind, (uint32_t)strlen(kind)}));
  if (end) { ASSERT_TRUE(r.turns[turn]->end_ms.present); ASSERT_EQ(end, r.turns[turn]->end_ms.value); }
  ASSERT_EQ(1, *(__int128 *)omap_get(&r.tools[0].other, STR_LIT("SubagentHandback")));
  claude_record_destroy(&r);
}
TEST(claude_subagent_handback_success_completion) {
  handback_check(HB_SUCCESS, 0, "completed", 1577836802000LL);
  handback_check(HB_PROMPT HB_CALL("null", "\"message\":\"Synthetic handback report\"") HB_RESULT("synthetic-hb", "false"), 0, "completed", 1577836802000LL);
}
TEST(claude_subagent_handback_success_answer) {
  ClaudeRecord r = {0}; parse_subagent_text(HB_SUCCESS, &r);
  ASSERT_TRUE(str_equal(r.answers[0], STR_LIT("Synthetic handback report")));
  ASSERT_TRUE(r.answer_ms[0].present); ASSERT_EQ(1577836801000LL, r.answer_ms[0].value);
  claude_record_destroy(&r);
}
TEST(claude_subagent_handback_unmatched_results_open) {
  handback_check(HB_PROMPT HB_CALL_TEXT, 0, "open", 0);
  handback_check(HB_PROMPT HB_CALL_TEXT HB_RESULT("synthetic-hb", "true"), 0, "open", 0);
  handback_check(HB_PROMPT HB_CALL_TEXT HB_RESULT("synthetic-foreign", "false"), 0, "open", 0);
}
TEST(claude_subagent_handback_unmatched_answer) {
  const char *cases[] = {HB_PROMPT HB_CALL_TEXT, HB_PROMPT HB_CALL_TEXT HB_RESULT("synthetic-hb", "true"), HB_PROMPT HB_CALL_TEXT HB_RESULT("synthetic-foreign", "false")};
  for (size_t i = 0; i < 3; i++) {
    ClaudeRecord r = {0}; parse_subagent_text(cases[i], &r);
    ASSERT_TRUE(str_equal(r.answers[0], STR_LIT("Synthetic handback report")));
    ASSERT_TRUE(r.answer_ms[0].present); ASSERT_EQ(1577836801000LL, r.answer_ms[0].value); claude_record_destroy(&r);
  }
}
TEST(claude_subagent_handback_unknown_last_clock) {
  handback_check(HB_SUCCESS "{\"type\":\"synthetic-unknown\",\"timestamp\":\"2020-01-01T00:00:05Z\"}\n", 0, "completed", 1577836802000LL);
}
TEST(claude_subagent_handback_later_text_completion) { handback_check(HB_SUCCESS HB_TEXT, 0, "completed", 1577836803000LL); }
TEST(claude_subagent_handback_later_text_answer) {
  ClaudeRecord r = {0}; parse_subagent_text(HB_SUCCESS HB_TEXT, &r);
  ASSERT_TRUE(str_equal(r.answers[0], STR_LIT("Synthetic later answer"))); ASSERT_TRUE(r.answer_ms[0].present);
  ASSERT_EQ(1577836803000LL, r.answer_ms[0].value); claude_record_destroy(&r);
}
TEST(claude_subagent_handback_later_tool_open) { handback_check(HB_SUCCESS HB_UNRESOLVED, 0, "open", 0); }
TEST(claude_subagent_handback_new_prompt_independent) {
  handback_check(HB_SUCCESS HB_NEW HB_TEXT_AFTER_NEW, 0, "completed", 1577836802000LL);
  handback_check(HB_SUCCESS HB_NEW HB_TEXT_AFTER_NEW, 1, "completed", 1577836805000LL);
}
TEST(claude_subagent_handback_delayed_result_open) { handback_check(HB_PROMPT HB_CALL_TEXT HB_NEW HB_RESULT("synthetic-hb", "false"), 1, "open", 0); }
TEST(claude_subagent_handback_duplicate_result_open) { handback_check(HB_SUCCESS HB_UNRESOLVED HB_RESULT("synthetic-hb", "false"), 0, "open", 0); }
TEST(claude_subagent_handback_error_consumes_id) { handback_check(HB_PROMPT HB_CALL_TEXT HB_RESULT("synthetic-hb", "true") HB_RESULT("synthetic-hb", "false"), 0, "open", 0); }
TEST(claude_subagent_handback_invalid_message_preserves_answer) {
  const char *cases[] = {HB_PROMPT HB_TEXT HB_CALL("null", ""), HB_PROMPT HB_TEXT HB_CALL("null", "\"message\":\"\""), HB_PROMPT HB_TEXT HB_CALL("null", "\"message\":42")};
  for (size_t i = 0; i < 3; i++) { ClaudeRecord r = {0}; parse_subagent_text(cases[i], &r);
    ASSERT_TRUE(str_equal(r.answers[0], STR_LIT("Synthetic later answer"))); ASSERT_TRUE(r.answer_ms[0].present);
    ASSERT_EQ(1577836803000LL, r.answer_ms[0].value); ASSERT_EQ(1, *(__int128 *)omap_get(&r.tools[0].other, STR_LIT("SubagentHandback"))); claude_record_destroy(&r); }
}
TEST(claude_subagent_handback_main_session_open) {
  ClaudeRecord r = {0}; parse_text(HB_SUCCESS, &r);
  ASSERT_TRUE(str_equal(r.turns[0]->end_kind, STR_LIT("open"))); ASSERT_EQ(1, *(__int128 *)omap_get(&r.tools[0].other, STR_LIT("SubagentHandback"))); claude_record_destroy(&r);
}
TEST(claude_subagent_handback_main_session_no_answer) {
  ClaudeRecord r = {0}; parse_text(HB_SUCCESS, &r); ASSERT_EQ(0, r.answers[0].n); ASSERT_FALSE(r.answer_ms[0].present); claude_record_destroy(&r);
}

TEST(claude_scan_unreadable_stores_are_incomplete) {
  char root[1024], desktop[1300], swap[1300], listing[1300], child[1400];
  snprintf(root, sizeof root, "%s/synthetic-completeness-XXXXXX",
           getenv("COLOPHON_HOME"));
  ASSERT_TRUE(mkdtemp(root));
  char *previous_home = strdup(getenv("HOME"));
  ASSERT_TRUE(previous_home);
  ASSERT_EQ(0, setenv("HOME", root, 1));
  snprintf(desktop, sizeof desktop,
           "%s/Library/Application "
           "Support/Claude/local-agent-mode-sessions/a/.claude/projects",
           root);
  snprintf(swap, sizeof swap,
           "%s/.claude-swap-backup/sessions/1-synthetic/projects", root);
  snprintf(listing, sizeof listing,
           "%s/Library/Application "
           "Support/Claude/local-agent-mode-sessions/synthetic-listable",
           root);
  snprintf(child, sizeof child, "%s/synthetic-child", listing);
  ASSERT_EQ(ERR_OK, file_mkdir_parents(desktop).code);
  ASSERT_EQ(ERR_OK, file_mkdir_parents(swap).code);
  ASSERT_EQ(ERR_OK, file_mkdir_parents(child).code);
  ASSERT_EQ(0, chmod(desktop, 0));
  ASSERT_EQ(0, chmod(swap, 0));
  ASSERT_EQ(0, chmod(listing, 0400));
  ClaudeScan scan = {0};
  Args args = {0};
  ASSERT_EQ(ERR_OK, claude_inspect(&args, &scan).code);
  ASSERT_EQ(ERR_OK, claude_scan(&scan, NULL).code);
  bool desktop_incomplete = false, swap_incomplete = false;
  for (size_t i = 0; i < scan.root_count; i++) {
    ClaudeRoot *r = &scan.roots[i];
    if (r->kind == CLAUDE_DESKTOP &&
        strstr(r->path.p, "local-agent-mode-sessions"))
      desktop_incomplete = !r->complete;
    if (r->kind == CLAUDE_SWAP)
      swap_incomplete = !r->complete;
  }
  claude_scan_destroy(&scan);
  ASSERT_EQ(0, chmod(desktop, 0700));
  ASSERT_EQ(0, chmod(swap, 0700));
  ASSERT_EQ(0, chmod(listing, 0700));
  ASSERT_EQ(ERR_OK, claude_inspect(&args, &scan).code);
  ASSERT_EQ(ERR_OK, claude_scan(&scan, NULL).code);
  bool readable_complete = true;
  for (size_t i = 0; i < scan.root_count; i++)
    readable_complete &= scan.roots[i].complete;
  size_t readable_skipped = scan.skipped_count;
  claude_scan_destroy(&scan);
  ASSERT_EQ(0, setenv("HOME", previous_home, 1));
  free(previous_home);
  ASSERT_TRUE(desktop_incomplete);
  ASSERT_TRUE(swap_incomplete);
  ASSERT_TRUE(readable_complete);
  ASSERT_EQ(0, readable_skipped);
  /* The outer unit wrapper owns and removes this synthetic fixture tree. */
}

TEST(claude_scan_locator_child_stat_failure_is_diagnostic_and_incomplete) {
  char root[1024], child[1300];
  snprintf(root, sizeof root, "%s/synthetic-stat-failure-XXXXXX",
           getenv("COLOPHON_HOME"));
  ASSERT_TRUE(mkdtemp(root));
  char *previous_home = strdup(getenv("HOME"));
  ASSERT_TRUE(previous_home);
  ASSERT_EQ(0, setenv("HOME", root, 1));
  snprintf(child, sizeof child,
           "%s/Library/Application "
           "Support/Claude/local-agent-mode-sessions/synthetic-child",
           root);
  ASSERT_EQ(ERR_OK, file_mkdir_parents(child).code);
  ClaudeScan scan = {0};
  Args args = {0};
  ASSERT_EQ(ERR_OK, claude_inspect(&args, &scan).code);
  char *canonical_child = realpath(child, NULL);
  ASSERT_TRUE(canonical_child);
  ASSERT_EQ(0, setenv("COLOPHON_TEST_FAULT", "claude_locator_lstat", 1));
  Err error = claude_scan(&scan, NULL);
  ASSERT_EQ(0, unsetenv("COLOPHON_TEST_FAULT"));
  bool incomplete = false, diagnostic = false;
  for (size_t i = 0; i < scan.root_count; i++)
    if (scan.roots[i].kind == CLAUDE_DESKTOP &&
        strstr(scan.roots[i].path.p, "local-agent-mode-sessions"))
      incomplete = !scan.roots[i].complete;
  for (size_t i = 0; i < scan.skipped_count; i++)
    diagnostic |=
        str_equal(scan.skipped[i].path,
                  (Str){canonical_child, (uint32_t)strlen(canonical_child)});
  claude_scan_destroy(&scan);
  free(canonical_child);
  ASSERT_EQ(0, setenv("HOME", previous_home, 1));
  free(previous_home);
  ASSERT_EQ(ERR_OK, error.code);
  ASSERT_TRUE(incomplete);
  ASSERT_TRUE(diagnostic);
}

#define CLOCK_PROMPT HB_PROMPT
#define CLOCK_ASSIST HB_UNRESOLVED
#define CLOCK_NEXT HB_NEW
#define CLOCK_DEQUEUE "{\"type\":\"queue-operation\",\"operation\":\"dequeue\",\"timestamp\":\"2020-01-01T00:00:04Z\"}\n"
#define CLOCK_STOP "{\"type\":\"system\",\"subtype\":\"stop_hook_summary\",\"timestamp\":\"2020-01-01T00:00:04Z\"}\n"
#define CLOCK_ERROR "{\"type\":\"system\",\"subtype\":\"api_error\",\"timestamp\":\"2020-01-01T00:00:04Z\"}\n"
#define CLOCK_NULL_TEXT "{\"type\":\"assistant\",\"timestamp\":\"2020-01-01T00:00:03Z\",\"message\":{\"stop_reason\":null,\"content\":[{\"type\":\"text\",\"text\":\"Synthetic answer\"}]}}\n"
static void clock_kind(const char *rows, const char *kind) {
  ClaudeRecord r = {0}; parse_text(rows, &r);
  ASSERT_TRUE(str_equal(r.turns[0]->end_kind, (Str){kind, (uint32_t)strlen(kind)}));
  claude_record_destroy(&r);
}
TEST(claude_turn_clock_ignores_bookkeeping_records) {
  ClaudeRecord r = {0}; parse_text(HB_PROMPT HB_TEXT
    "{\"type\":\"queue-operation\",\"operation\":\"enqueue\",\"timestamp\":\"2020-01-01T00:00:04Z\"}\n"
    "{\"type\":\"pr-link\",\"timestamp\":\"2020-01-01T00:00:05Z\"}\n"
    "{\"type\":\"user\",\"isMeta\":true,\"timestamp\":\"2020-01-01T00:00:06Z\",\"message\":{\"content\":\"synthetic\"}}\n"
    "{\"type\":\"attachment\",\"timestamp\":\"2020-01-01T00:00:07Z\"}\n"
    "{\"type\":\"system\",\"subtype\":\"stop_hook_summary\",\"timestamp\":\"2020-01-01T00:00:08Z\"}\n"
    "{\"type\":\"synthetic-unknown\",\"timestamp\":\"2020-01-01T00:00:09Z\"}\n", &r);
  ASSERT_EQ(1577836803000LL, r.turns[0]->last_ms.value);
  ASSERT_EQ(1577836809000LL, r.last_ms.value); claude_record_destroy(&r);
}
TEST(claude_turn_clock_follows_conversation_records) {
  ClaudeRecord r = {0}; parse_text(HB_PROMPT HB_CALL_TEXT HB_RESULT("synthetic-hb", "false"), &r);
  ASSERT_EQ(1577836802000LL, r.turns[0]->last_ms.value); claude_record_destroy(&r);
  parse_text(HB_PROMPT "{\"type\":\"user\",\"timestamp\":\"2020-01-01T00:00:04Z\",\"message\":{\"content\":\"[Request interrupted by user]\"}}\n", &r);
  ASSERT_EQ(1577836804000LL, r.turns[0]->last_ms.value); claude_record_destroy(&r);
  parse_text(HB_PROMPT CLOCK_ERROR, &r); ASSERT_EQ(1577836804000LL, r.turns[0]->last_ms.value); claude_record_destroy(&r);
}
TEST(claude_queued_prompt_steers_open_turn) {
  ClaudeRecord r = {0}; parse_text(HB_PROMPT HB_CALL_TEXT HB_RESULT("synthetic-hb", "false") CLOCK_DEQUEUE CLOCK_NEXT, &r);
  ASSERT_TRUE(str_equal(r.turns[0]->end_kind, STR_LIT("steered")));
  ASSERT_EQ(1577836802000LL, r.turns[0]->end_ms.value);
  ASSERT_EQ(1, *(__int128 *)omap_get(&r.tools[0].other, STR_LIT("SubagentHandback"))); claude_record_destroy(&r);
}
TEST(claude_queued_completed_not_steered) { clock_kind(HB_PROMPT HB_TEXT CLOCK_DEQUEUE CLOCK_NEXT, "completed"); }
TEST(claude_queued_without_dequeue_not_steered) { clock_kind(HB_PROMPT CLOCK_ASSIST CLOCK_NEXT, "open"); }
TEST(claude_queued_assistant_clears_dequeue) { clock_kind(HB_PROMPT CLOCK_ASSIST CLOCK_DEQUEUE CLOCK_ASSIST CLOCK_NEXT, "open"); }
/* Reply-less commands now complete even when a queued prompt follows. */
TEST(claude_queued_command_without_assistant) { clock_kind("{\"type\":\"user\",\"message\":{\"content\":\"<command-name>/synthetic\"}}\n" CLOCK_DEQUEUE CLOCK_NEXT, "completed"); }
TEST(claude_queued_stop_hook_not_steered) { clock_kind(HB_PROMPT CLOCK_ASSIST CLOCK_DEQUEUE CLOCK_STOP CLOCK_NEXT, "open"); }
TEST(claude_queued_interrupted_precedence) { clock_kind(HB_PROMPT CLOCK_ASSIST CLOCK_DEQUEUE "{\"type\":\"user\",\"message\":{\"content\":\"[Request interrupted by user]\"}}\n" CLOCK_NEXT, "interrupted"); }
TEST(claude_queued_api_error_precedence) { clock_kind(HB_PROMPT CLOCK_ASSIST CLOCK_DEQUEUE CLOCK_ERROR CLOCK_NEXT, "aborted"); }
TEST(claude_subagent_null_text_ending_completes) { ClaudeRecord r={0}; parse_subagent_text(HB_PROMPT CLOCK_NULL_TEXT,&r); ASSERT_TRUE(str_equal(r.turns[0]->end_kind,STR_LIT("completed"))); claude_record_destroy(&r); }
TEST(claude_subagent_null_text_later_tool_open) { ClaudeRecord r={0}; parse_subagent_text(HB_PROMPT CLOCK_NULL_TEXT HB_UNRESOLVED,&r); ASSERT_TRUE(str_equal(r.turns[0]->end_kind,STR_LIT("open"))); claude_record_destroy(&r); }
TEST(claude_subagent_absent_stop_open) { ClaudeRecord r={0}; parse_subagent_text(HB_PROMPT "{\"type\":\"assistant\",\"message\":{\"content\":[{\"type\":\"text\",\"text\":\"synthetic\"}]}}\n",&r); ASSERT_TRUE(str_equal(r.turns[0]->end_kind,STR_LIT("open"))); claude_record_destroy(&r); }
TEST(claude_subagent_null_thinking_open) { ClaudeRecord r={0}; parse_subagent_text(HB_PROMPT "{\"type\":\"assistant\",\"message\":{\"stop_reason\":null,\"content\":[{\"type\":\"thinking\"}]}}\n",&r); ASSERT_TRUE(str_equal(r.turns[0]->end_kind,STR_LIT("open"))); claude_record_destroy(&r); }
TEST(claude_main_null_text_open) { clock_kind(HB_PROMPT CLOCK_NULL_TEXT,"open"); }
TEST(claude_subagent_null_text_and_tool_open) { ClaudeRecord r={0}; parse_subagent_text(HB_PROMPT "{\"type\":\"assistant\",\"message\":{\"stop_reason\":null,\"content\":[{\"type\":\"text\",\"text\":\"synthetic\"},{\"type\":\"tool_use\",\"name\":\"Read\"}]}}\n",&r); ASSERT_TRUE(str_equal(r.turns[0]->end_kind,STR_LIT("open"))); claude_record_destroy(&r); }

#define ORIGIN(kind, extra, body) "{\"type\":\"user\",\"timestamp\":\"2020-01-01T00:00:10Z\",\"turnOrigin\":\"" kind "\"," extra "\"message\":{\"content\":\"" body "\"}}\n"
#define TOOL "{\"type\":\"assistant\",\"timestamp\":\"2020-01-01T00:00:11Z\",\"message\":{\"stop_reason\":\"end_turn\",\"content\":[{\"type\":\"tool_use\",\"name\":\"Read\"}]}}\n"
TEST(claude_turn_origin_starts_turns) {
  ClaudeRecord r={0}; parse_text(ORIGIN("task_notification", "", "Synthetic notification") TOOL ORIGIN("peer", "\"isMeta\":true,", "Synthetic peer") TOOL ORIGIN("sdk", "", "<system-reminder>synthetic context</system-reminder> Synthetic prompt") TOOL ORIGIN("other", "", "<command-name>/synthetic</command-name>") TOOL, &r);
  ASSERT_EQ(4, r.turn_count);
  const char *kinds[]={"notification","peer","text","command"};
  for(size_t i=0;i<4;i++) { ASSERT_TRUE(str_equal(r.requests[i].kind,(Str){kinds[i],(uint32_t)strlen(kinds[i])})); ASSERT_EQ(1,*(__int128 *)omap_get(&r.tools[i].other,STR_LIT("Read"))); }
  ASSERT_TRUE(str_equal(r.requests[2].text,STR_LIT("Synthetic prompt"))); claude_record_destroy(&r);
}
TEST(claude_turn_origin_compact_summary_continues) { ClaudeRecord r={0}; parse_text(HB_PROMPT ORIGIN("peer", "\"isCompactSummary\":true,", "Synthetic summary"),&r); ASSERT_EQ(1,r.turn_count); claude_record_destroy(&r); }
#define NOTICE "{\"type\":\"user\",\"timestamp\":\"2020-01-01T00:00:10Z\",\"message\":{\"content\":\"<task-notification>synthetic</task-notification>\"}}\n"
TEST(claude_task_notification_tag_after_completion) { ClaudeRecord r={0}; parse_text(HB_PROMPT HB_TEXT NOTICE,&r); ASSERT_EQ(2,r.turn_count); ASSERT_TRUE(str_equal(r.requests[1].kind,STR_LIT("notification"))); claude_record_destroy(&r); }
TEST(claude_task_notification_tag_first_record) { ClaudeRecord r={0}; parse_text(NOTICE,&r); ASSERT_EQ(1,r.turn_count); ASSERT_TRUE(str_equal(r.requests[0].kind,STR_LIT("notification"))); claude_record_destroy(&r); }
TEST(claude_task_notification_tag_mid_turn) { ClaudeRecord r={0}; parse_text(HB_PROMPT HB_UNRESOLVED NOTICE,&r); ASSERT_EQ(1,r.turn_count); claude_record_destroy(&r); }
#define RESUME "{\"type\":\"user\",\"isMeta\":true,\"timestamp\":\"2020-01-01T00:00:10Z\",\"origin\":{\"kind\":\"coordinator\"},\"message\":{\"content\":\"Synthetic resume\"}}\n"
TEST(claude_subagent_coordinator_resume_starts_turn) { ClaudeRecord r={0}; parse_subagent_text(HB_PROMPT RESUME,&r); ASSERT_EQ(2,r.turn_count); ASSERT_TRUE(str_equal(r.requests[1].kind,STR_LIT("resume"))); claude_record_destroy(&r); parse_text(HB_PROMPT RESUME,&r); ASSERT_EQ(1,r.turn_count); claude_record_destroy(&r); }
#define API_FAILURE "{\"type\":\"assistant\",\"isApiErrorMessage\":true,\"timestamp\":\"2020-01-01T00:00:01Z\",\"message\":{\"stop_reason\":\"end_turn\",\"content\":\"Synthetic error\"}}\n"
TEST(claude_api_error_message_aborts_turn) { clock_kind(HB_PROMPT API_FAILURE,"aborted"); }
TEST(claude_api_error_message_then_reply_completes) { clock_kind(HB_PROMPT API_FAILURE HB_TEXT,"completed"); }
TEST(claude_command_without_reply_completes) { clock_kind("{\"type\":\"user\",\"timestamp\":\"2020-01-01T00:00:00Z\",\"message\":{\"content\":\"<command-name>/synthetic</command-name>\"}}\n","completed"); }
TEST(claude_text_without_reply_stays_open) { clock_kind(HB_PROMPT,"open"); }
TEST(claude_wakeup_turn_clock_excludes_wait) { ClaudeRecord r={0}; parse_text(HB_PROMPT HB_TEXT ORIGIN("peer", "\"isMeta\":true,", "Synthetic wakeup") TOOL,&r); ASSERT_EQ(2,r.turn_count); ASSERT_EQ(1577836803000LL,r.turns[0]->end_ms.value); ASSERT_EQ(1577836810000LL,r.turns[1]->start_ms.value); ASSERT_EQ(1577836811000LL,r.turns[1]->end_ms.value); claude_record_destroy(&r); }
TEST(claude_title_skips_agent_requests) {
  ClaudeRecord records[2]={0};
  parse_text(ORIGIN("peer", "\"isMeta\":true,", "Synthetic agent") HB_PROMPT, &records[0]);
  parse_text(ORIGIN("task_notification", "", "Synthetic notification"), &records[1]);
  records[0].id=STR_LIT("synthetic-title"); records[1].id=STR_LIT("synthetic-filename");
  Corpus c={0}; CorpusStrings collisions={0};
  ASSERT_EQ(ERR_OK,claude_corpus_add(records,2,0,&c,&collisions).code);
  SessionModel *first=omap_get(&c.sessions,records[0].id), *second=omap_get(&c.sessions,records[1].id);
  ASSERT_TRUE(str_equal(first->title_full,STR_LIT("Synthetic request")));
  ASSERT_TRUE(str_equal(second->title_full,STR_LIT("synthetic-filename")));
  ASSERT_TRUE(str_equal(second->title_source,STR_LIT("filename")));
  corpus_destroy(&c); claude_record_destroy(&records[0]); claude_record_destroy(&records[1]);
}

static void parse_fork_text(const char *rows, ClaudeRecord *r) {
  char path[1024]; snprintf(path, sizeof path, "%s/synthetic-fork.jsonl", getenv("COLOPHON_HOME"));
  FILE *f=fopen(path,"w"); ASSERT_TRUE(f); ASSERT_TRUE(fputs(rows,f)>=0); ASSERT_EQ(0,fclose(f));
  DiscoveredLog key={.path={path,(uint32_t)strlen(path)},.size=(int64_t)strlen(rows)};
  ASSERT_EQ(ERR_OK,claude_parse(&key,STR_LIT("/synthetic/projects"),(Str){0},r).code); ASSERT_EQ(0,unlink(path));
}
TEST(claude_fork_transition_discards_inherited) {
  ClaudeRecord r={0}; parse_fork_text(
    "{\"type\":\"custom-title\",\"sessionId\":\"synthetic-source\",\"customTitle\":\"Synthetic inherited title\",\"timestamp\":\"2020-01-01T00:00:00Z\"}\n"
    "{\"type\":\"user\",\"message\":{\"content\":\"Synthetic inherited request\"}}\n"
    "{\"type\":\"assistant\",\"message\":{\"stop_reason\":\"end_turn\",\"content\":[{\"type\":\"tool_use\",\"name\":\"Bash\",\"id\":\"synthetic-old\"}]}}\n"
    "{\"type\":\"user\",\"sessionId\":\"synthetic-fork\",\"timestamp\":\"2020-01-01T00:00:10Z\",\"message\":{\"content\":\"Synthetic own request\"}}\n"
    "{\"type\":\"assistant\",\"timestamp\":\"2020-01-01T00:00:11Z\",\"message\":{\"stop_reason\":\"end_turn\",\"content\":\"Synthetic own answer\"}}\n",&r);
  ASSERT_EQ(1,r.turn_count); ASSERT_TRUE(str_equal(r.meta.forked_from_id,STR_LIT("synthetic-source")));
  ASSERT_TRUE(str_equal(r.requests[0].text,STR_LIT("Synthetic own request"))); ASSERT_EQ(0,r.tools[0].shell);
  ASSERT_EQ(0,r.tool_turns.size); ASSERT_EQ(0,r.custom_title.n); ASSERT_EQ(1577836810000LL,r.first_ms.value);
  Corpus c={0}; CorpusStrings collisions={0}; ASSERT_EQ(ERR_OK,claude_corpus_add(&r,1,0,&c,&collisions).code);
  SessionModel *s=omap_get(&c.sessions,r.id); ASSERT_TRUE(str_equal(s->forked_from,STR_LIT("synthetic-source")));
  ASSERT_FALSE(s->flags & F_FORKED); ASSERT_TRUE(str_equal(s->title_full,STR_LIT("Synthetic own request")));
  corpus_destroy(&c); claude_record_destroy(&r);
}
TEST(claude_fork_of_fork_parent) {
  ClaudeRecord r={0}; parse_fork_text("{\"type\":\"progress\",\"sessionId\":\"synthetic-grandparent\"}\n{\"type\":\"progress\",\"sessionId\":\"synthetic-parent\"}\n{\"type\":\"progress\",\"sessionId\":\"synthetic-fork\"}\n",&r);
  ASSERT_TRUE(str_equal(r.meta.forked_from_id,STR_LIT("synthetic-parent"))); claude_record_destroy(&r);
}
TEST(claude_foreign_only_transcript_is_not_fork) {
  ClaudeRecord r={0}; parse_fork_text("{\"type\":\"user\",\"sessionId\":\"synthetic-source\",\"message\":{\"content\":\"Synthetic alias\"}}\n",&r);
  ASSERT_EQ(1,r.turn_count); ASSERT_EQ(0,r.meta.forked_from_id.n); ASSERT_EQ(1,r.aliases.count); claude_record_destroy(&r);
}
TEST(claude_session_end_uses_turn_clock) {
  ClaudeRecord r={0}; parse_text(HB_PROMPT HB_TEXT CLOCK_DEQUEUE "{\"type\":\"pr-link\",\"timestamp\":\"2020-01-01T00:00:05Z\"}\n",&r);
  Corpus c={0}; CorpusStrings collisions={0}; ASSERT_EQ(ERR_OK,claude_corpus_add(&r,1,0,&c,&collisions).code);
  SessionModel *s=omap_get(&c.sessions,r.id); ASSERT_EQ(1577836803000LL,s->end_ms.value);
  corpus_destroy(&c); claude_record_destroy(&r);
}
TEST(claude_diagnostic_known_types) {
  const char *names[]={"attachment","atis-latch","api-request","api-request-shape","api-request-blob","agent-name","cost-state","tools-used","mode","file-history-delta","artifact-comment-monitor","artifact-autoreact-ledger","bridge-session","frame-link","permission-mode","session-owner","relocated","worktree-state"};
  for(size_t i=0;i<sizeof names/sizeof *names;i++) ASSERT_TRUE(claude_known_type((Str){names[i],(uint32_t)strlen(names[i])}));
  ASSERT_FALSE(claude_known_type(STR_LIT("retained_context")));
}
TEST(codex_diagnostic_known_types) {
  const char *names[]={"response_item/additional_tools","response_item/configuration_update","event_msg/item_completed/HookPrompt","event_msg/item_completed/FunctionCallOutput"};
  for(size_t i=0;i<sizeof names/sizeof *names;i++) ASSERT_TRUE(record_type_known((Str){names[i],(uint32_t)strlen(names[i])}));
  ASSERT_FALSE(record_type_known(STR_LIT("retained_context")));
}
