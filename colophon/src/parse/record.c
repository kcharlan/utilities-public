#include "record.h"
#include "history.h"
#include "links.h"
#include "messages.h"
#include "tools.h"
#include "turns.h"
#include "util/events.h"
#include "util/fileio.h"
#include "util/json_number.h"
#include "util/time.h"
#include "voice.h"
#include <math.h>
#include <stdalign.h>
#include <stdlib.h>
#include <string.h>

yyjson_val *record_get(yyjson_val *obj, const char *key) {
    return obj_get_last(obj, (Str){key, (uint32_t)strlen(key)});
}
yyjson_val *record_turn_id(yyjson_val *payload) {
    const char *keys[] = {"turn_id", "turnId", "id"};
    yyjson_val *info = record_get(payload, "info");
    for (size_t i = 0; i < 6; i++) {
        yyjson_val *value = record_get(i < 3 ? payload : info, keys[i % 3]);
        if (yyjson_is_str(value) && yyjson_get_len(value))
            return value;
    }
    return NULL;
}
Str record_string(yyjson_val *value) {
    return yyjson_is_str(value) ? (Str){yyjson_get_str(value), (uint32_t)yyjson_get_len(value)}
                                : (Str){0};
}
bool record_prefix(Str value, const char *prefix) {
    size_t n = strlen(prefix);
    return value.n >= n && !memcmp(value.p, prefix, n);
}
Str record_trim(Str value, bool right) {
    return str_trim(value, right);
}
bool record_identifier(Str value, bool history) {
    return value.p && (history ? record_trim(value, true).n : value.n) > 0;
}
Err record_intern(LogRecord *record, Str value, Str *out) {
    if (!value.p) {
        *out = (Str){0};
        return ERR_SUCCESS;
    }
    return intern_get(record->identifiers, value, out);
}
Err record_append(Arena *arena, void **data, size_t *count, size_t *capacity, size_t size,
                  const void *value) {
    return record_append_aligned(arena,data,count,capacity,size,alignof(max_align_t),value);
}
Err record_append_aligned(Arena *arena, void **data, size_t *count, size_t *capacity,
                          size_t size, size_t alignment, const void *value) {
    if (*count == *capacity) {
        size_t next = *capacity ? *capacity * 2 : 8;
        if (next < *capacity || next > SIZE_MAX / size)
            return err_make(ERR_NOMEM, "fact array too large");
        void *grown;
        Err err = arena_alloc(arena, next * size, alignment, &grown);
        if (err.code)
            return err;
        if (*count)
            memcpy(grown, *data, *count * size);
        *data = grown;
        *capacity = next;
    }
    memcpy((char *)*data + (*count)++ * size, value, size);
    return ERR_SUCCESS;
}
Err record_scalar(LogRecord *record, yyjson_val *value, const char *site, JScalar *out) {
    *out = (JScalar){0};
    if (!value)
        return ERR_SUCCESS;
    if (yyjson_is_null(value))
        out->kind = JS_NULL;
    else if (yyjson_is_bool(value)) {
        out->kind = JS_BOOL;
        out->value.b = yyjson_is_true(value);
    } else if (yyjson_is_str(value)) {
        out->kind = JS_STRING;
        return str_copy(&record->arena, record_string(value), &out->value.s);
    } else if (yyjson_is_arr(value)) {
        out->kind = JS_ARRAY;
        out->empty = !yyjson_arr_size(value);
    } else if (yyjson_is_obj(value)) {
        out->kind = JS_OBJECT;
        out->empty = !yyjson_obj_size(value);
    } else {
        PyNum number;
        if (json_number(value, site, &number)) {
            out->kind = number.is_float ? JS_FLOAT : JS_INT;
            if (number.is_float)
                out->value.f = number.f;
            else
                out->value.i = number.i;
        } else
            out->kind = JS_NULL;
    }
    return ERR_SUCCESS;
}
bool record_scalar_truthy(JScalar value) {
    switch (value.kind) {
    case JS_BOOL:
        return value.value.b;
    case JS_INT:
        return value.value.i != 0;
    case JS_FLOAT:
        return value.value.f != 0;
    case JS_STRING:
        return value.value.s.n > 0;
    case JS_ARRAY:
    case JS_OBJECT:
        return !value.empty;
    default:
        return false;
    }
}
static MaybeNum number_fact(PyNum number, bool nonnegative, const char *site, bool *range_noted) {
    MaybeNum result = {0};
    if (number.is_float && !isfinite(number.f))
        return result;
    if (nonnegative && (number.is_float ? number.f < 0 : number.i < 0))
        return result;
    result.present = pynum_timing_once(number, site, range_noted, &result.value);
    return result;
}
MaybeNum record_number(yyjson_val *value, bool nonnegative, const char *site) {
    PyNum number;
    return json_number(value, site, &number) ? number_fact(number, nonnegative, site, NULL)
                                             : (MaybeNum){0};
}
typedef struct {
    bool valid, range_noted;
    PyNum number;
} StartedConsumption;
static MaybeMs timestamp(yyjson_val *value) {
    MaybeMs ms = {0};
    Str text = record_string(value);
    if (text.p)
        ms.present = time_parse_rfc3339(text, "record.timestamp", &ms.value);
    return ms;
}
static MaybeMs event_time(yyjson_val *payload, MaybeMs wrapper, StartedConsumption *started,
                          Str *source) {
    Str kind = record_string(record_get(payload, "type"));
    const char *keys[2] = {"completed_at_ms", NULL};
    if (str_equal(kind, STR_LIT("task_started"))) {
        keys[0] = "started_at_ms";
        keys[1] = "started_at";
    } else if (str_equal(kind, STR_LIT("task_complete")) ||
               str_equal(kind, STR_LIT("turn_aborted")))
        keys[1] = "completed_at";
    *source = STR_LIT("record_timestamp");
    for (size_t i = 0; i < 2 && keys[i]; i++) {
        PyNum number;
        yyjson_val *value = record_get(payload, keys[i]);
        bool *range_noted = NULL;
        if (started && !strcmp(keys[i], "started_at")) {
            if (!started->valid)
                continue;
            number = started->number;
            range_noted = &started->range_noted;
        } else if (!json_number(value, keys[i], &number)) {
            continue;
        }
        MaybeMs ms = {0};
        bool milliseconds = i == 0;
        if (!pynum_epoch_ms_once(number, milliseconds, keys[i], range_noted, &ms.value))
            continue;
        ms.present = true;
        if (!milliseconds && wrapper.present) {
            int64_t low, high;
            int lower, upper;
            if (__builtin_sub_overflow(wrapper.value, INT64_C(2000), &low) ||
                __builtin_add_overflow(wrapper.value, INT64_C(2000), &high)) {
                event_note("tier2_time", "record.clock_threshold", 1);
            } else if (pynum_epoch_compare(number, low, &lower) &&
                       pynum_epoch_compare(number, high, &upper) && lower > 0 && upper < 0)
                return wrapper;
        }
        *source = (Str){keys[i], (uint32_t)strlen(keys[i])};
        return ms;
    }
    return wrapper;
}
MaybeMs record_event_time(yyjson_val *root, yyjson_val *payload, Str *source) {
    return event_time(payload, timestamp(record_get(root, "timestamp")), NULL, source);
}
static Err session_meta(LogRecord *out, yyjson_val *root, yyjson_val *payload, MaybeMs at,
                        SessionMeta *meta) {
    *meta = (SessionMeta){0};
    Err request_error = record_intern(out, record_string(record_get(payload, "session_id")),
                                     &meta->request_session_id);
    if (request_error.code)
        return request_error;
    yyjson_val *candidates[] = {record_get(payload, "id"),         record_get(root, "id"),
                                record_get(payload, "session_id"), record_get(payload, "sessionId"),
                                record_get(root, "session_id"),    record_get(root, "sessionId")};
    Err err = ERR_SUCCESS;
    for (size_t i = 0; i < 6; i++)
        if (yyjson_is_str(candidates[i])) {
            err = record_intern(out, record_string(candidates[i]), &meta->id);
            break;
        }
    if (err.code)
        return err;
    meta->created_at_ms = timestamp(record_get(payload, "timestamp"));
    if (!meta->created_at_ms.present)
        meta->created_at_ms = at;
    const char *parents[] = {"forked_from_id", "forkedFromId", "parent_session_id",
                             "parentSessionId"};
    for (size_t i = 0; i < 4; i++) {
        Str text = record_trim(record_string(record_get(payload, parents[i])), true);
        if (text.n) {
            err = record_intern(out, text, &meta->forked_from_id);
            break;
        }
    }
    if (err.code)
        return err;
    yyjson_val *source = record_get(payload, "source"), *subagent = record_get(source, "subagent");
    if (yyjson_is_str(source)) {
        Str lower;
        err = str_lower(&out->arena, record_trim(record_string(source), true), &lower);
        if (err.code)
            return err;
        meta->is_subagent = str_equal(lower, STR_LIT("subagent"));
    } else
        meta->is_subagent = yyjson_is_str(subagent) || yyjson_is_obj(subagent);
    yyjson_val *spawn = record_get(subagent, "thread_spawn"), *git = record_get(payload, "git");
    yyjson_val *raw = record_get(payload, "timestamp");
    if (!raw)
        raw = record_get(root, "timestamp");
    err = record_scalar(out, raw, "meta.timestamp_raw", &meta->timestamp_raw);
    if (err.code)
        return err;
    const char *keys[] = {"cwd",    "originator",     "cli_version",    "parent_thread_id",
                          "depth",  "agent_path",     "agent_nickname", "agent_role",
                          "branch", "repository_url", "commit_hash",    "thread_name"};
    JScalar *fields[] = {&meta->cwd,
                         &meta->originator,
                         &meta->cli_version,
                         &meta->parent_thread_id,
                         &meta->depth,
                         &meta->agent_path,
                         &meta->agent_nickname,
                         &meta->agent_role,
                         &meta->branch,
                         &meta->origin_url,
                         &meta->sha,
                         &meta->rollout_title};
    for (size_t i = 0; i < 12; i++) {
        yyjson_val *container = i < 3 || i == 11 ? payload : i < 8 ? spawn : git;
        err = record_scalar(out, record_get(container, keys[i]), keys[i], fields[i]);
        if (err.code)
            return err;
    }
    if (!record_scalar_truthy(meta->rollout_title))
        err = record_scalar(out, record_get(payload, "title"), "meta.title", &meta->rollout_title);
    return err;
}
typedef struct {
    LogRecord *out;
    Arena scratch;
    RecordFact *facts;
    size_t count, capacity, usage_capacity;
    Str wrappers[3];
    const ReaderCallbacks *raw_owner;
} ParseContext;
static Err chunk_callback(void *context) {
    ParseContext *parse = context;
    const ReaderCallbacks *owner = parse->raw_owner;
    return owner && owner->chunk ? owner->chunk(owner->context) : ERR_SUCCESS;
}
static Err raw_callback(void *context, const ReaderRawLine *line) {
    ParseContext *parse = context;
    const ReaderCallbacks *owner = parse->raw_owner;
    Err err = tokenstream_raw(&parse->out->token_stream, line);
    if (err.code) return err;
    return owner && owner->raw_line ? owner->raw_line(owner->context, line) : ERR_SUCCESS;
}
static Err line_callback(void *context, const ReaderRawLine *line, const JsonRead *json) {
    ParseContext *parse = context;
    Err err = tokenstream_decoded(&parse->out->token_stream, line, json);
    const ReaderCallbacks *owner = parse->raw_owner;
    return err.code || !owner || !owner->decoded_line ? err :
        owner->decoded_line(owner->context, line, json);
}
static Err decoded_callback(void *context, const ReaderRecord *record) {
    ParseContext *parse = context;
    LogRecord *out = parse->out;
    const ReaderCallbacks *owner = parse->raw_owner;
    if (owner && owner->record) {
        Err forwarded = owner->record(owner->context, record);
        if (forwarded.code) return forwarded;
    }
    RecordFact fact = {.rec = record->rec, .line = record->line};
    Err err;
    err = record_intern(out, record->kind, &fact.kind);
    if (err.code)
        return err;
    fact.wrapper_ms = timestamp(record_get(record->record, "timestamp"));
    StartedConsumption started = {0};
    started.valid = json_number(record_get(record->payload, "started_at"), "record.started_at",
                                &started.number);
    fact.at_ms = event_time(record->payload, fact.wrapper_ms, &started, &fact.ts_src);
    Str wrapper = record_string(record_get(record->record, "timestamp"));
    if (wrapper.p) {
        out->wrapper_count++;
        if (out->wrapper_distinct < 3) {
            bool seen = false;
            for (size_t i = 0; i < out->wrapper_distinct; i++)
                seen |= str_equal(wrapper, parse->wrappers[i]);
            if (!seen) {
                err = str_copy(&out->arena, wrapper, &parse->wrappers[out->wrapper_distinct++]);
                if (err.code)
                    return err;
            }
        }
    }
    Str turn = record_string(record_get(record->payload, "turn_id"));
    if (!record_identifier(turn, false) &&
        str_equal(record_string(record_get(record->record, "type")), STR_LIT("response_item")))
        turn = record_string(record_get(
            record_get(record->payload, "internal_chat_message_metadata_passthrough"), "turn_id"));
    if (record_identifier(turn, false)) {
        err = record_intern(out, turn, &fact.turn_id);
        if (err.code)
            return err;
    }
    Str thread = record_string(record_get(record->payload, "thread_id"));
    if (record_identifier(thread, false)) {
        err = record_intern(out, thread, &fact.thread_id);
        if (err.code)
            return err;
    }
    if (started.valid)
        fact.started_at =
            number_fact(started.number, false, "record.started_at", &started.range_noted);
    fact.reported_ms =
        record_number(record_get(record->payload, "duration_ms"), true, "record.duration_ms");
    fact.ttft_ms = record_number(record_get(record->payload, "time_to_first_token_ms"), true,
                                 "record.ttft_ms");
    fact.item_message = str_equal(fact.kind, STR_LIT("event_msg/item_completed/UserMessage")) ||
                        str_equal(fact.kind, STR_LIT("event_msg/item_completed/AgentMessage"));
    if (str_equal(fact.kind, STR_LIT("session_meta"))) {
        SessionMeta meta;
        err = session_meta(out, record->record, record->payload, fact.at_ms, &meta);
        if (err.code)
            return err;
        fact.meta_id = meta.id;
        if (!out->has_meta) {
            out->meta = meta;
            out->has_meta = true;
        } else
            out->extra_meta_count++;
        if (str_equal(out->status, STR_LIT("empty")))
            out->status = STR_LIT("header_only");
    } else
        out->status = STR_LIT("ok");
    err = message_candidate(out, record->payload, fact.kind, &fact.message, &fact.has_message);
    if (err.code)
        return err;
    err = voice_segment(out, record->payload, fact.kind, &fact.voice, &fact.has_voice);
    if (err.code)
        return err;
    err = tool_candidate(out, record->record, record->payload, fact.kind, &fact.tool);
    if (err.code) {
        tool_counts_destroy(&fact.tool.counts);
        return err;
    }
    err = link_candidate(out, record->payload, fact.kind, &fact.link);
    if (err.code) {
        tool_counts_destroy(&fact.tool.counts);
        return err;
    }
    err = record_append(&parse->scratch, (void **)&parse->facts, &parse->count, &parse->capacity,
                        sizeof fact, &fact);
    if (err.code) {
        tool_counts_destroy(&fact.tool.counts);
        return err;
    }
    if (str_equal(fact.kind, STR_LIT("token_usage_record"))) {
        UsageRecord row = {.line = fact.line,
                           .rec = fact.rec,
                           .at_ms = fact.at_ms,
                           .timestamp_unix_ms = fact.wrapper_ms};
        const char *ids[] = {"response_id", "thread_id", "session_id", "root_turn_id"};
        JScalar *fields[] = {&row.response_id, &row.thread_id, &row.session_id, &row.root_turn_id};
        for (size_t i = 0; i < 4; i++) {
            err = record_scalar(out, record_get(record->payload, ids[i]), ids[i], fields[i]);
            if (err.code)
                return err;
        }
        err = record_scalar(out, record_turn_id(record->payload), "usage.turn", &row.turn_id);
        if (err.code)
            return err;
        err = record_scalar(out, record_get(record->record, "timestamp"), "usage.ts", &row.ts);
        if (err.code)
            return err;
        const char *tokens[] = {"input_tokens",
                                "cached_input_tokens",
                                "cache_read_input_tokens",
                                "cache_write_input_tokens",
                                "output_tokens",
                                "reasoning_output_tokens"};
        JScalar *values[] = {&row.input,       &row.cached_input, &row.cache_read_input,
                             &row.cache_write, &row.output,       &row.reasoning};
        yyjson_val *usage = record_get(record->payload, "usage");
        for (size_t i = 0; i < 6; i++) {
            err = record_scalar(out, record_get(usage, tokens[i]), tokens[i], values[i]);
            if (err.code)
                return err;
        }
        const char *total_keys[] = {"thread_token_usage", "turn_token_usage"};
        UsageScalars *totals[] = {&row.thread_usage, &row.turn_usage};
        for (size_t i = 0; i < 2; i++) {
            yyjson_val *total = record_get(record->payload, total_keys[i]);
            const char *keys[] = {"input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens"};
            JScalar *fields[] = {&totals[i]->input, &totals[i]->cached_input, &totals[i]->output, &totals[i]->reasoning};
            for (size_t j = 0; j < 4; j++) {
                err = record_scalar(out, record_get(total, keys[j]), keys[j], fields[j]);
                if (err.code)
                    return err;
            }
        }
        err = record_append(&out->arena, (void **)&out->usage_records, &out->usage_count,
                            &parse->usage_capacity, sizeof row, &row);
    }
    return err;
}
void record_destroy(LogRecord *out) {
    for (OmapEntry *entry = out->tools.first; entry; entry = entry->next) {
        ToolTally *tally = entry->value;
        tool_counts_destroy(&tally->structured);
        tool_counts_destroy(&tally->raw);
    }
    omap_destroy(&out->tools);
    reader_result_destroy(&out->reader);
    arena_destroy(&out->arena);
    *out = (LogRecord){0};
}
Err record_parse(const DiscoveredLog *snapshot, Intern *identifiers,
                 const ReaderCallbacks *raw_owner, LogRecord *out) {
    out->identifiers = identifiers;
    out->key = *snapshot;
    out->status = STR_LIT("empty");
    out->token_stream.arena = &out->arena;
    out->token_stream.identifiers = identifiers;
    char *path = NULL;
    Err err = file_codex_path_key(snapshot->path.p, &path);
    if (err.code)
        return err;
    err = record_intern(out, (Str){path, (uint32_t)strlen(path)}, &out->key.path);
    free(path);
    if (err.code)
        return err;
    ParseContext context = {.out = out, .raw_owner = raw_owner};
    TurnBuilder turns = {0};
    ReaderCallbacks callbacks = {.context = &context, .chunk = chunk_callback, .raw_line = raw_callback,
        .record = decoded_callback, .decoded_line = line_callback};
    err = reader_read_log(snapshot, &callbacks, &out->reader);
    if (!err.code)
        err = history_build(out, context.facts, context.count);
    if (!err.code)
        err = turns_build(out, context.facts, context.count, &turns);
    if (!err.code)
        err = messages_build(out, context.facts, context.count);
    if (!err.code)
        err = voice_build(out, context.facts, context.count, &turns);
    if (!err.code)
        err = tools_build(out, context.facts, context.count);
    if (!err.code)
        err = links_build(out, context.facts, context.count);
    for (size_t i = 0; i < context.count; i++)
        tool_counts_destroy(&context.facts[i].tool.counts);
    omap_destroy(&turns.keyed);
    arena_destroy(&context.scratch);
    return err;
}
