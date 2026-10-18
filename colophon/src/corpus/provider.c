#include "provider.h"
#include "turnstatus.h"

Str provider_id(Provider provider) {
  switch (provider) {
  case PROVIDER_CODEX: return STR_LIT("codex");
  case PROVIDER_CLAUDE: return STR_LIT("claude");
  case PROVIDER_OPENCODE: return STR_LIT("opencode");
  }
  return (Str){0};
}

void corpus_status_flags(SessionModel *session, Str status) {
  if (str_equal(status, STR_LIT("running")))
    session->flags |= F_LIVE;
  else if (str_equal(status, STR_LIT("abandoned")))
    session->flags |= F_ABANDONED;
  else if (str_equal(status, STR_LIT("aborted")))
    session->flags |= F_ABORTED;
  else if (str_equal(status, STR_LIT("interrupted")))
    session->flags |= F_INTERRUPTED;
}

Err corpus_session_idle(Arena *arena, SessionModel *session) {
  if (session->start_ms.present && session->end_ms.present) {
    MaybeNum active;
    Err e = active_interval_union(arena, session->turns, session->turn_count, &active);
    if (e.code)
      return e;
    if (active.present)
      session->idle_ms = (MaybeNum){
          true, {.i = session->end_ms.value - session->start_ms.value - active.value.i}};
  }
  return ERR_SUCCESS;
}
