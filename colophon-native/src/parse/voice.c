#include "voice.h"
#include "out/jsonw.h"
#include "util/sort.h"
#include <stdalign.h>
#include <stdlib.h>

Err voice_segment(LogRecord *record, yyjson_val *payload, Str kind, VoiceSegment *out,
                  bool *present) {
    *present = false;
    *out = (VoiceSegment){0};
    Str role = record_string(record_get(payload, "role"));
    if (!str_equal(kind, STR_LIT("realtime_item")) ||
        !str_equal(record_string(record_get(payload, "type")), STR_LIT("transcript_segment")) ||
        (!str_equal(role, STR_LIT("user")) && !str_equal(role, STR_LIT("assistant"))) ||
        !yyjson_is_str(record_get(payload, "text")))
        return ERR_SUCCESS;
    out->role = str_equal(role, STR_LIT("user")) ? STR_LIT("user") : STR_LIT("assistant");
    Err err = str_copy(&record->arena, record_string(record_get(payload, "text")), &out->text);
    *present = !err.code;
    return err;
}
typedef struct {
    Str role, text;
    uint64_t rec;
    MaybeMs at_ms;
} Run;
typedef struct {
    uint64_t at, end;
    bool has_end;
    Str key;
} Boundary;
static int boundary_order(const void *a, const void *b, void *context) {
    (void)context;
    const Boundary *x = a, *y = b;
    int order = (x->at > y->at) - (x->at < y->at);
    if (!order && x->has_end && y->has_end)
        order = (x->end > y->end) - (x->end < y->end);
    return order ? order : str_compare(x->key, y->key);
}
static size_t after_boundary(const Boundary *items, size_t count, uint64_t rec) {
    size_t low = 0, high = count;
    while (low < high) {
        size_t mid = (low + high) / 2;
        if (items[mid].at <= rec)
            low = mid + 1;
        else
            high = mid;
    }
    return low;
}
static Err finish_run(LogRecord *record, JsonWriter *text, Run *run, Run **runs, size_t *count,
                      size_t *capacity) {
    Err err = text->error.code
                  ? text->error
                  : str_copy(&record->arena, (Str){text->data, (uint32_t)text->length}, &run->text);
    if (!err.code)
        err = record_append(&record->arena, (void **)runs, count, capacity, sizeof *run, run);
    text->length = 0;
    return err;
}
Err voice_build(LogRecord *record, RecordFact *facts, size_t count, const TurnBuilder *builder) {
    Run *runs = NULL, run = {0};
    size_t run_count = 0, capacity = 0;
    JsonWriter text = {0};
    Err err = ERR_SUCCESS;
    size_t parts = 0;
    for (size_t i = 0; i < count; i++)
        if (!facts[i].inherited && facts[i].has_voice) {
            RecordFact *fact = &facts[i];
            if (!run.role.p || !str_equal(run.role, fact->voice.role)) {
                if (run.role.p) {
                    err = finish_run(record, &text, &run, &runs, &run_count, &capacity);
                    if (err.code)
                        goto done;
                }
                run = (Run){.role = fact->voice.role, .rec = fact->rec, .at_ms = fact->at_ms};
                parts = 0;
            }
            if (parts++)
                jsonw_raw(&text, " ");
            jsonw_bytes(&text, fact->voice.text.p, fact->voice.text.n);
        }
    if (run.role.p) {
        err = finish_run(record, &text, &run, &runs, &run_count, &capacity);
        if (err.code)
            goto done;
    }
    Boundary *spans = NULL, *boundaries = NULL;
    size_t span_count = 0, boundary_count = 0, span_capacity = 0, boundary_capacity = 0;
    for (size_t i = 0; i < record->turn_count; i++) {
        TurnFact *turn = record->turns[i];
        const TurnKeyState *state = omap_get(&builder->keyed, turn->key);
        if (turn->has_start_rec || state->has_completion) {
            Boundary boundary = {.at =
                                     turn->has_start_rec ? turn->start_rec : state->completion_rec,
                                 .key = turn->key};
            err = record_append(&record->arena, (void **)&boundaries, &boundary_count,
                                &boundary_capacity, sizeof boundary, &boundary);
            if (err.code)
                break;
        }
    }
    for (OmapEntry *entry = builder->keyed.first; !err.code && entry; entry = entry->next) {
        const TurnKeyState *state = entry->value;
        if (!state->has_span)
            continue;
        Boundary span = {state->span_start, state->span_end, state->has_span_end, state->key};
        err = record_append(&record->arena, (void **)&spans, &span_count, &span_capacity,
                            sizeof span, &span);
    }
    if (err.code)
        goto done;
    err = stable_sort(spans, span_count, sizeof *spans, boundary_order, NULL);
    if (err.code)
        goto done;
    err = stable_sort(boundaries, boundary_count, sizeof *boundaries, boundary_order, NULL);
    if (err.code)
        goto done;
    size_t request_capacity = 0, reply_capacity = 0, last_request = SIZE_MAX;
    for (size_t i = 0; i < run_count; i++) {
        Run *value = &runs[i];
        size_t previous = after_boundary(spans, span_count, value->rec);
        if (str_equal(value->role, STR_LIT("assistant"))) {
            if (last_request != SIZE_MAX)
                record->requests[last_request].reply = value->text;
            else if (previous || !record->turn_count) {
                VoiceReply reply = {value->text, previous ? spans[previous - 1].key : (Str){0},
                                    value->at_ms};
                err = record_append(&record->arena, (void **)&record->replies, &record->reply_count,
                                    &reply_capacity, sizeof reply, &reply);
                if (err.code)
                    goto done;
            }
            continue;
        }
        VoiceRequest request = {.text = value->text, .at_ms = value->at_ms};
        if (previous && (!spans[previous - 1].has_end || value->rec <= spans[previous - 1].end))
            request.turn_key = spans[previous - 1].key;
        else if (previous < span_count) {
            request.turn_key = spans[previous].key;
            request.before_turn = true;
        } else {
            size_t boundary = after_boundary(boundaries, boundary_count, value->rec);
            if (boundary) {
                request.turn_key = boundaries[boundary - 1].key;
                request.follow_up = true;
            }
        }
        last_request = record->request_count;
        err = record_append(&record->arena, (void **)&record->requests, &record->request_count,
                            &request_capacity, sizeof request, &request);
        if (err.code)
            goto done;
    }
done:
    jsonw_free(&text);
    return err;
}
