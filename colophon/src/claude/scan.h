#ifndef CP_CLAUDE_SCAN_H
#define CP_CLAUDE_SCAN_H
#include "cli/args.h"
#include "parse.h"
#include <signal.h>
typedef enum { CLAUDE_PROJECTS, CLAUDE_DESKTOP, CLAUDE_SWAP } ClaudeRootKind;
typedef struct {
  Str path;
  ClaudeRootKind kind;
  bool present, complete;
} ClaudeRoot;
typedef struct {
  Arena arena;
  ClaudeRoot *roots;
  size_t root_count;
  Str config_root, history_path, desktop_dir, resume_config_dir;
  bool disabled, present;
  size_t history_usable, history_malformed;
  ClaudeRecord *records;
  size_t count, capacity, logs, parsed;
  CorpusStrings collisions;
  Omap history_aliases; /* Exact alias -> scan-arena CorpusStrings of canonical
                           owners. */
  SkippedFile *skipped;
  size_t skipped_count, skipped_capacity;
} ClaudeScan;
/* Path selection and history inspection are read-only, before runtime creation.
 */
Err claude_inspect(const Args *args, ClaudeScan *out);
Err claude_scan(ClaudeScan *scan, volatile sig_atomic_t *interrupted);
void claude_scan_destroy(ClaudeScan *scan);
#endif
