#include "links.h"
#include <stdalign.h>

static Err identifier(LogRecord *record, yyjson_val *value, Str *out) {
    Str text = record_string(value);
    return record_identifier(text, true) ? record_intern(record, text, out)
                                         : (*out = (Str){0}, ERR_SUCCESS);
}
static Err json_field(LogRecord *record, yyjson_val *value, const char *key, Str *out) {
    *out = (Str){0};
    if (!yyjson_is_str(value))
        return ERR_SUCCESS;
    JsonRead read = json_read(record_string(value), STR, JSON_CONSTANTS_ALLOW, "links.json_fields");
    Err err = ERR_SUCCESS;
    if (read.status == JSON_NOMEM)
        err = err_make(ERR_NOMEM, "link JSON allocation failed");
    else if (read.status == JSON_OK)
        err = identifier(record, record_get(yyjson_doc_get_root(read.doc), key), out);
    json_read_free(&read);
    return err;
}
Err link_candidate(LogRecord *record, yyjson_val *payload, Str kind, LinkCandidate *out) {
    *out = (LinkCandidate){0};
    Err err = ERR_SUCCESS;
    yyjson_val *item = record_get(payload, "item");
    if (str_equal(kind, STR_LIT("event_msg/item_completed/SubAgentActivity"))) {
        out->kind = LINK_ACTIVITY;
        err = identifier(record, record_get(item, "kind"), &out->first);
        if (!err.code)
            err = identifier(record, record_get(item, "agent_thread_id"), &out->second);
        if (!err.code)
            err = identifier(record, record_get(item, "agent_path"), &out->third);
    } else if (str_equal(kind, STR_LIT("event_msg/item_completed/CollabAgentToolCall"))) {
        out->kind = LINK_RECEIVERS;
        size_t i, n, capacity = 0;
        yyjson_val *value;
        yyjson_arr_foreach(record_get(item, "receiver_thread_ids"), i, n, value) {
            Str id;
            err = identifier(record, value, &id);
            if (err.code)
                break;
            if (!id.p)
                continue;
            err = record_append(&record->arena, (void **)&out->receivers, &out->count, &capacity,
                                sizeof id, &id);
            if (err.code)
                break;
        }
    } else if (str_equal(kind, STR_LIT("response_item/function_call")) &&
               str_equal(record_string(record_get(payload, "namespace")),
                         STR_LIT("collaboration"))) {
        Str name = record_string(record_get(payload, "name"));
        if (str_equal(name, STR_LIT("spawn_agent"))) {
            out->kind = LINK_SPAWN;
            err = identifier(record, record_get(payload, "call_id"), &out->first);
        } else if (str_equal(name, STR_LIT("followup_task")) ||
                   str_equal(name, STR_LIT("send_message"))) {
            out->kind = LINK_TARGET;
            err = json_field(record, record_get(payload, "arguments"), "target", &out->first);
        }
    } else if (str_equal(kind, STR_LIT("response_item/function_call_output"))) {
        out->kind = LINK_OUTPUT;
        err = identifier(record, record_get(payload, "call_id"), &out->first);
        if (!err.code)
            err = json_field(record, record_get(payload, "output"), "task_name", &out->second);
    }
    return err;
}
typedef struct {
    size_t spawns, outputs, index;
    Str task_name;
} Join;
static Err join_get(LogRecord *record, Omap *map, Str id, Join **out) {
    *out = omap_get(map, id);
    if (*out)
        return ERR_SUCCESS;
    Err err = arena_alloc(&record->arena, sizeof **out, alignof(Join), (void **)out);
    if (err.code)
        return err;
    **out = (Join){0};
    return omap_put(map, id, *out);
}
Err links_build(LogRecord *record, RecordFact *facts, size_t count) {
    Omap joins = {0};
    size_t activity_capacity = 0, spawn_capacity = 0, target_capacity = 0, receiver_capacity = 0;
    Err err = ERR_SUCCESS;
    for (size_t i = 0; i < count; i++) {
        RecordFact *fact = &facts[i];
        if (fact->inherited)
            continue;
        LinkCandidate *link = &fact->link;
        if (link->kind == LINK_ACTIVITY) {
            ActivityLink activity = {link->first, link->second, link->third, fact->turn_key};
            err =
                record_append(&record->arena, (void **)&record->activities, &record->activity_count,
                              &activity_capacity, sizeof activity, &activity);
        } else if (link->kind == LINK_TARGET) {
            TargetLink target = {link->first, fact->turn_key};
            err = record_append(&record->arena, (void **)&record->targets, &record->target_count,
                                &target_capacity, sizeof target, &target);
        } else if (link->kind == LINK_RECEIVERS) {
            for (size_t j = 0; j < link->count; j++) {
                ReceiverLink receiver = {link->receivers[j], fact->turn_key};
                err = record_append(&record->arena, (void **)&record->receivers,
                                    &record->receiver_count, &receiver_capacity, sizeof receiver,
                                    &receiver);
                if (err.code)
                    break;
            }
        } else if (link->kind == LINK_SPAWN) {
            SpawnLink spawn = {.turn_key = fact->turn_key, .at_ms = fact->at_ms};
            size_t index = record->spawn_count;
            err = record_append(&record->arena, (void **)&record->spawns, &record->spawn_count,
                                &spawn_capacity, sizeof spawn, &spawn);
            if (!err.code && link->first.p) {
                Join *join;
                err = join_get(record, &joins, link->first, &join);
                if (!err.code) {
                    join->spawns++;
                    join->index = index;
                }
            }
        } else if (link->kind == LINK_OUTPUT && link->first.p) {
            Join *join;
            err = join_get(record, &joins, link->first, &join);
            if (!err.code) {
                join->outputs++;
                join->task_name = link->second;
            }
        }
        if (err.code)
            break;
    }
    if (!err.code)
        for (OmapEntry *entry = joins.first; entry; entry = entry->next) {
            Join *join = entry->value;
            if (join->spawns == 1 && join->outputs == 1)
                record->spawns[join->index].task_name = join->task_name;
        }
    omap_destroy(&joins);
    return err;
}
