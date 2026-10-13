#include "turns.h"
#include <stdalign.h>
#include <stdio.h>

static Err new_turn(LogRecord *record, Str id, size_t *capacity, Omap *by_id, TurnFact **out) {
    TurnFact *turn;
    Err err = arena_alloc(&record->arena, sizeof *turn, alignof(TurnFact), (void **)&turn);
    if (err.code)
        return err;
    *turn = (TurnFact){.turn_id = id, .end_kind = STR_LIT("open")};
    if (id.p)
        turn->key = id;
    else {
        char key[64];
        int n = snprintf(key, sizeof key, "turn-%zu", record->turn_count + 1);
        err = record_intern(record, (Str){key, (uint32_t)n}, &turn->key);
        if (err.code)
            return err;
    }
    err = record_append(&record->arena, (void **)&record->turns, &record->turn_count, capacity,
                        sizeof turn, &turn);
    if (err.code)
        return err;
    if (id.p) {
        err = omap_put(by_id, id, turn);
        if (err.code)
            return err;
    }
    *out = turn;
    return ERR_SUCCESS;
}
static Err key_state(LogRecord *record, TurnBuilder *builder, Str key, TurnKeyState **out) {
    *out = omap_get(&builder->keyed, key);
    if (*out)
        return ERR_SUCCESS;
    Err err = arena_alloc(&record->arena, sizeof **out, alignof(TurnKeyState), (void **)out);
    if (err.code)
        return err;
    **out = (TurnKeyState){.key = key};
    return omap_put(&builder->keyed, key, *out);
}
Err turns_build(LogRecord *record, RecordFact *facts, size_t count, TurnBuilder *builder) {
    Omap by_id = {0};
    TurnFact *current = NULL;
    size_t capacity = 0;
    Err err = ERR_SUCCESS;
    bool unresolved = str_equal(record->history.method, STR_LIT("unresolved"));
    for (size_t i = 0; i < count; i++) {
        RecordFact *fact = &facts[i];
        if (fact->inherited)
            continue;
        if (fact->at_ms.present) {
            if (!record->first_ms.present || fact->at_ms.value < record->first_ms.value)
                record->first_ms = fact->at_ms;
            if (!record->last_ms.present || fact->at_ms.value > record->last_ms.value)
                record->last_ms = fact->at_ms;
        }
        if (unresolved)
            continue;
        bool start = str_equal(fact->kind, STR_LIT("event_msg/task_started"));
        bool end = str_equal(fact->kind, STR_LIT("event_msg/task_complete")) ||
                   str_equal(fact->kind, STR_LIT("event_msg/turn_aborted"));
        TurnFact *turn = fact->turn_id.p ? omap_get(&by_id, fact->turn_id) : current;
        if (start) {
            if (!fact->turn_id.p)
                turn = NULL;
            if (current && str_equal(current->end_kind, STR_LIT("open")) &&
                current->has_start_rec) {
                TurnKeyState *state = omap_get(&builder->keyed, current->key);
                state->has_span_end = true;
                state->span_end = fact->rec - 1;
                current->end_kind = STR_LIT("interrupted");
                current->end_ms = current->last_ms;
                current->end_src = state->last_src;
            }
            if (!turn) {
                err = new_turn(record, fact->turn_id, &capacity, &by_id, &turn);
                if (err.code)
                    break;
            }
            TurnKeyState *state;
            err = key_state(record, builder, turn->key, &state);
            if (err.code)
                break;
            turn->start_ms = fact->at_ms;
            turn->start_src = fact->ts_src;
            turn->has_start_rec = true;
            turn->start_rec = fact->rec;
            turn->end_ms = (MaybeMs){0};
            turn->end_src = (Str){0};
            turn->end_kind = STR_LIT("open");
            current = turn;
            state->has_span = true;
            state->span_start = fact->rec;
            state->has_span_end = false;
        } else if (end) {
            if (!turn) {
                err = new_turn(record, fact->turn_id, &capacity, &by_id, &turn);
                if (err.code)
                    break;
            }
            TurnKeyState *state;
            err = key_state(record, builder, turn->key, &state);
            if (err.code)
                break;
            if (!turn->has_start_rec && fact->started_at.present) {
                turn->start_ms.present = pynum_epoch_ms(fact->started_at.value, false,
                                                        "turn.started_at", &turn->start_ms.value);
                turn->start_src = STR_LIT("started_at");
            }
            turn->end_ms = fact->at_ms;
            turn->end_src = fact->ts_src;
            turn->end_kind = str_equal(fact->kind, STR_LIT("event_msg/task_complete"))
                                 ? STR_LIT("completed")
                                 : STR_LIT("aborted");
            turn->reported_ms = fact->reported_ms;
            turn->ttft_ms = fact->ttft_ms;
            state->has_completion = true;
            state->completion_rec = fact->rec;
            if (state->has_span) {
                state->has_span_end = true;
                state->span_end = fact->rec;
            }
            if (turn == current)
                current = NULL;
        }
        if (turn && fact->at_ms.present &&
            (!turn->last_ms.present || fact->at_ms.value >= turn->last_ms.value)) {
            turn->last_ms = fact->at_ms;
            TurnKeyState *state = omap_get(&builder->keyed, turn->key);
            state->last_src = fact->ts_src;
        }
        if (turn)
            fact->turn_key = turn->key;
    }
    /* Final-ID fallback applies only to downstream candidates, never last_ms. */
    if (!err.code)
        for (size_t i = 0; i < count; i++)
            if (!facts[i].inherited && !facts[i].turn_key.p && facts[i].turn_id.p) {
                TurnFact *turn = omap_get(&by_id, facts[i].turn_id);
                if (turn)
                    facts[i].turn_key = turn->key;
            }
    omap_destroy(&by_id);
    return err;
}
TurnTiming turn_timing(const TurnFact *turn, bool collapsed) {
    TurnTiming result = {0};
    if (turn->start_ms.present)
        result.start_ms = (MaybeNum){true, {.i = turn->start_ms.value}};
    if (turn->start_ms.present && !turn->has_start_rec &&
        str_equal(turn->start_src, STR_LIT("started_at")))
        result.flags[result.flag_count++] = STR_LIT("start_from_completion");
    if (str_equal(turn->end_kind, STR_LIT("open")))
        return result;
    if (collapsed && !turn->reported_ms.present &&
        str_equal(turn->start_src, STR_LIT("record_timestamp")) &&
        str_equal(turn->end_src, STR_LIT("record_timestamp")))
        result.flags[result.flag_count++] = STR_LIT("collapsed");
    else if (turn->reported_ms.present && turn->end_ms.present &&
             (!turn->start_ms.present || collapsed ||
              str_equal(turn->end_src, STR_LIT("completed_at")))) {
        result.start_ms.present =
            pynum_sub((PyNum){.i = turn->end_ms.value}, turn->reported_ms.value,
                      "turn.reported_duration", &result.start_ms.value);
        result.duration_ms = turn->reported_ms;
        result.flags[result.flag_count++] = STR_LIT("reported_duration");
    } else if (turn->start_ms.present && turn->end_ms.present &&
               turn->end_ms.value >= turn->start_ms.value) {
        result.duration_ms.present =
            pynum_sub((PyNum){.i = turn->end_ms.value}, (PyNum){.i = turn->start_ms.value},
                      "turn.duration", &result.duration_ms.value);
    } else
        result.flags[result.flag_count++] = STR_LIT("unknown_duration");
    return result;
}
