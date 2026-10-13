#include "codec.h"
#include "parse/record.h"
#include <stdalign.h>
#include <stdlib.h>
#include <string.h>

/* A single traversal defines both sides of the format. Never serialize struct
 * padding, pointers, native size_t, or the borrowed Intern/Arena owners. */
typedef struct {
    unsigned char *data;
    size_t length, capacity, position;
    bool reading;
    LogRecord *record;
    Err error;
} Wire;
static void invalid(Wire *w) {
    if (!w->error.code)
        w->error = err_make(ERR_INVALID, "invalid native cache record");
}
static void bytes(Wire *w, void *value, size_t n) {
    if (w->error.code)
        return;
    if (w->reading) {
        if (n > w->length - w->position) {
            invalid(w);
            return;
        }
        if (n)
            memcpy(value, w->data + w->position, n);
        w->position += n;
    } else {
        if (n > SIZE_MAX - w->length) {
            invalid(w);
            return;
        }
        size_t need = w->length + n;
        if (need > w->capacity) {
            size_t cap = w->capacity ? w->capacity : 4096;
            while (cap < need) {
                if (cap > SIZE_MAX / 2) {
                    cap = need;
                    break;
                }
                cap *= 2;
            }
            void *p = realloc(w->data, cap);
            if (!p) {
                w->error = err_make(ERR_NOMEM, "cache wire allocation failed");
                return;
            }
            w->data = p;
            w->capacity = cap;
        }
        if (n)
            memcpy(w->data + w->length, value, n);
        w->length = need;
    }
}
static void integer(Wire *w, uint64_t *v, unsigned width) {
    unsigned char raw[8] = {0};
    if (!w->reading)
        for (unsigned i = 0; i < width; i++)
            raw[i] = (unsigned char)(*v >> (8 * i));
    bytes(w, raw, width);
    if (w->reading && !w->error.code) {
        *v = 0;
        for (unsigned i = 0; i < width; i++)
            *v |= (uint64_t)raw[i] << (8 * i);
    }
}
static void u64(Wire *w, uint64_t *v) {
    integer(w, v, 8);
}
static void i64(Wire *w, int64_t *v) {
    uint64_t bits;
    memcpy(&bits, v, 8);
    u64(w, &bits);
    if (w->reading)
        memcpy(v, &bits, 8);
}
static void real(Wire *w, double *v) {
    uint64_t bits;
    memcpy(&bits, v, 8);
    u64(w, &bits);
    if (w->reading)
        memcpy(v, &bits, 8);
}
static void boolean(Wire *w, bool *v) {
    uint64_t n = *v;
    integer(w, &n, 1);
    if (n > 1)
        invalid(w);
    if (w->reading)
        *v = n != 0;
}
static void enumeration(Wire *w, int *v, int max) {
    uint64_t n = (unsigned)*v;
    integer(w, &n, 1);
    if (n > (unsigned)max)
        invalid(w);
    if (w->reading)
        *v = (int)n;
}
static void size(Wire *w, size_t *v) {
    uint64_t n = *v;
    u64(w, &n);
    if (n > SIZE_MAX)
        invalid(w);
    if (w->reading)
        *v = (size_t)n;
}
static void string(Wire *w, Str *v, bool id) {
    bool present = v->p != NULL;
    boolean(w, &present);
    if (!present) {
        if (w->reading)
            *v = (Str){0};
        return;
    }
    uint64_t n = v->n;
    integer(w, &n, 4);
    if (w->reading) {
        if (w->error.code || n > w->length - w->position) {
            invalid(w);
            return;
        }
        Str value = {(const char *)w->data + w->position, (uint32_t)n};
        size_t points;
        if (str_codepoints(value, &points).code) {
            invalid(w);
            return;
        }
        Err e = id ? intern_get(w->record->identifiers, value, v)
                   : str_copy(&w->record->arena, value, v);
        if (e.code) {
            w->error = e;
            return;
        }
        w->position += (size_t)n;
    } else
        bytes(w, (void *)v->p, (size_t)n);
}
static void ms(Wire *w, MaybeMs *v) {
    boolean(w, &v->present);
    if (v->present)
        i64(w, &v->value);
}
static void num(Wire *w, MaybeNum *v) {
    boolean(w, &v->present);
    if (v->present) {
        boolean(w, &v->value.is_float);
        if (v->value.is_float)
            real(w, &v->value.f);
        else
            i64(w, &v->value.i);
    }
}
static void scalar(Wire *w, JScalar *v) {
    int kind = v->kind;
    enumeration(w, &kind, JS_OBJECT);
    if (w->reading)
        v->kind = (JKind)kind;
    boolean(w, &v->empty);
    switch (v->kind) {
    case JS_BOOL:
        boolean(w, &v->value.b);
        break;
    case JS_INT:
        i64(w, &v->value.i);
        break;
    case JS_FLOAT:
        real(w, &v->value.f);
        break;
    case JS_STRING:
        string(w, &v->value.s, false);
        if (!v->value.s.p)
            invalid(w);
        break;
    default:
        break;
    }
}
/* The minimum wire bytes prevents corrupt counts allocating unbounded storage.
 * Arena bytes additionally check multiplication overflow before allocation. */
static void array(Wire *w, void **data, size_t *count, size_t element, size_t minimum) {
    size(w, count);
    if (!w->reading || w->error.code)
        return;
    if (*count > (w->length - w->position) / minimum || *count > SIZE_MAX / element) {
        invalid(w);
        return;
    }
    if (!*count)
        return;
    w->error = arena_alloc(&w->record->arena, *count * element, alignof(max_align_t), data);
    if (!w->error.code)
        memset(*data, 0, *count * element);
}
static void count_map(Wire *w, Omap *map, bool heap) {
    size_t count = map->size;
    size(w, &count);
    if (w->reading && count > (w->length - w->position) / 9)
        invalid(w);
    if (w->reading) {
        for (size_t i = 0; i < count && !w->error.code; i++) {
            Str key = {0};
            uint64_t n = 0;
            string(w, &key, false);
            u64(w, &n);
            if (w->error.code)
                break;
            if (!key.p || omap_get(map, key)) {
                invalid(w);
                break;
            }
            uint64_t *value = NULL;
            if (heap) {
                value = malloc(sizeof *value);
                if (!value)
                    w->error = err_make(ERR_NOMEM, "cache count allocation failed");
            } else
                w->error = arena_alloc(&w->record->arena, sizeof *value, alignof(uint64_t),
                                       (void **)&value);
            if (w->error.code)
                break;
            *value = n;
            w->error = omap_put(map, key, value);
            if (w->error.code && heap)
                free(value);
        }
    } else
        for (OmapEntry *e = map->first; e && !w->error.code; e = e->next) {
            Str key = e->key;
            string(w, &key, false);
            u64(w, e->value);
        }
}
static void tools(Wire *w, ToolCounts *v) {
    u64(w, &v->shell);
    u64(w, &v->shell_failed);
    u64(w, &v->file_edits);
    u64(w, &v->web);
    u64(w, &v->image);
    count_map(w, &v->mcp, false);
    count_map(w, &v->other, false);
}
static void token_integer(Wire *w, TokenInteger *v) {
    boolean(w, &v->present);
    if (v->present)
        i64(w, &v->value);
}
static void totals(Wire *w, TokenTotals *v) {
    boolean(w, &v->present);
    boolean(w, &v->has_reasoning);
    i64(w, &v->input);
    i64(w, &v->cached);
    i64(w, &v->output);
    i64(w, &v->reasoning);
}
static void token_meta(Wire *w, TokenMeta *v) {
    string(w, &v->session_id, true);
    string(w, &v->forked_from_id, true);
    string(w, &v->fork_ts, false);
    string(w, &v->project_path, true);
    string(w, &v->history_base_thread_id, true);
    boolean(w, &v->is_subagent);
    token_integer(w, &v->history_start_ordinal);
}
#define S(v) string(w, &(v), false)
#define ID(v) string(w, &(v), true)
#define U(v) u64(w, &(v))
#define B(v) boolean(w, &(v))
#define MS(v) ms(w, &(v))
#define NUM(v) num(w, &(v))
#define RAW(v) scalar(w, &(v))
#define ARRAY(field, count, type, min) array(w, (void **)&r->field, &r->count, sizeof(type), min)
static void record(Wire *w, LogRecord *r) {
    ID(r->key.path);
    i64(w, &r->key.size);
    i64(w, &r->key.mtime_ns);
    bytes(w, r->reader.tail_sha256, 64);
    if (w->reading)
        r->reader.tail_sha256[64] = 0;
    B(r->key.archived);
    B(r->key.stat_ok);
    uint64_t device = r->key.device, inode = r->key.inode;
    U(device);
    U(inode);
    if (w->reading) {
        r->key.device = (dev_t)device;
        r->key.inode = (ino_t)inode;
    }
    U(r->reader.malformed);
    U(r->reader.recovered);
    U(r->reader.physical_lines);
    U(r->reader.decoded_records);
    B(r->reader.partial_final_line);
    count_map(w, &r->reader.unknown_types, true);
    S(r->status);
    B(r->has_meta);
    ID(r->meta.id);
    ID(r->meta.request_session_id);
    ID(r->meta.forked_from_id);
    MS(r->meta.created_at_ms);
    B(r->meta.is_subagent);
    RAW(r->meta.timestamp_raw);
    RAW(r->meta.cwd);
    RAW(r->meta.originator);
    RAW(r->meta.cli_version);
    RAW(r->meta.parent_thread_id);
    RAW(r->meta.depth);
    RAW(r->meta.agent_path);
    RAW(r->meta.agent_nickname);
    RAW(r->meta.agent_role);
    RAW(r->meta.branch);
    RAW(r->meta.origin_url);
    RAW(r->meta.sha);
    RAW(r->meta.rollout_title);
    U(r->extra_meta_count);
    U(r->wrapper_count);
    size(w, &r->wrapper_distinct);
    ID(r->history.path);
    S(r->history.method);
    B(r->history.has_boundary);
    U(r->history.boundary_rec);
    ARRAY(history.inherited_recs, history.rec_count, RecordRange, 16);
    for (size_t i = 0; i < r->history.rec_count && !w->error.code; i++) {
        U(r->history.inherited_recs[i].start);
        U(r->history.inherited_recs[i].end);
    }
    ARRAY(history.inherited_lines, history.line_count, RecordRange, 16);
    for (size_t i = 0; i < r->history.line_count && !w->error.code; i++) {
        U(r->history.inherited_lines[i].start);
        U(r->history.inherited_lines[i].end);
    }
    MS(r->first_ms);
    MS(r->last_ms);
    ARRAY(turns, turn_count, TurnFact *, 11);
    for (size_t i = 0; i < r->turn_count && !w->error.code; i++) {
        if (w->reading) {
            w->error =
                arena_alloc(&r->arena, sizeof(TurnFact), alignof(TurnFact), (void **)&r->turns[i]);
            if (w->error.code)
                break;
            memset(r->turns[i], 0, sizeof(TurnFact));
        }
        TurnFact *v = r->turns[i];
        ID(v->key);
        ID(v->turn_id);
        S(v->start_src);
        S(v->end_src);
        S(v->end_kind);
        MS(v->start_ms);
        MS(v->end_ms);
        MS(v->last_ms);
        NUM(v->reported_ms);
        NUM(v->ttft_ms);
        B(v->has_start_rec);
        U(v->start_rec);
    }
    ARRAY(messages, message_count, MessageFact, 22);
    for (size_t i = 0; i < r->message_count && !w->error.code; i++) {
        MessageFact *v = &r->messages[i];
        S(v->role);
        S(v->kind);
        S(v->text);
        S(v->ts_src);
        ID(v->turn_key);
        U(v->images);
        U(v->rec);
        MS(v->at_ms);
    }
    ARRAY(requests, request_count, VoiceRequest, 6);
    for (size_t i = 0; i < r->request_count && !w->error.code; i++) {
        VoiceRequest *v = &r->requests[i];
        S(v->text);
        ID(v->turn_key);
        S(v->reply);
        MS(v->at_ms);
        B(v->before_turn);
        B(v->follow_up);
    }
    ARRAY(replies, reply_count, VoiceReply, 3);
    for (size_t i = 0; i < r->reply_count && !w->error.code; i++) {
        VoiceReply *v = &r->replies[i];
        S(v->text);
        ID(v->turn_key);
        MS(v->at_ms);
    }
    size_t count = r->tools.size;
    size(w, &count);
    if (w->reading && count > (w->length - w->position) / 115)
        invalid(w);
    OmapEntry *entry = r->tools.first;
    for (size_t i = 0; i < count && !w->error.code; i++) {
        Str key = w->reading ? (Str){0} : entry->key;
        ID(key);
        ToolTally *v = NULL;
        if (w->reading) {
            if (!key.p || omap_get(&r->tools, key)) {
                invalid(w);
                break;
            }
            w->error = arena_alloc(&r->arena, sizeof *v, alignof(ToolTally), (void **)&v);
            if (w->error.code)
                break;
            memset(v, 0, sizeof *v);
            w->error = omap_put(&r->tools, key, v);
            if (w->error.code)
                break;
        } else
            v = entry->value;
        tools(w, &v->structured);
        tools(w, &v->raw);
        B(v->has_structured);
        if (!w->reading)
            entry = entry->next;
    }
    ARRAY(activities, activity_count, ActivityLink, 4);
    for (size_t i = 0; i < r->activity_count && !w->error.code; i++) {
        ActivityLink *v = &r->activities[i];
        S(v->kind);
        ID(v->child_id);
        ID(v->agent_path);
        ID(v->turn_key);
    }
    ARRAY(spawns, spawn_count, SpawnLink, 3);
    for (size_t i = 0; i < r->spawn_count && !w->error.code; i++) {
        SpawnLink *v = &r->spawns[i];
        ID(v->task_name);
        ID(v->turn_key);
        MS(v->at_ms);
    }
    ARRAY(targets, target_count, TargetLink, 2);
    for (size_t i = 0; i < r->target_count && !w->error.code; i++) {
        TargetLink *v = &r->targets[i];
        ID(v->target);
        ID(v->turn_key);
    }
    ARRAY(receivers, receiver_count, ReceiverLink, 2);
    for (size_t i = 0; i < r->receiver_count && !w->error.code; i++) {
        ReceiverLink *v = &r->receivers[i];
        ID(v->child_id);
        ID(v->turn_key);
    }
    ARRAY(usage_records, usage_count, UsageRecord, 40);
    for (size_t i = 0; i < r->usage_count && !w->error.code; i++) {
        UsageRecord *v = &r->usage_records[i];
        U(v->line);
        U(v->rec);
        RAW(v->response_id);
        RAW(v->thread_id);
        RAW(v->session_id);
        RAW(v->turn_id);
        RAW(v->root_turn_id);
        RAW(v->ts);
        MS(v->at_ms);
        MS(v->timestamp_unix_ms);
        RAW(v->input);
        RAW(v->cached_input);
        RAW(v->cache_read_input);
        RAW(v->cache_write);
        RAW(v->output);
        RAW(v->reasoning);
        RAW(v->thread_usage.input);
        RAW(v->thread_usage.cached_input);
        RAW(v->thread_usage.output);
        RAW(v->thread_usage.reasoning);
        RAW(v->turn_usage.input);
        RAW(v->turn_usage.cached_input);
        RAW(v->turn_usage.output);
        RAW(v->turn_usage.reasoning);
    }
    TokenStream *t = &r->token_stream;
    B(t->has_prepass);
    B(t->unconsumed_tail);
    token_meta(w, &t->prepass);
    U(t->uidx);
    array(w, (void **)&t->observations, &t->count, sizeof(TokenObservation), 99);
    for (size_t i = 0; i < t->count && !w->error.code; i++) {
        TokenObservation *v = &t->observations[i];
        int tag = v->tag;
        enumeration(w, &tag, TOKEN_XC);
        if (w->reading)
            v->tag = (TokenTag)tag;
        U(v->line);
        U(v->uidx);
        token_integer(w, &v->ordinal);
        token_meta(w, &v->meta);
        S(v->timestamp);
        ID(v->model);
        ID(v->turn_id);
        int kind = v->model_state.kind;
        enumeration(w, &kind, MODEL_CLEAR);
        if (w->reading)
            v->model_state.kind = kind;
        ID(v->model_state.model);
        B(v->trigger);
        totals(w, &v->last);
        totals(w, &v->total);
    }
    if (w->reading) {
        t->capacity = t->count;
        t->arena = &r->arena;
        t->identifiers = r->identifiers;
    }
}
static uint32_t crc_table[8][256];
static pthread_once_t crc_once = PTHREAD_ONCE_INIT;
static void crc_tables(void) {
    for (unsigned i = 0; i < 256; i++) {
        uint32_t value = i;
        for (unsigned b = 0; b < 8; b++)
            value = (value >> 1) ^ (0xedb88320u & (0u - (value & 1)));
        crc_table[0][i] = value;
    }
    for (unsigned k = 1; k < 8; k++)
        for (unsigned i = 0; i < 256; i++) {
            uint32_t value = crc_table[k - 1][i];
            crc_table[k][i] = (value >> 8) ^ crc_table[0][value & 255];
        }
}
static uint32_t crc32(const unsigned char *p, size_t n) {
    pthread_once(&crc_once, crc_tables);
    uint32_t crc = UINT32_MAX;
    while (n >= 8) {
        crc ^= (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
        crc = crc_table[7][crc & 255] ^ crc_table[6][(crc >> 8) & 255] ^
              crc_table[5][(crc >> 16) & 255] ^ crc_table[4][crc >> 24] ^ crc_table[3][p[4]] ^
              crc_table[2][p[5]] ^ crc_table[1][p[6]] ^ crc_table[0][p[7]];
        p += 8;
        n -= 8;
    }
    while (n--) {
        crc = (crc >> 8) ^ crc_table[0][(crc ^ *p++) & 255];
    }
    return ~crc;
}
Err codec_encode(const LogRecord *r, unsigned char **out, size_t *length) {
    *out = NULL;
    *length = 0;
    Wire w = {.record = (LogRecord *)r};
    unsigned char header[12] = {'C', 'L', 'P', 'N', 1, 0, 0, 0, 4, 3, 2, 1};
    bytes(&w, header, sizeof header);
    record(&w, (LogRecord *)r);
    if (!w.error.code) {
        uint64_t crc = crc32(w.data + 12, w.length - 12);
        integer(&w, &crc, 4);
    }
    if (w.error.code) {
        free(w.data);
        return w.error;
    }
    *out = w.data;
    *length = w.length;
    return ERR_SUCCESS;
}
Err codec_decode(const void *data, size_t length, const DiscoveredLog *key, const char tail[65],
                 Intern *ids, LogRecord *out) {
    *out = (LogRecord){.identifiers = ids};
    const unsigned char header[12] = {'C', 'L', 'P', 'N', 1, 0, 0, 0, 4, 3, 2, 1};
    if (length < 16 || memcmp(data, header, 12))
        return err_make(ERR_INVALID, "invalid native cache header");
    Wire w = {.data = (unsigned char *)data,
              .length = length,
              .position = length - 4,
              .reading = true,
              .record = out};
    uint64_t expected = 0;
    integer(&w, &expected, 4);
    if (expected != crc32((const unsigned char *)data + 12, length - 16))
        return err_make(ERR_INVALID, "invalid native cache checksum");
    w.length = length - 4;
    w.position = 12;
    record(&w, out);
    if (!w.error.code && (w.position != w.length || !str_equal(out->key.path, key->path) ||
                          out->key.size != key->size || out->key.mtime_ns != key->mtime_ns ||
                          (tail && memcmp(out->reader.tail_sha256, tail, 65))))
        invalid(&w);
    if (w.error.code) {
        Err e = w.error;
        record_destroy(out);
        return e;
    }
    return ERR_SUCCESS;
}
