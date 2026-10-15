#ifndef CP_CLAUDE_STORE_H
#define CP_CLAUDE_STORE_H
#include "scan.h"
typedef struct ClaudeStored ClaudeStored;
typedef struct ClaudeStore {
  Arena arena;
  Str home;
  ClaudeStored *entries;
  size_t count, capacity;
  bool rebuild, inspected, committed;
} ClaudeStore;
/* All inspection and reconciliation are read-only. Commit is called only after
 * successful page output. No opened Codex state is used. */
Err claude_store_inspect(const char *home, ClaudeScan *scan, bool rebuild, ClaudeStore *store);
Err claude_store_get(ClaudeStore *store,const DiscoveredLog *key,ClaudeRecord *record,bool *hit);
Err claude_store_reconcile(ClaudeStore *store,ClaudeScan *scan,volatile sig_atomic_t *interrupted);
Err claude_store_commit(ClaudeStore *store,ClaudeScan *scan,volatile sig_atomic_t *interrupted);
/* Strict ENOENT plus readable/searchable surviving directory. */
bool claude_path_deleted(const char *path);
void claude_store_destroy(ClaudeStore *store);
#endif
