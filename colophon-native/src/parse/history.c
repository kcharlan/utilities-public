#include "history.h"
#include "util/events.h"
#include <ctype.h>
#include <stdlib.h>
#include <string.h>

static bool uuid_time(Str id, int64_t *out) {
    if (id.n != 36)
        return false;
    uint64_t value = 0;
    size_t digits = 0;
    for (size_t i = 0; i < id.n; i++) {
        if (i == 8 || i == 13 || i == 18 || i == 23) {
            if (id.p[i] != '-')
                return false;
            continue;
        }
        unsigned char c = (unsigned char)id.p[i];
        unsigned d;
        if (c >= '0' && c <= '9')
            d = c - '0';
        else if (c >= 'a' && c <= 'f')
            d = c - 'a' + 10;
        else if (c >= 'A' && c <= 'F')
            d = c - 'A' + 10;
        else
            return false;
        if (digits++ < 12)
            value = value * 16 + d;
    }
    if (id.p[14] != '7')
        return false;
    *out = (int64_t)value;
    return true;
}
static bool threshold(int64_t created, int64_t delta, int64_t *out) {
    if (!__builtin_add_overflow(created, delta, out))
        return true;
    event_note("tier2_time", "history.threshold", 1);
    return false;
}
static Str synthetic_key(PyNum number, unsigned char key[9]) {
    if (number.is_float && number.f >= -0x1p63 && number.f < 0x1p63 &&
        pynum_equal(number, (PyNum){.i = (int64_t)number.f}))
        number = (PyNum){.i = (int64_t)number.f};
    key[0] = number.is_float;
    if (number.is_float)
        memcpy(key + 1, &number.f, 8);
    else
        memcpy(key + 1, &number.i, 8);
    return (Str){(const char *)key, 9};
}
static Err ranges(LogRecord *record, RecordFact *facts, size_t count, bool lines) {
    RecordRange **data = lines ? &record->history.inherited_lines : &record->history.inherited_recs;
    size_t *length = lines ? &record->history.line_count : &record->history.rec_count, capacity = 0;
    for (size_t i = 0; i < count; i++)
        if (facts[i].inherited) {
            uint64_t at = lines ? facts[i].line : facts[i].rec;
            if (*length && (*data)[*length - 1].end == at)
                (*data)[*length - 1].end = at + 1;
            else {
                RecordRange range = {at, at + 1};
                Err err = record_append(&record->arena, (void **)data, length, &capacity,
                                        sizeof range, &range);
                if (err.code)
                    return err;
            }
        }
    return ERR_SUCCESS;
}
Err history_build(LogRecord *record, RecordFact *facts, size_t count) {
    History *history = &record->history;
    history->path = STR_LIT("none");
    MaybeMs created = record->has_meta ? record->meta.created_at_ms : (MaybeMs){0};
    for (size_t i = 0; i < count; i++)
        facts[i].inherited =
            created.present && facts[i].at_ms.present && facts[i].at_ms.value < created.value;
    int64_t before = 0, after = 0;
    bool has_before = created.present && threshold(created.value, -1000, &before),
         has_after = created.present && threshold(created.value, 1000, &after);
    if (record->has_meta && record->meta.forked_from_id.p) {
        history->path = STR_LIT("A");
        history->has_boundary = true;
        history->boundary_rec = count;
        history->method = STR_LIT("unresolved");
        /* Synthetic starts are keyed by numeric equality, not JSON spelling.
         * Only this compact numeric evidence survives phase one. */
        Omap synthetic = {0};
        Err err = ERR_SUCCESS;
        for (size_t i = 0; i < count; i++) {
            RecordFact *fact = &facts[i];
            bool start = str_equal(fact->kind, STR_LIT("event_msg/task_started"));
            if (!start && !str_equal(fact->kind, STR_LIT("event_msg/task_complete")))
                continue;
            if (start && record_prefix(fact->turn_id, "rollout-")) {
                if (fact->started_at.present) {
                    /* Numeric key canonicalization merges exact integral floats
                     * with ints. Byte keys are private binary, never text IDs. */
                    unsigned char key[9];
                    err = omap_put(&synthetic, synthetic_key(fact->started_at.value, key), fact);
                    if (err.code)
                        break;
                }
                continue;
            }
            int64_t id_time;
            bool uuid = uuid_time(fact->turn_id, &id_time);
            bool owned = uuid && has_before && id_time >= before;
            int comparison;
            if (fact->started_at.present && has_before &&
                pynum_epoch_compare(fact->started_at.value, before, &comparison) && comparison < 0)
                owned = false;
            if (start && !uuid && has_after && fact->wrapper_ms.present &&
                fact->wrapper_ms.value >= after)
                owned = true;
            if (!owned)
                continue;
            RecordFact *match = NULL;
            if (!start && fact->started_at.present) {
                unsigned char key[9];
                match = omap_get(&synthetic, synthetic_key(fact->started_at.value, key));
            }
            history->boundary_rec = match ? match->rec : fact->rec;
            history->method = match ? STR_LIT("synthetic_start_verified_by_completion")
                                    : STR_LIT("own_lifecycle");
            break;
        }
        omap_destroy(&synthetic);
        if (err.code)
            return err;
        for (size_t i = 1; i < history->boundary_rec; i++)
            facts[i].inherited = true;
    } else if (record->has_meta) {
        history->path = STR_LIT("B");
        bool in_run = false, seen = false;
        Str id = record_identifier(record->meta.id, true) ? record->meta.id : (Str){0};
        for (size_t i = 0; i < count; i++) {
            RecordFact *fact = &facts[i];
            if (str_equal(fact->kind, STR_LIT("session_meta"))) {
                if (seen && id.p && record_identifier(fact->meta_id, true) &&
                    !str_equal(id, fact->meta_id))
                    in_run = true;
                seen = true;
            }
            bool own = false;
            int comparison;
            if (str_equal(fact->kind, STR_LIT("event_msg/task_started")) && created.present) {
                own = fact->started_at.present
                          ? (has_before &&
                             pynum_epoch_compare(fact->started_at.value, before, &comparison) &&
                             comparison >= 0)
                          : has_after && fact->at_ms.present && fact->at_ms.value >= after;
            }
            if (in_run && (str_equal(fact->kind, STR_LIT("event_msg/thread_settings_applied")) ||
                           (id.p && str_equal(fact->thread_id, id)) || own))
                in_run = false;
            if (in_run)
                fact->inherited = true;
        }
    }
    Err err = ranges(record, facts, count, false);
    return err.code ? err : ranges(record, facts, count, true);
}
bool is_inherited(const LogRecord *record, uint64_t rec) {
    size_t low = 0, high = record->history.rec_count;
    while (low < high) {
        size_t mid = (low + high) / 2;
        RecordRange range = record->history.inherited_recs[mid];
        if (rec < range.start)
            high = mid;
        else if (rec >= range.end)
            low = mid + 1;
        else
            return true;
    }
    return false;
}
