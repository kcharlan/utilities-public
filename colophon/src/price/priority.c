#define _DARWIN_C_SOURCE
#include "priority.h"
#include "meta/metadata.h"
#include "model.h"
#include "parse/tokenstream.h"
#include "testing/hooks.h"
#include "util/atomic.h"
#include "util/fileio.h"
#include "util/json_number.h"
#include "util/json_read.h"
#include <errno.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

static Str text(const char *p) { return (Str){p, (uint32_t)strlen(p)}; }
static Str string(yyjson_val *v) {
  return yyjson_is_str(v)
             ? (Str){yyjson_get_str(v), (uint32_t)yyjson_get_len(v)}
             : (Str){0};
}
static Err copy_nullable(Arena *arena, Str value, Str *out) {
  if (!value.p) {
    *out = (Str){0};
    return ERR_SUCCESS;
  }
  return str_copy(arena, value, out);
}
static yyjson_val *first(yyjson_val *object, const char *name) {
  yyjson_obj_iter it = yyjson_obj_iter_with(object);
  yyjson_val *key;
  while ((key = yyjson_obj_iter_next(&it)))
    if (str_equal(string(key), text(name)))
      return yyjson_obj_iter_get_val(key);
  return NULL;
}
/* Every marker is ASCII, but both surrounding codepoints participate in
 * Swift Character literal matching. Return byte offset only at scalar starts.
 */
static size_t literal_parts(Str haystack, Str needle, Str suffix) {
  return price_literal_parts(haystack,needle,suffix,false);
}
static size_t literal(Str haystack, Str needle) {
  return literal_parts(haystack, needle, STR_LIT(""));
}
static Str slice(Str s, size_t start, size_t end) {
  return (Str){s.p + start, (uint32_t)(end - start)};
}
static Str marker_value(Str name, Str s, bool quoted) {
  Str suffix = quoted ? STR_LIT(": \"") : STR_LIT("=");
  size_t start = literal_parts(s, name, suffix),
         width = (size_t)name.n + suffix.n;
  if (start == SIZE_MAX)
    return (Str){0};
  start += width;
  Str tail = slice(s, start, s.n);
  if (quoted) {
    size_t end = literal(tail, STR_LIT("\""));
    return end == SIZE_MAX || !end ? (Str){0} : slice(tail, 0, end);
  }
  size_t offset = 0;
  uint32_t previous = 0, cp;
  while (offset < tail.n) {
    size_t end = offset;
    if (!str_decode_next(tail, &offset, &cp))
      break;
    bool control =
        (cp >= 9 && cp <= 13) || cp == 0x85 || cp == 0x2028 || cp == 0x2029;
    bool whitespace = cp != 0x200b && token_foundation_space(cp) &&
                      (control || !end || !price_character_prepend(previous));
    bool delimiter =
        cp < 128 && cp && strchr(",])}:", (int)cp) &&
        literal(slice(tail, end, tail.n), slice(tail, end, offset)) == 0 &&
        !price_character_prepend(previous);
    if (whitespace || delimiter)
      return end ? slice(tail, 0, end) : (Str){0};
    previous = cp;
  }
  return tail.n ? tail : (Str){0};
}
Str priority_trace_value(Str name, Str body) {
  return marker_value(name, body, false);
}
Str priority_trace_quoted(Str name, Str body) {
  return marker_value(name, body, true);
}

/* Explicit ancestor iterators visit every source pair before first-key
 * projection. Only nonempty containers occupy frames: an empty terminal
 * container at depth 512 remains valid, but a nonempty one does not. */
static bool foundation_valid(yyjson_val *v) {
  struct {
    bool object;
    union {
      yyjson_obj_iter obj;
      yyjson_arr_iter arr;
    } it;
  } stack[512];
  size_t count = 0;
  for (;;) {
    if (yyjson_is_str(v)) {
      if (!str_utf8_scalar_valid(string(v)))
        return false;
    } else if (yyjson_is_raw(v)) {
      Str raw = {yyjson_get_raw(v), (uint32_t)yyjson_get_len(v)};
      if (!json_number_is_integer(raw) && strtod(raw.p, NULL) == INFINITY)
        return false;
    } else if ((yyjson_is_obj(v) || yyjson_is_arr(v)) && yyjson_get_len(v)) {
      if (count >= 512)
        return false;
      stack[count].object = yyjson_is_obj(v);
      if (stack[count].object)
        stack[count].it.obj = yyjson_obj_iter_with(v);
      else
        stack[count].it.arr = yyjson_arr_iter_with(v);
      count++;
    }
    v = NULL;
    while (count) {
      if (stack[count - 1].object) {
        yyjson_val *key = yyjson_obj_iter_next(&stack[count - 1].it.obj);
        if (key) {
          if (!str_utf8_scalar_valid(string(key)))
            return false;
          v = yyjson_obj_iter_get_val(key);
        }
      } else {
        v = yyjson_arr_iter_next(&stack[count - 1].it.arr);
      }
      if (v)
        break;
      count--;
    }
    if (!v)
      return true;
  }
}
static JsonRead trace_json(Str tail) {
  JsonRead read =
      json_read(token_model_trim(tail), BYTES, JSON_CONSTANTS_REJECT,
                "logs_2.sqlite:feedback_log_body");
  if (read.status == JSON_OK &&
      (!yyjson_is_obj(yyjson_doc_get_root(read.doc)) ||
       !foundation_valid(yyjson_doc_get_root(read.doc)))) {
    json_read_free(&read);
    read.status = JSON_INVALID;
  }
  return read;
}
Err priority_completed_parse(Arena *arena, Str body, Str *turn, Str *model) {
  *turn = (Str){0};
  *model = (Str){0};
  size_t at = literal(body, STR_LIT("websocket event:"));
  if (at == SIZE_MAX)
    return ERR_SUCCESS;
  JsonRead read = trace_json(slice(body, at + 16, body.n));
  Err e = read.status == JSON_NOMEM
              ? err_make(ERR_NOMEM, "priority trace JSON allocation failed")
              : ERR_SUCCESS;
  yyjson_val *root = read.doc ? yyjson_doc_get_root(read.doc) : NULL;
  if (root &&
      str_equal(string(first(root, "type")), STR_LIT("response.completed"))) {
    Str value = string(first(first(root, "response"), "model"));
    Str prefix = slice(body, 0, at),
        id = priority_trace_value(STR_LIT("turn.id"), prefix);
    if (!id.p)
      id = priority_trace_value(STR_LIT("turn_id"), prefix);
    if (id.p && value.n) {
      e = str_copy(arena, value, model);
      if (!e.code)
        *turn = id;
    }
  }
  json_read_free(&read);
  return e;
}
Err priority_trace_parse(Arena *arena, Str timestamp, Str body,
                         PriorityTrace *out) {
  *out = (PriorityTrace){0};
  size_t at = literal(body, STR_LIT("websocket request:"));
  Str prefix;
  Err e = ERR_SUCCESS;
  if (at != SIZE_MAX) {
    JsonRead read = trace_json(slice(body, at + 18, body.n));
    if (read.status == JSON_NOMEM)
      return err_make(ERR_NOMEM, "priority trace JSON allocation failed");
    yyjson_val *root = read.doc ? yyjson_doc_get_root(read.doc) : NULL;
    if (!root ||
        !str_equal(string(first(root, "type")), STR_LIT("response.create")) ||
        !str_equal(string(first(root, "service_tier")), STR_LIT("priority"))) {
      json_read_free(&read);
      return e;
    }
    prefix = slice(body, 0, at);
    out->turn_id = priority_trace_value(STR_LIT("turn.id"), prefix);
    if (!out->turn_id.p)
      out->turn_id = priority_trace_value(STR_LIT("turn_id"), prefix);
    if (!out->turn_id.p)
      e = copy_nullable(arena, string(first(root, "turn_id")), &out->turn_id);
    if (!e.code)
      e = copy_nullable(arena, string(first(root, "model")), &out->model);
    json_read_free(&read);
  } else {
    Str marker = STR_LIT("Submission sub=Submission {");
    at = literal(body, marker);
    if (at == SIZE_MAX ||
        literal(body, STR_LIT("service_tier: Some(Some(\"priority\"))")) ==
            SIZE_MAX)
      return e;
    prefix = slice(body, 0, at);
    out->turn_id = priority_trace_quoted(STR_LIT("id"),
                                         slice(body, at + marker.n, body.n));
  }
  if (!out->turn_id.n) {
    *out = (PriorityTrace){0};
    return e;
  }
  out->thread_id = priority_trace_value(STR_LIT("thread_id"), prefix);
  out->timestamp = timestamp;
  return e;
}

Err priority_sqlite_text(Arena *arena, sqlite3_stmt *stmt, int column,
                         Str *out) {
  *out = (Str){0};
  if (sqlite3_column_type(stmt, column) == SQLITE_NULL)
    return ERR_SUCCESS;
  const unsigned char *raw = sqlite3_column_text(stmt, column);
  if (!raw)
    return err_make(ERR_NOMEM, "SQLite text allocation failed");
  size_t length = strlen((const char *)raw), i = 0;
  JsonWriter buffer = {0};
  /* UTF-8 strict decoder with maximal valid-prefix consumption on truncation
   * or a later bad continuation. Invalid leading/range bytes consume one. */
  while (i < length) {
    size_t start = i;
    unsigned char c = raw[i++];
    size_t need = 0;
    unsigned char low = 0x80, high = 0xbf;
    if (c < 0x80) {
      jsonw_bytes(&buffer, raw + start, 1);
      continue;
    }
    if (c >= 0xc2 && c <= 0xdf)
      need = 1;
    else if (c >= 0xe0 && c <= 0xef) {
      need = 2;
      if (c == 0xe0)
        low = 0xa0;
      if (c == 0xed)
        high = 0x9f;
    } else if (c >= 0xf0 && c <= 0xf4) {
      need = 3;
      if (c == 0xf0)
        low = 0x90;
      if (c == 0xf4)
        high = 0x8f;
    }
    bool valid = need > 0;
    for (size_t n = 0; n < need; n++) {
      if (i == length || raw[i] < low || raw[i] > high) {
        valid = false;
        break;
      }
      i++;
      low = 0x80;
      high = 0xbf;
    }
    if (valid)
      jsonw_bytes(&buffer, raw + start, i - start);
    else
      jsonw_bytes(&buffer, "\xef\xbf\xbd", 3);
  }
  Err e = buffer.error;
  if (!e.code)
    e = str_copy(arena,
                 (Str){buffer.data ? buffer.data : "", (uint32_t)buffer.length},
                 out);
  jsonw_free(&buffer);
  return e;
}

static Err alloc(Arena *arena, size_t size, void **out) {
  Err e = arena_alloc(arena, size, _Alignof(max_align_t), out);
  if (!e.code)
    memset(*out, 0, size);
  return e;
}
static Err message(PriorityTurns *out, const char *prefix, const char *tail) {
  PriorityMessage *item;
  Err e = alloc(&out->arena, sizeof *item, (void **)&item);
  JsonWriter w = {0};
  jsonw_raw(&w, prefix);
  if (tail)
    jsonw_raw(&w, tail);
  if (!e.code)
    e = w.error;
  if (!e.code)
    e = str_copy(&out->arena, (Str){w.data, (uint32_t)w.length}, &item->text);
  if (!e.code) {
    if (out->last_message)
      out->last_message->next = item;
    else
      out->messages = item;
    out->last_message = item;
  }
  jsonw_free(&w);
  return e;
}
static Err entry_copy(Arena *arena, const PriorityEntry *value,
                      PriorityEntry **copy) {
  Err e = alloc(arena, sizeof **copy, (void **)copy);
  if (!e.code)
    e = copy_nullable(arena, value->thread_id, &(*copy)->thread_id);
  if (!e.code)
    e = copy_nullable(arena, value->model, &(*copy)->model);
  if (!e.code)
    e = copy_nullable(arena, value->timestamp, &(*copy)->timestamp);
  if (!e.code)
    (*copy)->first_seen_ms = value->first_seen_ms;
  return e;
}
static bool integer(yyjson_val *v, const char *site, int64_t *out) {
  PyNum n;
  if (!json_number(v, site, &n) || n.is_float)
    return false;
  *out = n.i;
  return true;
}
static Err stored_load(const char *file, PriorityTurns *out) {
  struct stat st;
  if (stat(file, &st))
    return ERR_SUCCESS;
  char *bytes = NULL;
  size_t n = 0;
  Err e = file_read_all(file, &bytes, &n);
  JsonRead read = {0};
  Omap entries = {0};
  const char *invalid = NULL;
  if (e.code == ERR_NOMEM)
    return e;
  if (e.code) {
    free(bytes);
    return message(out, "Priority memory unavailable: ", e.message);
  }
  read = json_read((Str){bytes, (uint32_t)n}, BYTES, JSON_CONSTANTS_ALLOW,
                   "priority-turns.json");
  if (read.status == JSON_NOMEM) {
    e = err_make(ERR_NOMEM, "priority memory allocation failed");
    goto done;
  }
  if (read.status != JSON_OK) {
    invalid = "invalid JSON";
    goto unavailable;
  }
  yyjson_val *root = yyjson_doc_get_root(read.doc);
  int64_t schema;
  if (!yyjson_is_obj(root) ||
      !integer(obj_get_last(root, STR_LIT("schema")),
               "priority-turns.json:schema", &schema) ||
      schema != 1) {
    invalid = "unsupported priority memory schema";
    goto unavailable;
  }
  yyjson_val *turns = obj_get_last(root, STR_LIT("turns"));
  if (!yyjson_is_obj(turns)) {
    invalid = "invalid priority memory turns";
    goto unavailable;
  }
  e = json_object_dict(turns, &entries);
  for (OmapEntry *item = entries.first; !e.code && item; item = item->next) {
    yyjson_val *value = item->value;
    PriorityEntry entry = {0};
    bool valid = item->key.n && yyjson_is_obj(value);
    if (valid)
      valid = integer(obj_get_last(value, STR_LIT("first_seen_ms")),
                      "priority-turns.json:turns.*.first_seen_ms",
                      &entry.first_seen_ms);
    const char *names[] = {"thread_id", "model", "timestamp"};
    Str *fields[] = {&entry.thread_id, &entry.model, &entry.timestamp};
    for (size_t i = 0; i < 3 && valid; i++) {
      yyjson_val *v = obj_get_last(value, text(names[i]));
      valid = v && (yyjson_is_null(v) || yyjson_is_str(v));
      *fields[i] = string(v);
    }
    if (!valid) {
      e = message(out, "Invalid priority memory entry ignored", NULL);
      continue;
    }
    PriorityEntry *copy;
    e = entry_copy(&out->arena, &entry, &copy);
    if (!e.code)
      e = omap_put(&out->turns, item->key, copy);
  }
  goto done;
unavailable:
  e = message(out, "Priority memory unavailable: ", invalid);
done:
  omap_destroy(&entries);
  json_read_free(&read);
  free(bytes);
  return e;
}
typedef struct {
  PriorityEntry *entry;
  Str spelling;
} Detected;
typedef struct {
  Str model;
} Completion;
/* Trace replacements need exact-size owners: a separate general-purpose
 * arena reserves 64 KiB even for one short model. Only published results use
 * the run arena; the pending queue frees each transient value immediately. */
static Err owned_entry(const PriorityEntry *source, PriorityEntry **out) {
  size_t size = sizeof(PriorityEntry);
  Str values[] = {source->thread_id, source->model, source->timestamp};
  for (size_t i = 0; i < 3; i++) {
    if (values[i].p && (size_t)values[i].n + 1 > SIZE_MAX - size)
      return err_make(ERR_NOMEM, "priority entry too large");
    if (values[i].p)
      size += (size_t)values[i].n + 1;
  }
  PriorityEntry *value = malloc(size);
  if (!value)
    return err_make(ERR_NOMEM, "priority entry allocation failed");
  *value = *source;
  Str *fields[] = {&value->thread_id, &value->model, &value->timestamp};
  char *cursor = (char *)(value + 1);
  for (size_t i = 0; i < 3; i++) {
    if (values[i].p) {
      memcpy(cursor, values[i].p, values[i].n);
      cursor[values[i].n] = 0;
      *fields[i] = (Str){cursor, values[i].n};
      cursor += (size_t)values[i].n + 1;
    }
  }
  *out = value;
  return ERR_SUCCESS;
}
static void completion_destroy(Completion *value) {
  if (value) {
    free((void *)value->model.p);
    free(value);
  }
}
static void completions_destroy(Omap *map) {
  for (OmapEntry *item = map->first; item; item = item->next)
    completion_destroy(item->value);
  omap_destroy(map);
}
static Err completion_put(Omap *map, Str key, Completion *value) {
  Completion *old = omap_get(map, key);
  Err e = omap_put(map, key, value);
  if (e.code)
    completion_destroy(value);
  else
    completion_destroy(old);
  return e;
}
static void detected_destroy(Omap *map) {
  for (OmapEntry *item = map->first; item; item = item->next) {
    Detected *value = item->value;
    free(value->entry);
    free(value);
  }
  omap_destroy(map);
}
static Err trace_load(const char *file, PriorityTurns *out, Omap *turns) {
  sqlite3 *db = NULL;
  sqlite3_stmt *stmt = NULL;
  char *uri = NULL;
  Omap completed = {0}, pending = {0};
  Err e = metadata_database_uri(file, &uri);
  if (e.code)
    return e;
  int rc =
      sqlite3_open_v2(uri, &db, SQLITE_OPEN_READONLY | SQLITE_OPEN_URI, NULL);
  free(uri);
  if (rc == SQLITE_OK)
    rc = sqlite3_busy_timeout(db, 250);
  const char *sql = "select rowid, ts, feedback_log_body from logs where rowid "
                    "> 0 and ts >= 0 "
                    "and (feedback_log_body like '%websocket request:%' or "
                    "feedback_log_body like '%response.completed%' "
                    "or feedback_log_body like '%service_tier: "
                    "Some(Some(\"priority\"))%') order by rowid";
  if (rc == SQLITE_OK)
    rc = sqlite3_prepare_v2(db, sql, -1, &stmt, NULL);
  if (rc != SQLITE_OK)
    goto sql_error;
  while ((rc = sqlite3_step(stmt)) == SQLITE_ROW) {
    Arena row = {0};
    Str body = {0}, timestamp = {0}, id = {0}, model = {0}, key = {0};
    PriorityTrace parsed = {0};
    e = priority_sqlite_text(&row, stmt, 2, &body);
    if (!e.code && body.p)
      e = priority_completed_parse(&row, body, &id, &model);
    if (!e.code && id.p) {
      e = str_nfc(&row, id, "logs_2.sqlite:feedback_log_body.turn_id", &key);
      Omap *target = omap_get(turns, key) ? &completed : &pending;
      if (!e.code && target == &pending && !omap_get(target, key) &&
          pending.size >= 4096) {
        void *old;
        omap_delete_oldest(target, &old);
        completion_destroy(old);
      }
      Completion *saved = NULL;
      if (!e.code) {
        saved = calloc(1, sizeof *saved);
        if (!saved)
          e = err_make(ERR_NOMEM, "priority completion allocation failed");
      }
      if (!e.code) {
        char *copy = malloc((size_t)model.n + 1);
        if (!copy)
          e = err_make(ERR_NOMEM, "priority model allocation failed");
        else {
          memcpy(copy, model.p, model.n);
          copy[model.n] = 0;
          saved->model = (Str){copy, model.n};
        }
      }
      if (!e.code)
        e = completion_put(target, key, saved);
      else
        completion_destroy(saved);
    } else if (!e.code && body.p) {
      e = priority_sqlite_text(&row, stmt, 1, &timestamp);
      if (!e.code)
        e = priority_trace_parse(&row, timestamp, body, &parsed);
      if (!e.code && parsed.turn_id.p) {
        e = str_nfc(&row, parsed.turn_id,
                    "logs_2.sqlite:feedback_log_body.turn_id", &key);
        Detected *detected = omap_get(turns, key);
        if (!e.code && !detected) {
          detected = calloc(1, sizeof *detected);
          if (!detected)
            e = err_make(ERR_NOMEM, "priority trace allocation failed");
          if (!e.code)
            e = str_copy(&out->arena, parsed.turn_id, &detected->spelling);
          if (!e.code)
            e = omap_put(turns, key, detected);
          if (e.code) {
            free(detected);
            detected = NULL;
          }
        }
        PriorityEntry entry = {parsed.thread_id, parsed.model, parsed.timestamp,
                               0};
        if (!e.code) {
          free(detected->entry);
          detected->entry = NULL;
          e = owned_entry(&entry, &detected->entry);
        }
        void *completion;
        if (!e.code && omap_delete(&pending, key, &completion))
          e = completion_put(&completed, key, completion);
      }
    }
    arena_destroy(&row);
    if (e.code)
      goto done;
  }
  if (rc != SQLITE_DONE)
    goto sql_error;
  for (OmapEntry *item = completed.first; item; item = item->next) {
    Detected *detected = omap_get(turns, item->key);
    Completion *value = item->value;
    PriorityEntry replacement = *detected->entry;
    replacement.model = value->model;
    PriorityEntry *copy = NULL;
    e = owned_entry(&replacement, &copy);
    if (!e.code) {
      free(detected->entry);
      detected->entry = copy;
    }
    if (e.code)
      goto done;
  }
  goto done;
sql_error:
  if (rc == SQLITE_NOMEM)
    e = err_make(ERR_NOMEM, "priority SQLite allocation failed");
  else {
    e = message(out,
                "Priority trace database unavailable: ", sqlite3_errmsg(db));
    detected_destroy(turns);
  }
done:
  sqlite3_finalize(stmt);
  if (db)
    sqlite3_close(db);
  completions_destroy(&completed);
  completions_destroy(&pending);
  return e;
}
static bool entry_equal(const PriorityEntry *a, const PriorityEntry *b) {
  return a->first_seen_ms == b->first_seen_ms &&
         (a->thread_id.p != NULL) == (b->thread_id.p != NULL) &&
         str_equal(a->thread_id, b->thread_id) &&
         (a->model.p != NULL) == (b->model.p != NULL) &&
         str_equal(a->model, b->model) &&
         (a->timestamp.p != NULL) == (b->timestamp.p != NULL) &&
         str_equal(a->timestamp, b->timestamp);
}
static void nullable(JsonWriter *w, Str s) {
  if (s.p)
    jsonw_string(w, s);
  else
    jsonw_raw(w, "null");
}
void priority_turns_json(JsonWriter *w, const Omap *turns) {
  jsonw_raw(w, "{");
  for (OmapEntry *item = turns->first; item; item = item->next) {
    PriorityEntry *v = item->value;
    if (item != turns->first)
      jsonw_raw(w, ",");
    jsonw_string(w, item->key);
    jsonw_raw(w, ":{\"thread_id\":");
    nullable(w, v->thread_id);
    jsonw_raw(w, ",\"model\":");
    nullable(w, v->model);
    jsonw_raw(w, ",\"timestamp\":");
    nullable(w, v->timestamp);
    jsonw_raw(w, ",\"first_seen_ms\":");
    jsonw_i64(w, v->first_seen_ms);
    jsonw_raw(w, "}");
  }
  jsonw_raw(w, "}");
}
Err priority_load(const char *codex, const char *home, PriorityTurns *out) {
  JsonWriter path = {0};
  jsonw_raw(&path, home);
  jsonw_raw(&path, "/priority-turns.json");
  jsonw_bytes(&path, "", 1);
  Err e = path.error;
  Omap trace = {0}, stored_keys = {0};
  if (!e.code)
    e = stored_load(path.data, out);
  JsonWriter database = {0};
  jsonw_raw(&database, codex);
  jsonw_raw(&database, "/logs_2.sqlite");
  jsonw_bytes(&database, "", 1);
  if (!e.code)
    e = database.error;
  struct stat st;
  if (!e.code && !stat(database.data, &st))
    e = trace_load(database.data, out, &trace);
  Arena normalized = {0};
  for (OmapEntry *item = out->turns.first; !e.code && item; item = item->next) {
    Str key;
    e = str_nfc(&normalized, item->key, "priority-turns.json:turns.*", &key);
    if (!e.code)
      e = omap_put(&stored_keys, key, item);
  }
  bool changed = false;
  int64_t wall = cp_wall_ms();
  for (OmapEntry *item = trace.first; !e.code && item; item = item->next) {
    Detected *detected = item->value;
    OmapEntry *saved = omap_get(&stored_keys, item->key);
    Str spelling = saved ? saved->key : detected->spelling;
    PriorityEntry *previous = saved ? saved->value : NULL;
    detected->entry->first_seen_ms = previous ? previous->first_seen_ms : wall;
    if (!previous || !entry_equal(previous, detected->entry))
      changed = true;
    PriorityEntry *copy;
    e = entry_copy(&out->arena, detected->entry, &copy);
    if (!e.code)
      e = omap_put(&out->turns, spelling, copy);
  }
  if (!e.code && changed) {
    JsonWriter w = {0};
    jsonw_raw(&w, "{\"schema\":1,\"turns\":");
    priority_turns_json(&w, &out->turns);
    jsonw_raw(&w, "}");
    e = w.error;
    if (!e.code)
      e = atomic_write(path.data, w.data, w.length);
    jsonw_free(&w);
  }
  detected_destroy(&trace);
  omap_destroy(&stored_keys);
  arena_destroy(&normalized);
  jsonw_free(&database);
  jsonw_free(&path);
  return e;
}
void priority_destroy(PriorityTurns *out) {
  omap_destroy(&out->turns);
  arena_destroy(&out->arena);
  *out = (PriorityTurns){0};
}
