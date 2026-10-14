#ifndef CP_PRIORITY_H
#define CP_PRIORITY_H
#include "out/jsonw.h"
#include "util/omap.h"
#include <sqlite3.h>

typedef struct {
  Str thread_id, model, timestamp;
  int64_t first_seen_ms;
} PriorityEntry;
typedef struct PriorityMessage {
  Str text;
  struct PriorityMessage *next;
} PriorityMessage;
typedef struct {
  Arena arena;
  Omap turns; /* Retained source spelling -> arena-owned PriorityEntry. */
  PriorityMessage *messages, *last_message;
} PriorityTurns;
typedef struct {
  Str turn_id, thread_id, model, timestamp;
} PriorityTrace;
/* Zero-initialize output; always destroy, including on returned failures.
 * Optional memory/trace errors become messages. Required write/allocation
 * errors propagate. SQLite handles/statements close on every exit. */
Err priority_load(const char *codex_home, const char *home, PriorityTurns *out);
void priority_destroy(PriorityTurns *out);
void priority_turns_json(JsonWriter *writer, const Omap *turns);
/* Value/quoted borrow input. Parsers copy JSON models into caller's arena and
 * otherwise borrow input slices. Missing result is represented by NULL turn. */
Str priority_trace_value(Str name, Str text);
Str priority_trace_quoted(Str name, Str text);
Err priority_trace_parse(Arena *arena, Str timestamp, Str body,
                         PriorityTrace *out);
Err priority_completed_parse(Arena *arena, Str body, Str *turn, Str *model);
/* Converts the actual SQLite column_text C string using strict UTF-8 maximal
 * subpart replacement. SQLite owns input; returned text belongs to arena. */
Err priority_sqlite_text(Arena *arena, sqlite3_stmt *stmt, int column,
                         Str *out);
#endif
