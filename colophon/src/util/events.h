#ifndef CP_EVENTS_H
#define CP_EVENTS_H
#include <stdint.h>
#include <stdbool.h>
typedef struct EventCaptureItem EventCaptureItem;
typedef struct { EventCaptureItem *first, *last; bool lost; } EventCapture;
void event_capture_begin(EventCapture *capture);
void event_capture_end(void);
void event_capture_replay(EventCapture *capture);
void event_capture_destroy(EventCapture *capture);
/* Sites contain schema field paths, never content values or Codex paths.
 * Thread-safe notes; flush drains the current run and is called by main only. */
void event_note(const char *type, const char *site, uint64_t count);
void event_flush(const char *home);
#endif
