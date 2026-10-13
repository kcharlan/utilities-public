#ifndef CP_SUBAGENTS_H
#define CP_SUBAGENTS_H
#include "assemble.h"
Err corpus_strings_add(Arena *arena, CorpusStrings *list, Str value);
MaybeNum corpus_finite(JScalar value, const char *site);
Err corpus_link_subagents(Corpus *corpus, const CodexMetadata *metadata,
                          int64_t snapshot_ms);
#endif
