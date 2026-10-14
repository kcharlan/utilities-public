#include "classify.h"
#include <stdlib.h>
#include <string.h>

static Str type_string(yyjson_val *value) {
    return yyjson_is_str(value)
        ? (Str){yyjson_get_str(value), (uint32_t)yyjson_get_len(value)}
        : STR_LIT("unknown");
}

Err record_type_key(yyjson_val *record, Str *key) {
    *key = (Str){0};
    yyjson_val *type = obj_get_last(record, STR_LIT("type"));
    Str parts[3] = {type_string(type)};
    size_t count = 1;
    if (!type) {
        const char *names[] = {"data", "result", "response"};
        bool usage = yyjson_is_obj(obj_get_last(record, STR_LIT("usage")));
        for (size_t i = 0; i < 3 && !usage; i++) {
            yyjson_val *container = obj_get_last(record, (Str){names[i], (uint32_t)strlen(names[i])});
            usage = yyjson_is_obj(obj_get_last(container, STR_LIT("usage")));
        }
        if (usage) parts[0] = STR_LIT("bare_usage");
    }
    if (str_equal(parts[0], STR_LIT("event_msg")) || str_equal(parts[0], STR_LIT("response_item"))) {
        yyjson_val *payload = obj_get_last(record, STR_LIT("payload"));
        parts[count++] = type_string(obj_get_last(payload, STR_LIT("type")));
        if (str_equal(parts[0], STR_LIT("event_msg")) && str_equal(parts[1], STR_LIT("item_completed"))) {
            yyjson_val *item = obj_get_last(payload, STR_LIT("item"));
            parts[count++] = type_string(obj_get_last(item, STR_LIT("type")));
        }
    }
    size_t length = count - 1;
    for (size_t i = 0; i < count; i++) length += parts[i].n;
    if (length > UINT32_MAX) return err_make(ERR_INVALID, "record type exceeds string capacity");
    char *text = malloc(length + 1);
    if (!text) return err_make(ERR_NOMEM, "record type allocation failed");
    size_t offset = 0;
    for (size_t i = 0; i < count; i++) {
        if (i) text[offset++] = '/';
        memcpy(text + offset, parts[i].p, parts[i].n);
        offset += parts[i].n;
    }
    text[offset] = 0;
    *key = (Str){text, (uint32_t)length};
    return ERR_SUCCESS;
}

bool record_type_known(Str key) {
    static const char *const known[] = {
        "session_meta", "turn_context", "token_usage_record", "world_state", "compacted",
        "inter_agent_communication_metadata", "realtime_item", "bare_usage",
        "event_msg/task_started", "event_msg/task_complete", "event_msg/turn_aborted",
        "event_msg/thread_settings_applied", "event_msg/token_count",
        "event_msg/user_message", "event_msg/agent_message",
        "event_msg/item_completed/UserMessage", "event_msg/item_completed/AgentMessage",
        "event_msg/item_completed/CommandExecution", "event_msg/item_completed/FileChange",
        "event_msg/item_completed/McpToolCall", "event_msg/item_completed/WebSearch",
        "event_msg/item_completed/ImageView", "event_msg/item_completed/Extension",
        "event_msg/item_completed/SubAgentActivity", "event_msg/item_completed/CollabAgentToolCall",
        "event_msg/item_completed/Reasoning", "event_msg/item_completed/ContextCompaction",
        "event_msg/item_completed/Plan", "response_item/message", "response_item/function_call",
        "response_item/custom_tool_call", "response_item/local_shell_call", "response_item/web_search_call",
        "response_item/tool_search_call", "response_item/function_call_output",
        "response_item/custom_tool_call_output", "response_item/local_shell_call_output",
        "response_item/reasoning", "response_item/tool_search_output", "response_item/agent_message"
    };
    for (size_t i = 0; i < sizeof known / sizeof *known; i++)
        if (str_equal(key, (Str){known[i], (uint32_t)strlen(known[i])})) return true;
    return false;
}
