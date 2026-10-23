#ifndef CP_WORKSPACES_H
#define CP_WORKSPACES_H
#include "subagents.h"
#include "util/json_read.h"
/* Alias facts own their strings in arena; resolve copies retained names, so
 * aliases may be destroyed immediately after resolution. The corpus owns all
 * workspace strings/maps and never borrows the alias owner. */
typedef struct {
  Str name;
  CorpusStrings origins, paths, raw_origins, raw_paths;
} WorkspaceAlias;
typedef struct {
  Arena arena;
  WorkspaceAlias *items;
  size_t count;
  CorpusStrings errors;
} WorkspaceAliases;
typedef struct {
  Str name, kind, alias;
  CorpusStrings keys;
} Workspace;
Err workspace_origin(Arena *arena, Str raw, Str *out);
Err workspace_path(Arena *arena, Str raw, Str *out);
/* Nearest repository containing cwd; a missing cwd searches from its nearest
 * existing ancestor. */
Err workspace_git_root(Arena *arena, Str cwd, Str *out);
/* Normalized remote "origin" url from root's git config (following a linked
 * worktree to its common directory), or empty when absent or unreadable. */
Err workspace_git_origin(Arena *arena, Str root, Str *out);
Err workspace_aliases_decode(yyjson_val *root, bool file_schema,
                             const char *path, WorkspaceAliases *out);
Err workspace_aliases_load(const char *path, WorkspaceAliases *out);
void workspace_aliases_destroy(WorkspaceAliases *aliases);
Err corpus_resolve_workspaces(Corpus *corpus, const WorkspaceAliases *aliases);
void corpus_workspaces_destroy(Corpus *corpus);
#endif
