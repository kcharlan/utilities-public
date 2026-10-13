#ifndef CP_TITLES_H
#define CP_TITLES_H
#include "assemble.h"
typedef struct {
  JScalar json;
  MetadataValue bytes;
  bool is_bytes;
} TitleCandidate;
Str title_candidate_text(TitleCandidate candidate);
/* Callers pass only text evidence; arbitrary raw/SQL types yield empty Str. */
Str title_path_name(Str path, bool stem);
Err title_display(Arena *arena, Str full, Str *out);
Err title_subagent(Arena *arena, Str path, Str nickname, Str *out);
Err title_humanize(Arena *arena, Str path, Str *out);
void title_select(const Str candidates[7], Str cwd, Str identity, Str path,
                  Str *full, Str *source);
#endif
