#include "tools.h"
#include "util/json_number.h"
#include <stdalign.h>
#include <string.h>

void tool_counts_destroy(ToolCounts *counts) {
    omap_destroy(&counts->mcp);
    omap_destroy(&counts->other);
    *counts = (ToolCounts){0};
}
static Err group(LogRecord *record, Omap *groups, Str name, uint64_t amount) {
    if (!record_identifier(name, true))
        return ERR_SUCCESS;
    uint64_t *value = omap_get(groups, name);
    if (value) {
        *value += amount;
        return ERR_SUCCESS;
    }
    Err err = arena_alloc(&record->arena, sizeof *value, alignof(uint64_t), (void **)&value);
    if (err.code)
        return err;
    *value = amount;
    return omap_put(groups, name, value);
}
static bool named(Str value, const char *const *names, size_t count) {
    for (size_t i = 0; i < count; i++)
        if (str_equal(value, (Str){names[i], (uint32_t)strlen(names[i])}))
            return true;
    return false;
}
static bool structured(Str kind) {
    static const char *const names[] = {"CommandExecution", "FileChange", "McpToolCall",
                                        "WebSearch",        "ImageView",  "Extension"};
    return named(kind, names, sizeof names / sizeof *names);
}
static Err structured_count(LogRecord *record, yyjson_val *item, ToolCounts *counts) {
    Str type = record_string(record_get(item, "type")),
        kind = record_string(record_get(item, "kind"));
    if (str_equal(type, STR_LIT("CommandExecution"))) {
        counts->shell++;
        PyNum exit_code;
        if (json_number(record_get(item, "exit_code"), "tool.exit_code", &exit_code) &&
            !exit_code.is_float && exit_code.i)
            counts->shell_failed++;
    } else if (str_equal(type, STR_LIT("FileChange"))) {
        yyjson_val *changes = record_get(item, "changes");
        if (!yyjson_is_obj(changes))
            return ERR_SUCCESS;
        Omap keys = {0};
        size_t i, n;
        yyjson_val *key, *value;
        Err err = ERR_SUCCESS;
        yyjson_obj_foreach(changes, i, n, key, value) {
            (void)value;
            err = omap_put(&keys, record_string(key), (void *)1);
            if (err.code)
                break;
        }
        counts->file_edits = keys.size;
        omap_destroy(&keys);
        return err;
    } else if (str_equal(type, STR_LIT("McpToolCall")))
        return group(record, &counts->mcp, record_string(record_get(item, "server")), 1);
    else if (str_equal(type, STR_LIT("WebSearch")) || str_equal(kind, STR_LIT("web.search")))
        counts->web++;
    else if (str_equal(type, STR_LIT("ImageView")))
        counts->image++;
    else if (!str_equal(kind, STR_LIT("clock.sleep")))
        return group(record, &counts->other, kind, 1);
    return ERR_SUCCESS;
}
static Err js_name(LogRecord *record, ToolCounts *counts, Str name) {
    static const char *const ignored[] = {
        "write_stdin", "update_plan", "wait", "request_user_input", "request_user_input_async",
        "clock__sleep"};
    if (named(name, ignored, sizeof ignored / sizeof *ignored) ||
        record_prefix(name, "collaboration__"))
        return ERR_SUCCESS;
    if (str_equal(name, STR_LIT("exec_command")))
        counts->shell++;
    else if (str_equal(name, STR_LIT("apply_patch")))
        counts->file_edits++;
    else if (record_prefix(name, "mcp__")) {
        Str rest = {name.p + 5, name.n - 5};
        size_t split = 0;
        while (split + 1 < rest.n && !(rest.p[split] == '_' && rest.p[split + 1] == '_'))
            split++;
        if (split > 0 && split + 2 < rest.n)
            return group(record, &counts->mcp, (Str){rest.p, (uint32_t)split}, 1);
        return group(record, &counts->other, name, 1);
    } else if (str_equal(name, STR_LIT("web__run")))
        counts->web++;
    else if (str_equal(name, STR_LIT("view_image")))
        counts->image++;
    else
        return group(record, &counts->other, name, 1);
    return ERR_SUCCESS;
}
static bool ascii_first(char c) {
    return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || c == '_';
}
static bool ascii_rest(char c) {
    return ascii_first(c) || (c >= '0' && c <= '9');
}
static Err javascript(LogRecord *record, Str text, ToolCounts *counts) {
    size_t at = 0;
    uint32_t previous = 0;
    bool has_previous = false;
    while (at < text.n) {
        size_t start = at;
        uint32_t cp;
        if (!str_decode_next(text, &at, &cp))
            break;
        if (!has_previous ||
            (!str_word_codepoint(previous) && previous != '$' && previous != '.')) {
            Str suffix = {text.p + start, text.n - (uint32_t)start};
            if (record_prefix(suffix, "tools.")) {
                size_t begin = start + 6, end = begin;
                if (end < text.n && ascii_first(text.p[end])) {
                    end++;
                    while (end < text.n && ascii_rest(text.p[end]))
                        end++;
                    if (end < text.n && text.p[end] == '(') {
                        Err err =
                            js_name(record, counts, (Str){text.p + begin, (uint32_t)(end - begin)});
                        if (err.code)
                            return err;
                    }
                }
            } else if (record_prefix(suffix, "web.run("))
                counts->web++;
        }
        previous = cp;
        has_previous = true;
    }
    return ERR_SUCCESS;
}
static Err raw_count(LogRecord *record, yyjson_val *payload, ToolCounts *counts) {
    Str type = record_string(record_get(payload, "type")),
        name = record_string(record_get(payload, "name")),
        ns = record_string(record_get(payload, "namespace"));
    if (str_equal(type, STR_LIT("local_shell_call")))
        counts->shell++;
    else if (str_equal(type, STR_LIT("web_search_call")))
        counts->web++;
    else if (str_equal(type, STR_LIT("custom_tool_call"))) {
        if (str_equal(name, STR_LIT("apply_patch")))
            counts->file_edits++;
        else if (str_equal(name, STR_LIT("exec")) && yyjson_is_str(record_get(payload, "input")))
            return javascript(record, record_string(record_get(payload, "input")), counts);
    } else if (str_equal(type, STR_LIT("function_call")) && record_identifier(name, true)) {
        static const char *const ignored[] = {"update_plan",
                                              "request_user_input",
                                              "request_user_input_async",
                                              "write_stdin",
                                              "wait",
                                              "wait_agent",
                                              "list_agents",
                                              "spawn_agent",
                                              "followup_task",
                                              "send_message",
                                              "interrupt_agent"};
        yyjson_val *rawns = record_get(payload, "namespace");
        if (str_equal(ns, STR_LIT("collaboration")) || str_equal(ns, STR_LIT("clock")) ||
            named(name, ignored, sizeof ignored / sizeof *ignored))
            return ERR_SUCCESS;
        if (rawns && !yyjson_is_null(rawns) && !yyjson_is_str(rawns))
            return ERR_SUCCESS;
        if ((str_equal(name, STR_LIT("exec_command")) || str_equal(name, STR_LIT("shell"))) &&
            !ns.n)
            counts->shell++;
        else if (ns.n && record_prefix(ns, "mcp__"))
            return group(record, &counts->mcp, (Str){ns.p + 5, ns.n - 5}, 1);
        else if (str_equal(ns, STR_LIT("web")) && str_equal(name, STR_LIT("run")))
            counts->web++;
        else if (str_equal(name, STR_LIT("view_image")))
            counts->image++;
        else {
            if (!ns.n)
                return group(record, &counts->other, name, 1);
            size_t length = (size_t)ns.n + 1 + name.n;
            char *joined;
            Err err = arena_alloc(&record->arena, length, 1, (void **)&joined);
            if (err.code)
                return err;
            memcpy(joined, ns.p, ns.n);
            joined[ns.n] = ':';
            memcpy(joined + ns.n + 1, name.p, name.n);
            return group(record, &counts->other, (Str){joined, (uint32_t)length}, 1);
        }
    }
    return ERR_SUCCESS;
}
Err tool_candidate(LogRecord *record, yyjson_val *root, yyjson_val *payload, Str kind,
                   ToolCandidate *out) {
    *out = (ToolCandidate){0};
    Str type = record_string(record_get(record_get(payload, "item"), "type"));
    out->structured = record_prefix(kind, "event_msg/item_completed/") && structured(type);
    bool raw = str_equal(kind, STR_LIT("response_item/function_call")) ||
               str_equal(kind, STR_LIT("response_item/custom_tool_call")) ||
               str_equal(kind, STR_LIT("response_item/local_shell_call")) ||
               str_equal(kind, STR_LIT("response_item/web_search_call"));
    if (!out->structured && !raw)
        return ERR_SUCCESS;
    (void)root;
    Err err = out->structured ? structured_count(record, record_get(payload, "item"), &out->counts)
                              : raw_count(record, payload, &out->counts);
    out->present = out->structured || out->counts.shell || out->counts.file_edits ||
                   out->counts.web || out->counts.image || out->counts.mcp.size ||
                   out->counts.other.size;
    return err;
}
static Err merge(LogRecord *record, ToolCounts *out, ToolCounts *input) {
    out->shell += input->shell;
    out->shell_failed += input->shell_failed;
    out->file_edits += input->file_edits;
    out->web += input->web;
    out->image += input->image;
    Omap *targets[] = {&out->mcp, &out->other}, *sources[] = {&input->mcp, &input->other};
    for (size_t i = 0; i < 2; i++)
        for (OmapEntry *entry = sources[i]->first; entry; entry = entry->next) {
            Err err = group(record, targets[i], entry->key, *(uint64_t *)entry->value);
            if (err.code)
                return err;
        }
    return ERR_SUCCESS;
}
Err tools_build(LogRecord *record, RecordFact *facts, size_t count) {
    for (size_t i = 0; i < record->turn_count; i++) {
        ToolTally *tally;
        Err err = arena_alloc(&record->arena, sizeof *tally, alignof(ToolTally), (void **)&tally);
        if (err.code)
            return err;
        *tally = (ToolTally){0};
        err = omap_put(&record->tools, record->turns[i]->key, tally);
        if (err.code)
            return err;
    }
    for (size_t i = 0; i < count; i++) {
        RecordFact *fact = &facts[i];
        if (fact->inherited || !fact->tool.present || !fact->turn_key.p)
            continue;
        ToolTally *tally = omap_get(&record->tools, fact->turn_key);
        if (!tally)
            continue;
        if (fact->tool.structured)
            tally->has_structured = true;
        Err err = merge(record, fact->tool.structured ? &tally->structured : &tally->raw,
                        &fact->tool.counts);
        if (err.code)
            return err;
    }
    return ERR_SUCCESS;
}
