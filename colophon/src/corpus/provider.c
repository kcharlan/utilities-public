#include "provider.h"
#include "turnstatus.h"

Str provider_id(Provider provider) {
  switch (provider) {
  case PROVIDER_CODEX: return STR_LIT("codex");
  case PROVIDER_CLAUDE: return STR_LIT("claude");
  case PROVIDER_OPENCODE: return STR_LIT("opencode");
  case PROVIDER_ANTIGRAVITY: return STR_LIT("antigravity");
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
    PyNum span, idle;
    if (active.present &&
        pynum_sub((PyNum){.i = session->end_ms.value},
                  (PyNum){.i = session->start_ms.value}, "session.idle", &span) &&
        pynum_sub(span, active.value, "session.idle", &idle)) {
      if (pynum_compare(idle, (PyNum){.i = 0}) < 0)
        idle = (PyNum){.i = 0};
      session->idle_ms = (MaybeNum){true, idle};
    }
  }
  return ERR_SUCCESS;
}
