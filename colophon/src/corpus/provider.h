#ifndef CP_PROVIDER_H
#define CP_PROVIDER_H
#include "assemble.h"

Str provider_id(Provider provider);
/* Copy source tool counts into an empty turn and accumulate session totals.
 * Map nodes are independently owned; wide values belong to the corpus arena.
 * Source facts must outlive the corpus's borrowed map keys. */
Err corpus_turn_tools_adopt(Arena *arena, SessionModel *session,
                           TurnModel *turn, const CorpusTools *source);
void corpus_status_flags(SessionModel *session, Str status);
Err corpus_session_idle(Arena *arena, SessionModel *session);
#endif
