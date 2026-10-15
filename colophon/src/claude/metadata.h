#ifndef CP_CLAUDE_METADATA_H
#define CP_CLAUDE_METADATA_H
#include "scan.h"
typedef struct {
  Str id, title, cwd;
  bool has_archived, archived;
  MaybeMs created, activity;
} ClaudeDesktop;
Err claude_sidecar_load(ClaudeRecord *record);
Err claude_metadata_load(ClaudeScan *scan);
Err claude_metadata_apply(ClaudeScan *scan, Corpus *corpus);
#endif
