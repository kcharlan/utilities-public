#define _DARWIN_C_SOURCE
#include "compose.h"
#include "foundation.h"
#include "parse/record.h"
#include "parse/tokenstream.h"
#include "price/claude_model.h"
#include "util/json_number.h"
#include "util/time.h"
#include <CoreFoundation/CoreFoundation.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define TRY(x)                                                                 \
  do {                                                                         \
    Err e_ = (x);                                                              \
    if (e_.code)                                                               \
      return e_;                                                               \
  } while (0)
static yyjson_val *get(yyjson_val *v, const char *k) {
  return record_get(v, k);
}
static Str text(yyjson_val *v) {
  return yyjson_is_str(v)
             ? (Str){yyjson_get_str(v), (uint32_t)yyjson_get_len(v)}
             : (Str){0};
}
static bool contains(Str s, const char *p) {
  return s.p && memmem(s.p, s.n, p, strlen(p));
}
static bool contains_case(Str s, const char *p) {
  size_t n = strlen(p);
  for (size_t i = 0; i + n <= s.n; i++)
    if (!strncasecmp(s.p + i, p, n))
      return true;
  return false;
}
static bool unsigned_number(yyjson_val *v, uint64_t *out) {
  if (yyjson_is_uint(v)) {
    *out = yyjson_get_uint(v);
    return true;
  }
  if (yyjson_is_sint(v) && yyjson_get_sint(v) >= 0) {
    *out = (uint64_t)yyjson_get_sint(v);
    return true;
  }
  if (!yyjson_is_raw(v))
    return false;
  Str s = {yyjson_get_raw(v), (uint32_t)yyjson_get_len(v)};
  if (!json_number_is_integer(s) || !s.n || s.p[0] == '-')
    return false;
  uint64_t n = 0;
  for (size_t i = 0; i < s.n; i++) {
    unsigned d = s.p[i] - '0';
    if (n > (UINT64_MAX - d) / 10)
      return false;
    n = n * 10 + d;
  }
  *out = n;
  return true;
}
static int64_t integer(yyjson_val *v) {
  if (yyjson_is_bool(v))
    return yyjson_is_true(v);
  uint64_t unsigned_value;
  if (unsigned_number(v, &unsigned_value)) {
    int64_t signed_value;
    memcpy(&signed_value, &unsigned_value, sizeof signed_value);
    return signed_value;
  }
  /* JSONSerialization may choose NSDecimalNumber for a fractional spelling.
   * Converting it through double first changes its intValue semantics. */
  if (yyjson_is_raw(v) &&
      !json_number_is_integer(
          (Str){yyjson_get_raw(v), (uint32_t)yyjson_get_len(v)})) {
    int64_t value = 0;
    bool ignored;
    (void)claude_foundation_number(
        (Str){yyjson_get_raw(v), (uint32_t)yyjson_get_len(v)}, &value,
        &ignored);
    return value;
  }
  PyNum n;
  if (!json_number(v, "claude.usage", &n)) {
    int64_t value = 0;
    bool ignored;
    if (yyjson_is_raw(v))
      (void)claude_foundation_number(
          (Str){yyjson_get_raw(v), (uint32_t)yyjson_get_len(v)}, &value,
          &ignored);
    return value;
  }
  if (!n.is_float)
    return n.i;
  if (!isfinite(n.f))
    return 0;
  if (n.f >= 0x1p63)
    return INT64_MAX;
  if (n.f < -0x1p63)
    return INT64_MIN;
  return (int64_t)n.f;
}
static __int128 positive(yyjson_val *v) {
  int64_t n = integer(v);
  return n > 0 ? n : 0;
}
static bool boolean(yyjson_val *v) {
  if (yyjson_is_bool(v))
    return yyjson_is_true(v);
  uint64_t u;
  if (unsigned_number(v, &u))
    return u != 0;
  if (yyjson_is_raw(v) &&
      !json_number_is_integer(
          (Str){yyjson_get_raw(v), (uint32_t)yyjson_get_len(v)})) {
    int64_t ignored;
    bool value = false;
    (void)claude_foundation_number(
        (Str){yyjson_get_raw(v), (uint32_t)yyjson_get_len(v)}, &ignored,
        &value);
    return value;
  }
  PyNum n;
  if (json_number(v, "claude.sidechain", &n))
    return n.is_float ? n.f != 0 : n.i != 0;
  int64_t ignored;
  bool value = false;
  if (yyjson_is_raw(v))
    (void)claude_foundation_number(
        (Str){yyjson_get_raw(v), (uint32_t)yyjson_get_len(v)}, &ignored,
        &value);
  return value;
}
static __int128 advisor_tokens(yyjson_val *v) {
  uint64_t n = 0;
  (void)unsigned_number(v, &n);
  return n;
}
static Err dropped(ClaudeRecord *r, const char *reason) {
  Str key = {reason, (uint32_t)strlen(reason)};
  uint64_t *n = omap_get(&r->rows_dropped, key);
  if (!n) {
    TRY(arena_alloc(&r->arena, sizeof *n, _Alignof(uint64_t), (void **)&n));
    *n = 0;
    TRY(omap_put(&r->rows_dropped, key, n));
  }
  (*n)++;
  return ERR_SUCCESS;
}
/* Swift decoded-string contains/hasPrefix compare canonical-equivalent whole
 * graphemes. Raw JSON prefilters deliberately retain their byte predicates. */
static bool decoded_match(Str s, CFStringRef needle, bool prefix) {
  CFStringRef string = CFStringCreateWithBytes(NULL, (const UInt8 *)s.p, s.n,
                                               kCFStringEncodingUTF8, false);
  if (!string)
    return false;
  bool found = false;
  CFIndex at = 0, length = CFStringGetLength(string);
  CFRange match;
  while (at < length &&
         CFStringFindWithOptions(string, needle, CFRangeMake(at, length - at),
                                 kCFCompareNonliteral, &match)) {
    if (prefix && match.location != 0)
      break;
    CFRange first = CFStringGetRangeOfComposedCharactersAtIndex(string,
                                                                match.location),
            last = CFStringGetRangeOfComposedCharactersAtIndex(
                string, match.location + match.length - 1);
    if (first.location == match.location &&
        last.location + last.length == match.location + match.length) {
      found = true;
      break;
    }
    at = match.location + match.length;
  }
  CFRelease(string);
  return found;
}
static bool decoded_contains(Str s, CFStringRef needle) {
  return decoded_match(s, needle, false);
}
static bool decoded_prefix(Str s, CFStringRef needle) {
  return decoded_match(s, needle, true);
}
static Err marker(Arena *a, Str s, bool gcp, bool *out) {
  Str lower;
  TRY(str_lower(a, s, &lower));
  *out = decoded_contains(lower, CFSTR("vertex")) ||
         (gcp && decoded_contains(lower, CFSTR("gcp")));
  return ERR_SUCCESS;
}
static Err timestamp(Str s, MaybeMs *out) {
  *out = (MaybeMs){0};
  if (s.n > 12 && s.p[11] >= '0' && s.p[11] <= '2' &&
      !(s.p[11] == '2' && s.p[12] >= '4') &&
      time_codex_timestamp(s, "claude.usage.timestamp", &out->value)) {
    out->present = true;
    return ERR_SUCCESS;
  }
  CFStringRef string = CFStringCreateWithBytes(NULL, (const UInt8 *)s.p, s.n,
                                               kCFStringEncodingUTF8, false);
  if (!string)
    return ERR_SUCCESS;
  const CFISO8601DateFormatOptions options[] = {
      kCFISO8601DateFormatWithInternetDateTime |
          kCFISO8601DateFormatWithFractionalSeconds,
      kCFISO8601DateFormatWithInternetDateTime};
  Err e = ERR_SUCCESS;
  for (size_t i = 0; i < 2 && !out->present; i++) {
    CFDateFormatterRef formatter =
        CFDateFormatterCreateISO8601Formatter(NULL, options[i]);
    if (!formatter) {
      e = err_make(ERR_NOMEM, "Claude timestamp formatter allocation");
      break;
    }
    CFAbsoluteTime absolute;
    bool valid = CFDateFormatterGetAbsoluteTimeFromString(formatter, string,
                                                          NULL, &absolute);
    CFRelease(formatter);
    if (valid)
      out->present =
          time_round_swift_ms(absolute + kCFAbsoluteTimeIntervalSince1970,
                              "claude.usage.timestamp", &out->value);
  }
  CFRelease(string);
  return e;
}
static Err metadata_vertex(Arena *a, yyjson_val *v, bool *out) {
  *out = false;
  size_t i, max;
  yyjson_val *k, *value;
  yyjson_obj_foreach(v, i, max, k, value) {
    bool found;
    TRY(marker(a, text(k), true, &found));
    if (found) {
      *out = true;
      return ERR_SUCCESS;
    }
    Str lower;
    TRY(str_lower(a, text(k), &lower));
    const char *keys[] = {"provider",    "platform", "backend", "api_provider",
                          "apiprovider", "api_type", "apitype", "source",
                          "vendor",      "client"};
    for (size_t j = 0; j < sizeof keys / sizeof *keys; j++)
      if (str_equal(lower, (Str){keys[j], (uint32_t)strlen(keys[j])}) &&
          yyjson_is_str(value)) {
        TRY(marker(a, text(value), false, &found));
        if (found) {
          *out = true;
          return ERR_SUCCESS;
        }
      }
    if (yyjson_is_obj(value)) {
      TRY(metadata_vertex(a, value, &found));
      if (found) {
        *out = true;
        return ERR_SUCCESS;
      }
    } else if (yyjson_is_arr(value)) {
      size_t j, n;
      yyjson_val *q;
      yyjson_arr_foreach(value, j, n, q) if (yyjson_is_obj(q)) {
        TRY(metadata_vertex(a, q, &found));
        if (found) {
          *out = true;
          return ERR_SUCCESS;
        }
      }
    }
  }
  return ERR_SUCCESS;
}
static Err keep_row(ClaudeRecord *r, yyjson_val *v, yyjson_val *usage,
                    Str model, Str message_id, Str turn, uint64_t line,
                    MaybeMs stamp, bool advisor) {
  yyjson_val *m = get(v, "message");
  __int128 input = positive(get(usage, "input_tokens")),
           read = positive(get(usage, "cache_read_input_tokens")),
           write = positive(get(usage, "cache_creation_input_tokens")),
           output = positive(get(usage, "output_tokens"));
  yyjson_val *creation = get(usage, "cache_creation");
  if (advisor) {
    input = advisor_tokens(get(usage, "input_tokens"));
    read = advisor_tokens(get(usage, "cache_read_input_tokens"));
    write = advisor_tokens(get(usage, "cache_creation_input_tokens"));
    output = advisor_tokens(get(usage, "output_tokens"));
  }
  if (advisor && yyjson_is_obj(creation)) {
    /* ccusage TokenUsageRaw.cache_creation_token_count uses the nested sum. */
    write = advisor_tokens(get(creation, "ephemeral_5m_input_tokens")) +
            advisor_tokens(get(creation, "ephemeral_1h_input_tokens"));
    if (write > UINT64_MAX)
      write = UINT64_MAX;
  }
  __int128 one =
      advisor ? advisor_tokens(get(creation, "ephemeral_1h_input_tokens"))
              : positive(get(creation, "ephemeral_1h_input_tokens"));
  if (one > write)
    one = write;
  Str session = text(get(v, "sessionId"));
  if (!session.p)
    session = text(get(v, "session_id"));
  if (!session.p)
    session = text(get(get(v, "metadata"), "sessionId"));
  if (!session.p)
    session = text(get(get(m, "metadata"), "sessionId"));
  ClaudeUsageRow row = {
      .incomplete = !advisor && yyjson_is_null(get(m, "stop_reason")) &&
                    input > 0 && output == 0 &&
                    !get(usage, "cache_read_input_tokens") &&
                    !get(usage, "cache_creation_input_tokens"),
      .sidechain = boolean(get(v, "isSidechain")),
      .subagent = decoded_contains(r->key.path, CFSTR("/subagents/"))};
  Str originals[] = {model, message_id, text(get(v, "requestId")), session,
                     turn};
  Str *dest[] = {&row.unit.model_raw, &row.message_id, &row.request_id,
                 &row.session_id, &row.unit.display_turn};
  for (size_t i = 0; i < 5; i++)
    if (originals[i].p)
      TRY(str_copy(&r->arena, originals[i], dest[i]));
  row.unit.model = row.unit.model_raw;
  row.unit.turn_id = row.unit.display_turn;
  row.unit.source = STR_LIT("claude");
  row.unit.at_ms = row.unit.timestamp_ms = stamp;
  row.unit.line = line;
  row.unit.input = input + read + write;
  row.unit.cached = read;
  row.unit.cache_write = write;
  row.unit.cache_write_1h = one;
  row.unit.output = output;
  yyjson_val *thinking =
      get(get(usage, "output_tokens_details"), "thinking_tokens");
  if (thinking)
    row.unit.reasoning = (OptionalTokens){true, (int64_t)positive(thinking)};
  row.unit.fast = str_equal(text(get(usage, "speed")), STR_LIT("fast"));
  return record_append_aligned(&r->arena, (void **)&r->usage_rows,
                               &r->usage_count, &r->usage_capacity, sizeof row,
                               _Alignof(ClaudeUsageRow), &row);
}
/* Rust serde rejects the whole iterations envelope if any iteration's typed
 * fields fail, including unrelated iterations. Keep that boundary. */
static bool unsigned_field(yyjson_val *v, bool required) {
  if (!v)
    return !required;
  uint64_t n;
  return unsigned_number(v, &n);
}
static bool unique_fields(yyjson_val *v, const char *const *names,
                          size_t count) {
  uint64_t seen = 0;
  size_t i, n;
  yyjson_val *key, *value;
  yyjson_obj_foreach(v, i, n, key, value) {
    (void)value;
    for (size_t j = 0; j < count; j++)
      if (str_equal(text(key), (Str){names[j], (uint32_t)strlen(names[j])})) {
        uint64_t bit = UINT64_C(1) << j;
        if (seen & bit)
          return false;
        seen |= bit;
        break;
      }
  }
  return true;
}
static bool advisor_valid(yyjson_val *v) {
  if (!yyjson_is_obj(v) || !yyjson_is_str(get(v, "type")))
    return false;
  const char *fields[] = {"type",
                          "model",
                          "input_tokens",
                          "output_tokens",
                          "cache_creation_input_tokens",
                          "cache_read_input_tokens",
                          "speed",
                          "cache_creation"};
  if (!unique_fields(v, fields, sizeof fields / sizeof *fields))
    return false;
  yyjson_val *model = get(v, "model"), *speed = get(v, "speed"),
             *cache = get(v, "cache_creation");
  if (model && !yyjson_is_null(model) && !yyjson_is_str(model))
    return false;
  if (speed && !yyjson_is_null(speed) &&
      !str_equal(text(speed), STR_LIT("fast")) &&
      !str_equal(text(speed), STR_LIT("standard")))
    return false;
  if (!unsigned_field(get(v, "input_tokens"), true) ||
      !unsigned_field(get(v, "output_tokens"), true) ||
      !unsigned_field(get(v, "cache_read_input_tokens"), false) ||
      !unsigned_field(get(v, "cache_creation_input_tokens"), false))
    return false;
  const char *cache_fields[] = {"ephemeral_5m_input_tokens",
                                "ephemeral_1h_input_tokens"};
  return !cache || yyjson_is_null(cache) ||
         (yyjson_is_obj(cache) && unique_fields(cache, cache_fields, 2) &&
          unsigned_field(get(cache, "ephemeral_5m_input_tokens"), false) &&
          unsigned_field(get(cache, "ephemeral_1h_input_tokens"), false));
}
typedef struct {
  ClaudeRecord *r;
  Str turn;
} Extract;
static Err decoded(void *context, const ReaderRawLine *raw,
                   const JsonRead *json) {
  Extract *x = context;
  ClaudeRecord *r = x->r;
  if (!json->doc || json->stats.nonfinite || json->stats.raw_surrogates ||
      json->stats.lone_surrogates)
    return dropped(r, "invalid_json");
  if (!claude_foundation_object_valid(raw->bytes))
    return dropped(r, "invalid_json");
  yyjson_val *v = yyjson_doc_get_root(json->doc), *m = get(v, "message");
  if (!str_equal(text(get(v, "type")), STR_LIT("assistant")))
    return dropped(r, "type");
  Str model = text(get(m, "model"));
  bool vertex = decoded_contains(text(get(m, "id")), CFSTR("_vrtx_")) ||
                decoded_contains(text(get(v, "requestId")), CFSTR("_vrtx_")) ||
                (decoded_prefix(model, CFSTR("claude-")) &&
                 decoded_contains(model, CFSTR("@")));
  bool scan_metadata = contains_case(raw->bytes, "vertex") ||
                       contains_case(raw->bytes, "gcp") ||
                       contains_case(raw->bytes, "\\u004") ||
                       contains_case(raw->bytes, "\\u005") ||
                       contains_case(raw->bytes, "\\u006") ||
                       contains_case(raw->bytes, "\\u007");
  if (!vertex && scan_metadata) {
    Arena scratch = {0};
    Err e = metadata_vertex(&scratch, v, &vertex);
    arena_destroy(&scratch);
    TRY(e);
  }
  if (vertex)
    return dropped(r, "vertex_ai");
  MaybeMs stamp = {0};
  TRY(timestamp(text(get(v, "timestamp")), &stamp));
  if (!stamp.present)
    return dropped(r, "timestamp");
  if (!yyjson_is_obj(m))
    return dropped(r, "message");
  if (!model.p)
    return dropped(r, "model");
  yyjson_val *usage = get(m, "usage");
  if (!yyjson_is_obj(usage))
    return dropped(r, "usage");
  if (!positive(get(usage, "input_tokens")) &&
      !positive(get(usage, "cache_creation_input_tokens")) &&
      !positive(get(usage, "cache_read_input_tokens")) &&
      !positive(get(usage, "output_tokens"))) {
    TRY(dropped(r, "zero_usage"));
  } else {
    TRY(keep_row(r, v, usage, model, text(get(m, "id")), x->turn, raw->index,
                 stamp, false));
  }
  yyjson_val *iterations = get(usage, "iterations");
  if (!contains(raw->bytes, "\"advisor_message\"") ||
      !yyjson_is_arr(iterations))
    return ERR_SUCCESS;
  const char *root_fields[] = {"message"}, *message_fields[] = {"usage"},
             *usage_fields[] = {"iterations"};
  if (!unique_fields(v, root_fields, 1) ||
      !unique_fields(m, message_fields, 1) ||
      !unique_fields(usage, usage_fields, 1))
    return ERR_SUCCESS;
  size_t i, n;
  yyjson_val *q;
  yyjson_arr_foreach(iterations, i, n,
                     q) if (!advisor_valid(q)) return ERR_SUCCESS;
  size_t advisor_index = 0;
  yyjson_arr_foreach(iterations, i, n, q) {
    Str advisor_model = text(get(q, "model"));
    if (!str_equal(text(get(q, "type")), STR_LIT("advisor_message")) ||
        !advisor_model.n)
      continue;
    Str id = text(get(m, "id"));
    JsonWriter w = {0};
    if (id.p) {
      jsonw_bytes(&w, id.p, id.n);
      jsonw_raw(&w, ":advisor:");
      jsonw_i64(&w, (int64_t)advisor_index);
      if (w.error.code) {
        Err e = w.error;
        jsonw_free(&w);
        return e;
      }
      id = (Str){w.data, (uint32_t)w.length};
    }
    Err e =
        keep_row(r, v, q, advisor_model, id, x->turn, raw->index, stamp, true);
    jsonw_free(&w);
    TRY(e);
    advisor_index++;
  }
  return ERR_SUCCESS;
}
Err claude_usage_line(ClaudeRecord *r, const ReaderRawLine *line, Str turn) {
  if (!line->bytes.n)
    return ERR_SUCCESS;
  if (line->bytes.n > 512 * 1024)
    return dropped(r, "line_cap");
  if (!contains(line->bytes, "\"type\":\"assistant\"") ||
      !contains(line->bytes, "\"usage\""))
    return dropped(r, "line_filter");
  Extract x = {r, turn};
  return reader_observe_line(line, &x, decoded);
}
static Err row_key(Arena *arena, const ClaudeUsageRow *r, Str *out) {
  *out = (Str){0};
  if (!r->message_id.p)
    return ERR_SUCCESS;
  if (!r->request_id.p &&
      (!token_model_trim(r->message_id).n || !r->session_id.p ||
       !token_model_trim(r->session_id).n))
    return ERR_SUCCESS;
  Str message, scope;
  TRY(str_nfc(arena, r->message_id, "claude.usage.identity", &message));
  TRY(str_nfc(arena, r->request_id.p ? r->request_id : r->session_id,
              "claude.usage.identity", &scope));
  JsonWriter w = {0};
  jsonw_raw(&w, r->request_id.p ? "[\"request\"," : "[\"session\",");
  jsonw_string(&w, message);
  jsonw_raw(&w, ",");
  jsonw_string(&w, scope);
  jsonw_raw(&w, "]");
  Err e = w.error;
  if (!e.code)
    e = str_copy(arena, (Str){w.data, (uint32_t)w.length}, out);
  jsonw_free(&w);
  return e;
}
typedef struct {
  ClaudeUsageRow *row;
  ClaudeRecord *record;
  Str key;
  size_t copies;
  Str path_order; /* Swift comparison key; original provenance stays intact. */
} Winner;
static bool wins(const Winner *candidate, const Winner *old) {
  if (candidate->row->incomplete != old->row->incomplete)
    return !candidate->row->incomplete;
  if (candidate->row->sidechain != old->row->sidechain)
    return !candidate->row->sidechain;
  if (candidate->row->subagent != old->row->subagent)
    return !candidate->row->subagent;
  return str_compare(candidate->path_order, old->path_order) < 0;
}
static Err authored(Corpus *c, ClaudeScan *scan, const Winner *w) {
  if (w->row->incomplete) {
    scan->incomplete_requests++;
    return ERR_SUCCESS;
  }
  SessionModel *s = omap_get(&c->sessions, w->record->id);
  if (!s || s->provider != PROVIDER_CLAUDE)
    return ERR_SUCCESS;
  UsageUnit u = w->row->unit;
  TRY(normalize_claude_model(&c->usage_arena,u.model_raw,&u.model));
  u.session_id = s->id;
  u.file = (size_t)(w->record - scan->records);
  u.priority_tier =
      u.fast; /* Shared bucket grouping; Codex pricing skips Claude. */
  bool found = false;
  for (size_t i = 0; i < s->turn_count; i++)
    if (str_equal(s->turns[i].id, u.display_turn))
      found = true;
  if (!found)
    u.display_turn = (Str){0};
  TRY(record_append_aligned(&c->usage_arena, (void **)&s->units, &s->unit_count,
                            &s->unit_capacity, sizeof u, _Alignof(UsageUnit),
                            &u));
  if (!scan->token_data_from_ms.present ||
      u.at_ms.value < scan->token_data_from_ms.value)
    scan->token_data_from_ms = u.at_ms;
  return ERR_SUCCESS;
}
Err claude_compose(ClaudeScan *scan, Corpus *c) {
  Arena arena = {0};
  Omap global = {0};
  Err e = ERR_SUCCESS;
  scan->duplicate_keys = scan->duplicate_rows = scan->incomplete_requests = 0;
  scan->token_data_from_ms = (MaybeMs){0};
  for (size_t f = 0; f < scan->count; f++) {
    ClaudeRecord *r = &scan->records[f];
    SessionModel *s = omap_get(&c->sessions, r->id);
    if (!s || s->provider != PROVIDER_CLAUDE)
      continue;
    Str path_order;
    e = str_nfc(&arena, r->key.path, "claude.usage.path_order", &path_order);
    if (e.code)
      goto done;
    Omap local = {0};
    for (size_t i = 0; i < r->usage_count; i++) {
      ClaudeUsageRow *row = &r->usage_rows[i];
      Str key;
      e = row_key(&arena, row, &key);
      if (e.code)
        break;
      Winner candidate = {row, r, key, 1, path_order};
      if (!key.p) {
        e = authored(c, scan, &candidate);
        if (e.code)
          break;
        continue;
      }
      Winner *old = omap_get(&local, key);
      if (old) {
        old->copies++;
        if (!row->incomplete || old->row->incomplete)
          old->row = row;
      } else {
        e = arena_alloc(&arena, sizeof *old, _Alignof(Winner), (void **)&old);
        if (e.code)
          break;
        *old = candidate;
        e = omap_put(&local, key, old);
        if (e.code)
          break;
      }
    }
    if (!e.code)
      for (OmapEntry *p = local.first; p; p = p->next) {
        Winner *candidate = p->value, *old = omap_get(&global, p->key);
        if (old) {
          size_t copies = old->copies + candidate->copies;
          if (wins(candidate, old))
            *old = *candidate;
          old->copies = copies;
        } else {
          e = omap_put(&global, p->key, candidate);
          if (e.code)
            break;
        }
      }
    omap_destroy(&local);
    if (e.code)
      goto done;
  }
  for (OmapEntry *p = global.first; p; p = p->next) {
    Winner *w = p->value;
    if (w->copies > 1) {
      scan->duplicate_keys++;
      scan->duplicate_rows += w->copies - 1;
    }
    e = authored(c, scan, w);
    if (e.code)
      goto done;
  }
  for (OmapEntry *p = c->sessions.first; p; p = p->next) {
    SessionModel *s = p->value;
    if (s->provider != PROVIDER_CLAUDE)
      continue;
    s->bucket_count = 0;
    e = compose_aggregate_session(c, s);
    if (e.code)
      goto done;
  }
done:
  omap_destroy(&global);
  arena_destroy(&arena);
  return e;
}
