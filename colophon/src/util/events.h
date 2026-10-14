#ifndef CP_EVENTS_H
#define CP_EVENTS_H
#include <stdint.h>
/* Sites contain schema field paths, never content values or Codex paths.
 * Thread-safe notes; flush drains the current run and is called by main only. */
void event_note(const char *type, const char *site, uint64_t count);
void event_flush(const char *home);
#endif
