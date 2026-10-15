#define _DARWIN_C_SOURCE
#include "claude/parse.h"
#include "runner.h"
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
