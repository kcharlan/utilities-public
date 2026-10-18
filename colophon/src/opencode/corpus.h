#ifndef CP_OPENCODE_CORPUS_H
#define CP_OPENCODE_CORPUS_H
#include "db.h"
/* Call once after read and after other providers' corpus construction. The
 * store must outlive the corpus. Annotates accepted messages with inherited
 * and display-turn identity; leading messages retain an empty turn. Source
 * TurnFacts and diagnostics belong to the store; display models to corpus. */
Err opencode_corpus_add(OpencodeStore *store, int64_t snapshot, Corpus *corpus);
#endif
