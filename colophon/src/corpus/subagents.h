#ifndef CP_SUBAGENTS_H
#define CP_SUBAGENTS_H
#include "assemble.h"
Err corpus_strings_add(Arena *arena, CorpusStrings *list, Str value);
MaybeNum corpus_finite(JScalar value, const char *site);
/* Provider-neutral graph helpers; map keys are the caller's identities. */
Err corpus_graph_break_cycles(Arena *arena, Omap *identified);
Err corpus_children_order(SessionModel *session, Omap *by_id);
Err corpus_link_subagents(Corpus *corpus, const CodexMetadata *metadata,
                          int64_t snapshot_ms);
#endif
