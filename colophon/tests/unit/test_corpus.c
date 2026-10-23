#define _DARWIN_C_SOURCE
#include "corpus/turnstatus.h"
#include "corpus/workspaces.h"
#include "out/session_payload.h"
#include "runner.h"
#include "util/events.h"
#include "util/json_number.h"
#include "util/json_read.h"
#include <ftw.h>
#include <stdalign.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>
TEST(corpus_payload_wide_notes_once_before_repeated_rendering) {
  event_flush(NULL);
  Intern intern;
  ASSERT_EQ(ERR_OK, intern_init(&intern).code);
  LogRecord records[2] = {{.status = STR_LIT("empty"),
                           .key = {.path = STR_LIT("/synthetic/first.jsonl")},
                           .reader = {.malformed = INT64_MAX}},
                          {.status = STR_LIT("empty"),
                           .key = {.path = STR_LIT("/synthetic/second.jsonl")},
                           .reader = {.malformed = INT64_MAX}}};
  AssemblyRecord inputs[2] = {{.record = &records[0]}, {.record = &records[1]}};
  CodexMetadata metadata = {0};
  Corpus corpus = {0};
  ASSERT_EQ(ERR_OK,
            corpus_build(inputs, 2, &metadata, 0, &intern, &corpus).code);
  JsonWriter writer = {0};
  for (size_t i = 0; i < 3; i++) {
    payload_file_diagnostic(&writer, &corpus.malformed);
    jsonw_free(&writer);
    jsonw_i128(&writer, (__int128)INT64_MAX * 3);
    jsonw_free(&writer);
  }
  char directory[] = "/tmp/colophon-corpus-events.XXXXXX";
  ASSERT_TRUE(mkdtemp(directory));
  event_flush(directory);
  char path[128];
  snprintf(path, sizeof path, "%s/native-events.jsonl", directory);
  FILE *file = fopen(path, "r");
  ASSERT_TRUE(file);
  char line[512];
  ASSERT_TRUE(fgets(line, sizeof line, file));
  JsonRead parsed = json_read((Str){line, (uint32_t)strlen(line)}, BYTES,
                              JSON_CONSTANTS_REJECT, "test.events");
  ASSERT_EQ(JSON_OK, parsed.status);
  yyjson_val *event = yyjson_doc_get_root(parsed.doc);
  ASSERT_STREQ("int128_payload_sum",
               yyjson_get_str(yyjson_obj_get(event, "event")));
  ASSERT_STREQ("diagnostics.malformed_lines.total",
               yyjson_get_str(yyjson_obj_get(event, "site")));
  PyNum count;
  ASSERT_TRUE(
      json_number(yyjson_obj_get(event, "count"), "test.events.count", &count));
  ASSERT_FALSE(count.is_float);
  ASSERT_EQ(1, count.i);
  ASSERT_FALSE(fgets(line, sizeof line, file));
  fclose(file);
  json_read_free(&parsed);
  ASSERT_EQ(0, unlink(path));
  ASSERT_EQ(0, rmdir(directory));
  corpus_destroy(&corpus);
  metadata_destroy(&metadata);
  intern_destroy(&intern);
}
TEST(corpus_aggregate_objects_have_typed_alignment) {
  Intern intern;
  ASSERT_EQ(ERR_OK, intern_init(&intern).code);
  LogRecord record = {.status = STR_LIT("ok"),
                      .key = {.path = STR_LIT("/synthetic/file.jsonl")}};
  AssemblyRecord input = {.record = &record};
  CodexMetadata metadata = {0};
  Corpus corpus = {0};
  ASSERT_EQ(ERR_OK,
            corpus_build(&input, 1, &metadata, 0, &intern, &corpus).code);
  ASSERT_TRUE(corpus.sessions.first);
  ASSERT_EQ(0, (uintptr_t)corpus.sessions.first->value % alignof(SessionModel));
  corpus_destroy(&corpus);
  metadata_destroy(&metadata);
  intern_destroy(&intern);
}
TEST(corpus_numeric_order_is_exact_and_antisymmetric) {
  const PyNum integer = {.i = 9007199254740993LL},
              rounded = {.is_float = true, .f = 9007199254740992.0};
  ASSERT_EQ(1, corpus_number_compare(integer, rounded));
  ASSERT_EQ(-1, corpus_number_compare(rounded, integer));
  ASSERT_EQ(1, corpus_number_compare(
                   (PyNum){.i = INT64_MAX},
                   (PyNum){.is_float = true, .f = 9223372036854774784.0}));
  ASSERT_EQ(-1, corpus_number_compare(
                    (PyNum){.i = INT64_MAX},
                    (PyNum){.is_float = true, .f = 9223372036854775808.0}));
  ASSERT_EQ(-1, corpus_number_compare((PyNum){.i = -2},
                                      (PyNum){.is_float = true, .f = -1.5}));
  ASSERT_EQ(1, corpus_number_compare((PyNum){.is_float = true, .f = -1.5},
                                     (PyNum){.i = -2}));
}
TEST(corpus_link_resets_annotations_and_derives_production_clocks) {
  Intern intern;
  ASSERT_EQ(ERR_OK, intern_init(&intern).code);
  TurnFact fact = {.key = STR_LIT("synthetic-turn"),
                   .turn_id = STR_LIT("synthetic-logged-turn"),
                   .start_ms = {true, 0},
                   .end_ms = {true, 10},
                   .end_kind = STR_LIT("completed")};
  TurnFact *turns[] = {&fact};
  SpawnLink spawn = {.task_name = STR_LIT("/root/synthetic-worker"),
                     .turn_key = STR_LIT("synthetic-turn"),
                     .at_ms = {true, 5}};
  LogRecord records[2] = {
      {.status = STR_LIT("ok"),
       .has_meta = true,
       .key = {.path = STR_LIT("/synthetic/parent.jsonl")},
       .meta = {.id = STR_LIT("synthetic-parent")},
       .turns = turns,
       .turn_count = 1,
       .spawns = &spawn,
       .spawn_count = 1},
      {.status = STR_LIT("ok"),
       .has_meta = true,
       .key = {.path = STR_LIT("/synthetic/child.jsonl")},
       .meta = {.id = STR_LIT("synthetic-child"),
                .is_subagent = true,
                .created_at_ms = {true, 5},
                .parent_thread_id = {.kind = JS_STRING,
                                     .value.s = STR_LIT("synthetic-parent")},
                .agent_path = {.kind = JS_STRING,
                               .value.s = STR_LIT("/root/synthetic-worker")}}}};
  AssemblyRecord inputs[] = {assembly_record(&records[0]),
                             assembly_record(&records[1])};
  Corpus corpus = {0};
  CodexMetadata metadata = {0};
  ASSERT_EQ(ERR_OK,
            corpus_build(inputs, 2, &metadata, 20, &intern, &corpus).code);
  SessionModel *parent =
      omap_get(&corpus.sessions, STR_LIT("synthetic-parent"));
  SessionModel *child = omap_get(&corpus.sessions, STR_LIT("synthetic-child"));
  for (size_t i = 0; i < 2; i++) {
    ASSERT_EQ(ERR_OK, corpus_link_subagents(&corpus, &metadata, 20).code);
    ASSERT_EQ(1, parent->children.count);
    ASSERT_EQ(1, parent->turns[0].spawned.count);
    ASSERT_EQ(1, child->depth);
    ASSERT_TRUE(child->created_at_ms.present);
    ASSERT_EQ(5, child->created_at_ms.value.i);
    ASSERT_STREQ("spawn_call", child->link_method.p);
  }
  Str missing = STR_LIT("synthetic-missing");
  ASSERT_EQ(ERR_OK, omap_put(&metadata.spawn_parents,
                             STR_LIT("synthetic-child"), &missing)
                        .code);
  ASSERT_EQ(ERR_OK, corpus_link_subagents(&corpus, &metadata, 20).code);
  ASSERT_EQ(0, parent->children.count);
  ASSERT_EQ(0, parent->turns[0].spawned.count);
  ASSERT_EQ(1, corpus.orphaned_subagents.count);
  ASSERT_FALSE(child->has_depth);
  ASSERT_STREQ("synthetic-missing", child->parent_id.p);
  corpus_destroy(&corpus);
  metadata_destroy(&metadata);
  intern_destroy(&intern);
}
TEST(corpus_rejects_misaligned_typed_spawn_clocks) {
  Intern intern;
  ASSERT_EQ(ERR_OK, intern_init(&intern).code);
  LogRecord record = {.status = STR_LIT("ok"),
                      .key = {.path = STR_LIT("/synthetic/clock.jsonl")}};
  AssemblyRecord input = assembly_record(&record);
  input.typed_clocks = true;
  input.spawn_clock_count = 1;
  Corpus corpus = {0};
  CodexMetadata metadata = {0};
  ASSERT_EQ(ERR_INVALID,
            corpus_build(&input, 1, &metadata, 0, &intern, &corpus).code);
  corpus_destroy(&corpus);
  record.spawn_count = 1;
  ASSERT_EQ(ERR_INVALID,
            corpus_build(&input, 1, &metadata, 0, &intern, &corpus).code);
  corpus_destroy(&corpus);
  metadata_destroy(&metadata);
  intern_destroy(&intern);
}
TEST(corpus_workspace_owns_alias_names_after_alias_teardown) {
  Intern intern;
  ASSERT_EQ(ERR_OK, intern_init(&intern).code);
  LogRecord record = {
      .status = STR_LIT("ok"),
      .key = {.path = STR_LIT("/synthetic/workspace.jsonl")},
      .meta = {.cwd = {.kind = JS_STRING,
                       .value.s = STR_LIT("/synthetic/project/nested")}}};
  AssemblyRecord input = assembly_record(&record);
  Corpus corpus = {0};
  CodexMetadata metadata = {0};
  ASSERT_EQ(ERR_OK,
            corpus_build(&input, 1, &metadata, 0, &intern, &corpus).code);
  Str data =
      STR_LIT("[{\"name\":\"Synthetic owned "
              "alias\",\"origins\":[],\"paths\":[\"/synthetic/project\"]}]");
  JsonRead read = json_read(data, BYTES, JSON_CONSTANTS_ALLOW, "test.aliases");
  ASSERT_EQ(JSON_OK, read.status);
  WorkspaceAliases aliases = {0};
  ASSERT_EQ(ERR_OK, workspace_aliases_decode(yyjson_doc_get_root(read.doc),
                                             false, "test.aliases", &aliases)
                        .code);
  json_read_free(&read);
  ASSERT_EQ(ERR_OK, corpus_resolve_workspaces(&corpus, &aliases).code);
  workspace_aliases_destroy(&aliases);
  JsonWriter writer = {0};
  payload_workspaces(&writer, &corpus);
  ASSERT_STREQ("{\"alias:Synthetic owned alias\":{\"name\":\"Synthetic owned "
               "alias\",\"kind\":\"alias\",\"keys\":[\"/synthetic/project/"
               "nested\"],\"alias\":\"Synthetic owned alias\"}}",
               writer.data);
  jsonw_free(&writer);
  corpus_destroy(&corpus);
  metadata_destroy(&metadata);
  intern_destroy(&intern);
}
static void workspace_write(const char *path, const char *text) {
  FILE *file = fopen(path, "w");
  ASSERT_TRUE(file);
  ASSERT_TRUE(fputs(text, file) >= 0);
  ASSERT_EQ(0, fclose(file));
}
static int workspace_remove(const char *path, const struct stat *st, int flag,
                            struct FTW *ftw) {
  (void)st, (void)flag, (void)ftw;
  return remove(path);
}
static LogRecord workspace_session(const char *id, const char *cwd,
                                   const char *origin) {
  LogRecord record = {
      .status = STR_LIT("ok"),
      .has_meta = true,
      .key = {.path = {id, (uint32_t)strlen(id)}},
      .meta = {.id = {id, (uint32_t)strlen(id)},
               .cwd = {.kind = JS_STRING,
                       .value.s = {cwd, (uint32_t)strlen(cwd)}}}};
  if (origin)
    record.meta.origin_url = (JScalar){
        .kind = JS_STRING, .value.s = {origin, (uint32_t)strlen(origin)}};
  return record;
}
TEST(corpus_workspace_reads_origin_from_repository_config) {
  /* Codex records the remote; Claude/OpenCode record only cwd. Both resolve
   * to one workspace, including linked and since-deleted worktrees. */
  char base[512], repo[600], sub[700], linked[600], gone[700], plain[600],
      loose[700], path[800];
  snprintf(base, sizeof base, "%s/synthetic-workspaces-XXXXXX",
           getenv("TMPDIR") ? getenv("TMPDIR") : "/tmp");
  ASSERT_TRUE(mkdtemp(base));
  snprintf(repo, sizeof repo, "%s/repo", base);
  snprintf(sub, sizeof sub, "%s/nested", repo);
  snprintf(linked, sizeof linked, "%s/linked", base);
  snprintf(gone, sizeof gone, "%s/.claude/worktrees/removed", repo);
  snprintf(plain, sizeof plain, "%s/plain", base);
  snprintf(loose, sizeof loose, "%s/removed/deeper", base);
  const char *dirs[] = {repo, sub, linked, plain};
  for (size_t i = 0; i < 4; i++)
    ASSERT_EQ(0, mkdir(dirs[i], 0700));
  const char *repo_dirs[] = {"/.git", "/.git/worktrees",
                             "/.git/worktrees/linked", "/.claude",
                             "/.claude/worktrees"};
  for (size_t i = 0; i < 5; i++) {
    snprintf(path, sizeof path, "%s%s", repo, repo_dirs[i]);
    ASSERT_EQ(0, mkdir(path, 0700));
  }
  snprintf(path, sizeof path, "%s/.git", plain);
  ASSERT_EQ(0, mkdir(path, 0700));
  snprintf(path, sizeof path, "%s/.git/config", plain);
  workspace_write(path, "[core]\n\tbare = false\n");
  snprintf(path, sizeof path, "%s/.git/config", repo);
  workspace_write(path, "[core]\n\tbare = false\n"
                        "[remote \"upstream\"]\n"
                        "\turl = https://example.invalid/other/upstream.git\n"
                        "; comment line\n"
                        "[Remote \"origin\"]\n"
                        "\tfetch = +refs/heads/*:refs/remotes/origin/*\n"
                        "\tURL = \"git@github.com:synthetic-owner/"
                        "synthetic-repo.git\" # trailing comment\r\n");
  snprintf(path, sizeof path, "%s/.git/worktrees/linked/commondir", repo);
  workspace_write(path, "../..\n");
  /* A linked worktree's gitdir is relative to the worktree, not to cwd. */
  snprintf(path, sizeof path, "%s/.git", linked);
  workspace_write(path, "gitdir: ../repo/.git/worktrees/linked\n");
  Intern intern;
  ASSERT_EQ(ERR_OK, intern_init(&intern).code);
  LogRecord records[] = {
      workspace_session("synthetic-codex", sub,
                        "https://github.com/synthetic-owner/synthetic-repo"),
      workspace_session("synthetic-claude", repo, NULL),
      workspace_session("synthetic-linked", linked, NULL),
      workspace_session("synthetic-removed", gone, NULL),
      workspace_session("synthetic-plain", plain, NULL),
      workspace_session("synthetic-loose", loose, NULL)};
  AssemblyRecord inputs[6];
  for (size_t i = 0; i < 6; i++)
    inputs[i] = assembly_record(&records[i]);
  Corpus corpus = {0};
  CodexMetadata metadata = {0};
  ASSERT_EQ(ERR_OK,
            corpus_build(inputs, 6, &metadata, 0, &intern, &corpus).code);
  WorkspaceAliases aliases = {0};
  ASSERT_EQ(ERR_OK, corpus_resolve_workspaces(&corpus, &aliases).code);
  Str origin =
      STR_LIT("origin:https://github.com/synthetic-owner/synthetic-repo");
  const char *same[] = {"synthetic-codex", "synthetic-claude",
                        "synthetic-linked", "synthetic-removed"};
  for (size_t i = 0; i < 4; i++) {
    SessionModel *s =
        omap_get(&corpus.sessions, (Str){same[i], (uint32_t)strlen(same[i])});
    ASSERT_TRUE(s);
    ASSERT_TRUE(str_equal(origin, s->workspace));
  }
  SessionModel *removed =
      omap_get(&corpus.sessions, STR_LIT("synthetic-removed"));
  ASSERT_TRUE(
      str_equal(STR_LIT(".claude/worktrees/removed"), removed->subfolder));
  Workspace *w = omap_get(&corpus.workspaces, origin);
  ASSERT_TRUE(w);
  ASSERT_TRUE(str_equal(STR_LIT("synthetic-repo"), w->name));
  ASSERT_TRUE(str_equal(STR_LIT("origin"), w->kind));
  SessionModel *plain_session =
      omap_get(&corpus.sessions, STR_LIT("synthetic-plain"));
  ASSERT_TRUE(!strncmp("git:", plain_session->workspace.p, 4));
  SessionModel *loose_session =
      omap_get(&corpus.sessions, STR_LIT("synthetic-loose"));
  ASSERT_TRUE(!strncmp("cwd:", loose_session->workspace.p, 4));
  ASSERT_EQ(3, corpus.workspaces.size);
  corpus_destroy(&corpus);
  metadata_destroy(&metadata);
  intern_destroy(&intern);
  ASSERT_EQ(0, nftw(base, workspace_remove, 16, FTW_DEPTH | FTW_PHYS));
}
