#ifndef CP_ANTIGRAVITY_CORPUS_H
#define CP_ANTIGRAVITY_CORPUS_H
#include "db.h"
#include "corpus/assemble.h"
Err antigravity_corpus_add(AntigravityStore *store,int64_t snapshot,Corpus *corpus);
/* Explicit SQL INTEGER wins; otherwise a present payload scalar may supply the
 * fact. No absent scalar is promoted to a proto3 default. */
bool antigravity_step_enum(const AntigravityStep *step,bool status,int64_t *out);
/* Input is a retained validated wire message. Single occurrences borrow the
 * input; multiple singular-message occurrences merge in the supplied arena. */
Err antigravity_message_merge(Arena *arena,Str input,uint32_t number,Str *out);
Err antigravity_clock(Arena *arena,Str input,uint32_t number,MaybeMs *out);
#endif
