#include "messages.h"
#include "out/jsonw.h"
#include "util/sha1.h"
#include "util/sort.h"
#include <stdalign.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static bool matches(Str text, const char *const *values, size_t count) {
    for (size_t i = 0; i < count; i++)
        if (record_prefix(text, values[i]))
            return true;
    return false;
}
Err classify_user_part(Arena *arena, Str text, Str *kind, Str *accepted, bool *present) {
    static const char *const wrappers[] = {"# Files mentioned by the user",
                                           "# Files pasted by the user", "# Browser comments",
                                           "<in-app-browser-context"};
    static const char *const injected[] = {"# AGENTS.md",
                                           "<environment_context>",
                                           "<INSTRUCTIONS>",
                                           "<external_codex_apps_open_page>",
                                           "<permissions instructions>",
                                           "<recommended_plugins>",
                                           "<skills_instructions>",
                                           "<codex_apps_open_page_instructions>",
                                           "<realtime_delegation>",
                                           "<skill>",
                                           "<turn_aborted>"};
    text = record_trim(text, false);
    *present = false;
    *kind = STR_LIT("text");
    *accepted = (Str){0};
    if (matches(text, wrappers, sizeof wrappers / sizeof *wrappers)) {
        size_t at = 0, start = 0;
        bool found = false;
        JsonWriter body = {0};
        while (at < text.n) {
            size_t cpstart = at;
            uint32_t cp;
            if (!str_decode_next(text, &at, &cp))
                break;
            if (!str_linebreak_codepoint(cp))
                continue;
            Str line = record_trim((Str){text.p + start, (uint32_t)(cpstart - start)}, true);
            if (found) {
                jsonw_bytes(&body, text.p + start, cpstart - start);
                jsonw_raw(&body, "\n");
            } else
                found = str_equal(line, STR_LIT("## My request:")) ||
                        str_equal(line, STR_LIT("## My request for Codex:"));
            if (cp == '\r' && at < text.n && text.p[at] == '\n')
                at++;
            start = at;
        }
        if (found) {
            jsonw_bytes(&body, text.p + start, text.n - start);
            Str value = record_trim((Str){body.data, (uint32_t)body.length}, true);
            Err err = body.error.code ? body.error : str_copy(arena, value, accepted);
            jsonw_free(&body);
            *present = !err.code;
            return err;
        }
        /* A request heading may be the final line, with an empty body. */
        Str last = record_trim((Str){text.p + start, text.n - (uint32_t)start}, true);
        if (str_equal(last, STR_LIT("## My request:")) ||
            str_equal(last, STR_LIT("## My request for Codex:"))) {
            *present = true;
            *accepted = STR_LIT("");
        }
        jsonw_free(&body);
        return ERR_SUCCESS;
    }
    if (matches(text, injected, sizeof injected / sizeof *injected))
        return ERR_SUCCESS;
    const char *opening = "<send_user_message_question_reply>",
               *closing = "</send_user_message_question_reply>";
    if (record_prefix(text, opening)) {
        text.p += strlen(opening);
        text.n -= (uint32_t)strlen(opening);
        text = record_trim(text, true);
        size_t n = strlen(closing);
        if (text.n >= n && !memcmp(text.p + text.n - n, closing, n))
            text.n -= (uint32_t)n;
        *kind = STR_LIT("answer");
        *accepted = record_trim(text, true);
        *present = true;
        return ERR_SUCCESS;
    }
    if (record_prefix(text, "<image") || str_equal(record_trim(text, true), STR_LIT("</image>")))
        return ERR_SUCCESS;
    *accepted = record_trim(text, true);
    *present = true;
    return ERR_SUCCESS;
}
static Err add_text(LogRecord *record, MessageCandidate *out, JsonWriter *text, Str type,
                    yyjson_val *value) {
    bool user = str_equal(out->role, STR_LIT("user"));
    if (user && (str_equal(type, STR_LIT("local_image")) || str_equal(type, STR_LIT("image")) ||
                 str_equal(type, STR_LIT("input_image"))))
        out->images++;
    bool accepted =
        user ? (str_equal(type, STR_LIT("text")) || str_equal(type, STR_LIT("input_text")))
             : (str_equal(type, STR_LIT("Text")) || str_equal(type, STR_LIT("text")) ||
                str_equal(type, STR_LIT("output_text")));
    if (!accepted || !yyjson_is_str(value))
        return ERR_SUCCESS;
    Str part = record_string(value), kind;
    bool present = true;
    Err err = ERR_SUCCESS;
    if (user)
        err = classify_user_part(&record->arena, part, &kind, &part, &present);
    else
        part = record_trim(part, true);
    if (err.code)
        return err;
    if (present) {
        if (user && str_equal(kind, STR_LIT("answer")))
            out->kind = kind;
        if (part.n) {
            if (text->length)
                jsonw_raw(text, "\n\n");
            jsonw_bytes(text, part.p, part.n);
        }
    }
    return text->error;
}
Err message_candidate(LogRecord *record, yyjson_val *payload, Str kind, MessageCandidate *out,
                      bool *present) {
    *out = (MessageCandidate){0};
    *present = false;
    yyjson_val *content = payload;
    if (str_equal(kind, STR_LIT("event_msg/item_completed/UserMessage")) ||
        str_equal(kind, STR_LIT("event_msg/item_completed/AgentMessage"))) {
        content = record_get(payload, "item");
        out->role = str_equal(kind, STR_LIT("event_msg/item_completed/UserMessage"))
                        ? STR_LIT("user")
                        : STR_LIT("assistant");
        out->family = STR_LIT("item");
    } else if (str_equal(kind, STR_LIT("event_msg/user_message")) ||
               str_equal(kind, STR_LIT("event_msg/agent_message"))) {
        out->role = str_equal(kind, STR_LIT("event_msg/user_message")) ? STR_LIT("user")
                                                                       : STR_LIT("assistant");
        out->family = STR_LIT("event");
    } else if (str_equal(kind, STR_LIT("response_item/message"))) {
        out->role = record_string(record_get(payload, "role"));
        out->family = STR_LIT("response");
        if (!str_equal(out->role, STR_LIT("user")) && !str_equal(out->role, STR_LIT("assistant")))
            return ERR_SUCCESS;
    } else
        return ERR_SUCCESS;
    bool user = str_equal(out->role, STR_LIT("user"));
    out->role = user ? STR_LIT("user") : STR_LIT("assistant");
    out->kind = user ? STR_LIT("text") : STR_LIT("final");
    if (!user && !str_equal(record_string(record_get(content, "phase")), STR_LIT("final_answer")))
        return ERR_SUCCESS;
    JsonWriter text = {0};
    Err err = ERR_SUCCESS;
    yyjson_val *message = record_get(content, "message");
    if (str_equal(out->family, STR_LIT("event")) && yyjson_is_str(message))
        err = add_text(record, out, &text, STR_LIT("text"), message);
    else {
        yyjson_val *parts = record_get(content, "content");
        size_t index, max;
        yyjson_val *part;
        yyjson_arr_foreach(parts, index, max, part) {
            err = add_text(record, out, &text, record_string(record_get(part, "type")),
                           record_get(part, "text"));
            if (err.code)
                break;
        }
    }
    if (!err.code && (text.length || out->images)) {
        if (!text.length) {
            char image[80];
            int n = snprintf(image, sizeof image, "+ %llu images", (unsigned long long)out->images);
            jsonw_bytes(&text, image, (size_t)n);
        }
        err = text.error.code
                  ? text.error
                  : str_copy(&record->arena, (Str){text.data, (uint32_t)text.length}, &out->text);
        *present = !err.code;
    }
    jsonw_free(&text);
    return err;
}
/* AVL timestamp index: querying a ten-second window and retaining a copy are
 * logarithmic even for repeated identical text with nonmonotonic timestamps. */
typedef struct TimeNode {
    int64_t time;
    int height;
    struct TimeNode *left, *right;
} TimeNode;
typedef struct {
    TimeNode *root;
    bool unknown;
} Times;
static int height(TimeNode *node) {
    return node ? node->height : 0;
}
static void update(TimeNode *node) {
    int l = height(node->left), r = height(node->right);
    node->height = 1 + (l > r ? l : r);
}
static TimeNode *rotate_right(TimeNode *root) {
    TimeNode *left = root->left;
    root->left = left->right;
    left->right = root;
    update(root);
    update(left);
    return left;
}
static TimeNode *rotate_left(TimeNode *root) {
    TimeNode *right = root->right;
    root->right = right->left;
    right->left = root;
    update(root);
    update(right);
    return right;
}
static TimeNode *insert_time(TimeNode *root, TimeNode *node) {
    /* An AVL tree representing a size_t-counted allocation has height <128.
     * Explicit links allow bottom-up rotations without recursive walkers. */
    TimeNode **links[128], **link = &root;
    size_t count = 0;
    while (*link) {
        TimeNode *value = *link;
        if (value->time == node->time)
            return root;
        links[count++] = link;
        link = node->time < value->time ? &value->left : &value->right;
    }
    *link = node;
    while (count) {
        link = links[--count];
        TimeNode *value = *link;
        update(value);
        int balance = height(value->left) - height(value->right);
        if (balance > 1) {
            if (node->time > value->left->time)
                value->left = rotate_left(value->left);
            *link = rotate_right(value);
        } else if (balance < -1) {
            if (node->time < value->right->time)
                value->right = rotate_right(value->right);
            *link = rotate_left(value);
        }
    }
    return root;
}
static bool time_match(Times *times, MaybeMs ms) {
    if (!times)
        return false;
    if (!ms.present)
        return times->unknown;
    int64_t low, high;
    if (__builtin_sub_overflow(ms.value, INT64_C(10000), &low))
        low = INT64_MIN;
    if (__builtin_add_overflow(ms.value, INT64_C(10000), &high))
        high = INT64_MAX;
    TimeNode *node = times->root;
    while (node) {
        if (node->time < low)
            node = node->right;
        else if (node->time > high)
            node = node->left;
        else
            return true;
    }
    return false;
}
static Err index_key(unsigned char digest[20], Str role, int family, int bucket, Str turn,
                     Str *out) {
    size_t length = 23 + (bucket == 2 ? turn.n : 0);
    char *data = malloc(length);
    if (!data)
        return err_make(ERR_NOMEM, "message index allocation failed");
    memcpy(data, digest, 20);
    data[20] = str_equal(role, STR_LIT("user"));
    data[21] = (char)family;
    data[22] = (char)bucket;
    if (bucket == 2)
        memcpy(data + 23, turn.p, turn.n);
    *out = (Str){data, (uint32_t)length};
    return ERR_SUCCESS;
}
static int message_order(const void *a, const void *b, void *context) {
    (void)context;
    uint64_t x = ((const MessageFact *)a)->rec, y = ((const MessageFact *)b)->rec;
    return (x > y) - (x < y);
}
Err messages_build(LogRecord *record, RecordFact *facts, size_t count) {
    Omap item_turns = {0}, index = {0};
    Err err = ERR_SUCCESS;
    size_t capacity = 0;
    for (size_t i = 0; i < count; i++)
        if (!facts[i].inherited && facts[i].item_message && facts[i].turn_key.p) {
            err = omap_put(&item_turns, facts[i].turn_key, (void *)1);
            if (err.code)
                goto done;
        }
    const Str families[] = {STR_LIT("response"), STR_LIT("event"), STR_LIT("item")};
    for (int family = 2; family >= 0; family--)
        for (size_t i = 0; i < count; i++) {
            RecordFact *fact = &facts[i];
            MessageCandidate *message = &fact->message;
            if (fact->inherited || !fact->has_message ||
                !str_equal(message->family, families[family]))
                continue;
            if (!family && fact->turn_key.p && omap_get(&item_turns, fact->turn_key))
                continue;
            unsigned char digest[20];
            sha1_digest(message->text, digest);
            bool duplicate = false;
            for (int other = 0; other < 3 && !duplicate; other++)
                if (other != family) {
                    int buckets[2] = {fact->turn_id.p ? 2 : 0, 1};
                    size_t n = fact->turn_id.p ? 2 : 1;
                    for (size_t b = 0; b < n && !duplicate; b++) {
                        Str key;
                        err = index_key(digest, message->role, other, buckets[b], fact->turn_id,
                                        &key);
                        if (err.code)
                            goto done;
                        duplicate = time_match(omap_get(&index, key), fact->at_ms);
                        free((void *)key.p);
                    }
                }
            if (duplicate)
                continue;
            MessageFact kept = {message->role,  message->kind,   message->text, fact->ts_src,
                                fact->turn_key, message->images, fact->rec,     fact->at_ms};
            err = record_append(&record->arena, (void **)&record->messages, &record->message_count,
                                &capacity, sizeof kept, &kept);
            if (err.code)
                goto done;
            int buckets[2] = {0, fact->turn_id.p ? 2 : 1};
            for (size_t b = 0; b < 2; b++) {
                Str key;
                err = index_key(digest, message->role, family, buckets[b], fact->turn_id, &key);
                if (err.code)
                    goto done;
                Times *times = omap_get(&index, key);
                if (!times) {
                    err =
                        arena_alloc(&record->arena, sizeof *times, alignof(Times), (void **)&times);
                    if (!err.code) {
                        *times = (Times){0};
                        err = omap_put(&index, key, times);
                    }
                }
                free((void *)key.p);
                if (err.code)
                    goto done;
                if (!fact->at_ms.present)
                    times->unknown = true;
                else {
                    TimeNode *node;
                    err = arena_alloc(&record->arena, sizeof *node, alignof(TimeNode),
                                      (void **)&node);
                    if (err.code)
                        goto done;
                    *node = (TimeNode){.time = fact->at_ms.value, .height = 1};
                    times->root = insert_time(times->root, node);
                }
            }
        }
    err = stable_sort(record->messages, record->message_count, sizeof *record->messages,
                      message_order, NULL);
done:
    omap_destroy(&item_turns);
    omap_destroy(&index);
    return err;
}
bool select_final_answer(const LogRecord *record, Str key, Str *text, bool *voice) {
    for (size_t i = record->message_count; i > 0; i--) {
        const MessageFact *message = &record->messages[i - 1];
        if (str_equal(message->turn_key, key) && str_equal(message->kind, STR_LIT("final"))) {
            *text = message->text;
            *voice = false;
            return true;
        }
    }
    for (size_t i = record->request_count; i > 0; i--) {
        const VoiceRequest *request = &record->requests[i - 1];
        if (str_equal(request->turn_key, key) && !request->before_turn && request->reply.p) {
            *text = request->reply;
            *voice = true;
            return true;
        }
    }
    return false;
}
