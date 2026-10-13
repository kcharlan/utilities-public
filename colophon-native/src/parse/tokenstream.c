#define _DARWIN_C_SOURCE
#include "tokenstream.h"
#include "record.h"
#include "util/events.h"
#include "util/fileio.h"
#include "util/json_number.h"
#ifdef COLOPHON_TESTING
#include "out/jsonw.h"
#endif
#include <math.h>
#include <stdlib.h>
#include <string.h>

static bool ascii_space(unsigned char c) { return c == ' ' || c == '\t' || c == '\n' || c == '\r'; }
bool token_tail_complete(Str bytes) {
    enum { CONTAINER, LITERAL, NUMBER, INVALID } kind = CONTAINER;
    enum { SIGN, ZERO, INTEGER, POINT, FRACTION, EXP, EXP_SIGN, EXP_DIGITS, FINISHED, BAD } number = SIGN;
    size_t depth = 0, matched = 0;
    const char *literal = NULL;
    bool saw = false, quoted = false, escaped = false;
    for (size_t i = 0; i < bytes.n; i++) {
        unsigned char c = (unsigned char)bytes.p[i];
        if (!saw) {
            if (ascii_space(c)) continue;
            saw = true;
            if (c == '"') quoted = true;
            else if (c == '{' || c == '[') depth = 1;
            else if (c == 't' || c == 'f' || c == 'n') {
                kind = LITERAL; literal = c == 't' ? "true" : c == 'f' ? "false" : "null"; matched = 1;
            } else if (c == '-' || (c >= '0' && c <= '9')) {
                kind = NUMBER; number = c == '-' ? SIGN : c == '0' ? ZERO : INTEGER;
            } else kind = INVALID;
            continue;
        }
        if (kind == INVALID) continue;
        if (kind == LITERAL) {
            if (literal[matched]) { if (c == literal[matched]) matched++; else kind = INVALID; }
            else if (!ascii_space(c)) kind = INVALID;
            continue;
        }
        if (kind == NUMBER) {
            bool digit = c >= '0' && c <= '9', space = ascii_space(c);
            switch (number) {
            case SIGN: number = c == '0' ? ZERO : digit ? INTEGER : BAD; break;
            case ZERO: case INTEGER:
                if (number == INTEGER && digit) break;
                number = c == '.' ? POINT : c == 'e' || c == 'E' ? EXP : space ? FINISHED : BAD; break;
            case POINT: number = digit ? FRACTION : BAD; break;
            case FRACTION: number = digit ? FRACTION : c == 'e' || c == 'E' ? EXP : space ? FINISHED : BAD; break;
            case EXP: number = c == '+' || c == '-' ? EXP_SIGN : digit ? EXP_DIGITS : BAD; break;
            case EXP_SIGN: number = digit ? EXP_DIGITS : BAD; break;
            case EXP_DIGITS: number = digit ? EXP_DIGITS : space ? FINISHED : BAD; break;
            case FINISHED: number = space ? FINISHED : BAD; break;
            case BAD: break;
            }
            continue;
        }
        if (quoted) {
            if (escaped) escaped = false;
            else if (c == '\\') escaped = true;
            else if (c == '"') quoted = false;
        } else if (c == '"') quoted = true;
        else if (c == '{' || c == '[') depth++;
        else if ((c == '}' || c == ']') && depth) depth--;
    }
    return saw && (kind == INVALID || (kind == NUMBER ? number == FINISHED || number == BAD :
        kind == LITERAL ? !literal[matched] : !quoted && !depth));
}

bool token_foundation_space(uint32_t cp) {
    return (cp >= 9 && cp <= 13) || cp == 32 || cp == 0x85 || cp == 0xa0 || cp == 0x1680 ||
        (cp >= 0x2000 && cp <= 0x200b) || cp == 0x2028 || cp == 0x2029 || cp == 0x202f ||
        cp == 0x205f || cp == 0x3000;
}
Str token_model_trim(Str value) {
    size_t offset = 0, first = value.n, last = value.n;
    uint32_t cp;
    while (offset < value.n) {
        size_t start = offset;
        if (!str_decode_next(value, &offset, &cp)) break;
        if (!token_foundation_space(cp)) { if (first == value.n) first = start; last = offset; }
    }
    return (Str){value.p ? value.p + first : NULL, (uint32_t)(last - first)};
}
static bool timestamp_valid(Str s) {
    if (s.n < 20 || s.p[4] != '-' || s.p[7] != '-') return false;
    const unsigned positions[] = {0,1,2,3,5,6,8,9};
    for (size_t i = 0; i < sizeof positions / sizeof *positions; i++)
        if (s.p[positions[i]] < '0' || s.p[positions[i]] > '9') return false;
    if (s.p[10] == 'T') {
        if (s.p[13] != ':' || s.p[16] != ':') return false;
        const unsigned clock[] = {11,12,14,15,17,18};
        for (size_t i = 0; i < sizeof clock / sizeof *clock; i++)
            if (s.p[clock[i]] < '0' || s.p[clock[i]] > '9') return false;
    }
    for (size_t i = s.n; i-- > 11;) {
        if (s.p[i] == 'Z') return true;
        if (s.p[i] == '+' || s.p[i] == '-') {
            if (i + 2 >= s.n || s.p[i+1] < '0' || s.p[i+1] > '9' || s.p[i+2] < '0' || s.p[i+2] > '9') return false;
            if (i + 3 < s.n && s.p[i+3] == ':' && (i + 5 >= s.n || s.p[i+4] < '0' || s.p[i+4] > '9' || s.p[i+5] < '0' || s.p[i+5] > '9')) return false;
            return true;
        }
    }
    return false; /* Historical ICU formatter is the explicit N4 DROP. */
}
static yyjson_val *typed(yyjson_val *obj, const char *key, yyjson_type type) {
    return obj_get_first_typed(obj, (Str){key, (uint32_t)strlen(key)}, type);
}
static yyjson_val *object(yyjson_val *obj, const char *key) { return typed(obj, key, YYJSON_TYPE_OBJ); }
static Str string(yyjson_val *obj, const char *key, bool empty) {
    yyjson_val *k;
    yyjson_obj_iter it = yyjson_obj_iter_with(obj);
    while ((k = yyjson_obj_iter_next(&it))) {
        yyjson_val *v = yyjson_obj_iter_get_val(k);
        if (str_equal(record_string(k), (Str){key, (uint32_t)strlen(key)}) && yyjson_is_str(v) &&
            (empty || yyjson_get_len(v))) return record_string(v);
    }
    return (Str){0};
}
static Err retain(TokenStream *s, Str value, Str *out) {
    if (!value.p) { *out = value; return ERR_SUCCESS; }
    return intern_get(s->identifiers, value, out);
}
static TokenInteger integer_value(yyjson_val *v, bool component, bool *clamped) {
    PyNum number;
    if (!json_number(v, component ? "tokenstream.tokens" : "tokenstream.ordinal", &number))
        return (TokenInteger){.present = component && v != NULL};
    TokenInteger out = {.present = true};
    if (!number.is_float) out.value = number.i;
    else if (!isfinite(number.f) || number.f >= 0x1p63 || number.f < -0x1p63) {
        event_note("tier2_int", component ? "tokenstream.tokens" : "tokenstream.ordinal", 1);
        out.present = component;
        return out;
    } else out.value = (int64_t)number.f;
    if (component && (number.is_float || out.value < 0)) {
        event_note("token_value_clamped", "tokenstream.tokens", 1);
        if (clamped) *clamped = true;
    }
    if (component && out.value < 0) out.value = 0;
    return out;
}
static TokenInteger integer_once(yyjson_val *obj, const char *key, bool component, bool *clamped) {
    return integer_value(typed(obj,key,YYJSON_TYPE_RAW),component,clamped);
}
static TokenInteger integer(yyjson_val *obj, const char *key, bool component) {
    return integer_once(obj,key,component,NULL);
}
static TokenTotals totals(yyjson_val *obj) {
    if (!obj) return (TokenTotals){0};
    TokenTotals t = {.present = true};
    t.input = integer(obj, "input_tokens", true).value;
    int64_t cached = integer(obj, "cached_input_tokens", true).value,
            read = integer(obj, "cache_read_input_tokens", true).value;
    t.cached = cached > read ? cached : read;
    t.output = integer(obj, "output_tokens", true).value;
    bool reasoning_noted = false;
    TokenInteger reasoning = integer_once(obj, "reasoning_output_tokens", true, &reasoning_noted);
    t.has_reasoning = reasoning.present;
    t.reasoning = reasoning.value > t.output ? t.output : reasoning.value;
    if (reasoning.present && reasoning.value > t.output && !reasoning_noted) event_note("token_value_clamped", "tokenstream.tokens", 1);
    return t;
}
static Err model_state(TokenStream *s, Str values[4], TokenModel *model) {
    for (size_t i = 0; i < 4; i++) if (values[i].p) {
        Str value = token_model_trim(values[i]);
        model->kind = MODEL_CLEAR;
        if (value.n) { model->kind = MODEL_SET; return retain(s, value, &model->model); }
    }
    return ERR_SUCCESS;
}
static Str dom_string(void *obj, const char *key, bool empty) { return string(obj,key,empty); }
static void *dom_object(void *obj, const char *key) { return object(obj,key); }
static TokenInteger dom_integer(void *obj, const char *key, bool component) { return integer(obj,key,component); }
static Err metadata_project(TokenStream *s, void *root, void *payload, TokenMeta *meta,
    Str (*string)(void *,const char *,bool), void *(*object)(void *,const char *),
    TokenInteger (*integer)(void *,const char *,bool)) {
    Str ids[] = {string(payload,"id",false),string(root,"id",false),string(payload,"session_id",false),
        string(payload,"sessionId",false),string(root,"session_id",false),string(root,"sessionId",false)};
    Err err = ERR_SUCCESS;
    for (size_t i = 0; i < 6; i++) if (ids[i].p) { err = retain(s, ids[i], &meta->session_id); break; }
    if (err.code) return err;
    const char *parents[] = {"forked_from_id","forkedFromId","parent_session_id","parentSessionId"};
    for (size_t i = 0; i < 4; i++) {
        Str value = token_model_trim(string(payload,parents[i],false));
        if (value.n) { err = retain(s,value,&meta->forked_from_id); break; }
    }
    if (err.code) return err;
    Str ts = string(payload,"timestamp",false);
    if (!ts.p) ts = string(root,"timestamp",false);
    err = retain(s,ts,&meta->fork_ts);
    if (err.code) return err;
    void *history = object(payload,"history_base");
    if (!history) history = object(payload,"historyBase");
    const char *history_ids[] = {"thread_id","threadId"};
    for (size_t i = 0; i < 2; i++) {
        Str value = token_model_trim(string(history,history_ids[i],false));
        if (value.n) { err = retain(s,value,&meta->history_base_thread_id); break; }
    }
    if (err.code) return err;
    meta->history_start_ordinal = integer(payload,"subagent_history_start_ordinal",false);
    Str source = string(payload,"source",false);
    if (source.p) {
        Str lower;
        err = str_lower(s->arena,token_model_trim(source),&lower);
        if (err.code) return err;
        meta->is_subagent = str_equal(lower,STR_LIT("subagent"));
    } else {
        void *source_obj = object(payload,"source");
        meta->is_subagent = string(source_obj,"subagent",false).p || object(source_obj,"subagent");
    }
    Str cwd = token_model_trim(string(payload,"cwd",false));
    if (cwd.n) {
        Str expanded = {0}, normalized = {0};
        err = file_expand_user(cwd,true,&expanded);
        if (!err.code && expanded.n && expanded.p[0] == '/') {
            Str start = expanded;
            while (start.n > 1 && start.p[0] == '/' && start.p[1] == '/') { start.p++; start.n--; }
            err = file_lexical_path(start,true,&normalized);
            if (!err.code) err = retain(s,normalized,&meta->project_path);
        }
        free((void *)expanded.p); free((void *)normalized.p);
    }
    return err;
}
static Err append(TokenStream *s, TokenObservation observation) {
    return record_append(s->arena,(void **)&s->observations,&s->count,&s->capacity,sizeof observation,&observation);
}

/* Prefix strings remove a backslash literally, matching TruncatedPrefix.swift.
 * Scanning names never allocates; only selected complete values are copied. */
static bool prefix_string(Str text, size_t *offset, Str *raw) {
    size_t i = *offset;
    if (i >= text.n || text.p[i] != '"') return false;
    size_t start = ++i;
    bool escaped = false;
    for (; i < text.n; i++) {
        if (escaped) escaped = false;
        else if (text.p[i] == '\\') escaped = true;
        else if (text.p[i] == '"') { *raw = (Str){text.p+start,(uint32_t)(i-start)}; *offset = i+1; return true; }
    }
    return false;
}
static void prefix_space(Str text, size_t *offset) {
    size_t next = *offset;
    uint32_t cp;
    while (str_decode_next(text,&next,&cp)) {
        if (!token_foundation_space(cp) || cp == 0x200b) break;
        *offset = next;
    }
}
static bool prefix_name(Str raw, const char *key) {
    size_t j = 0;
    for (size_t i = 0; i < raw.n; i++) {
        if (raw.p[i] == '\\') { if (++i == raw.n) return false; }
        if (!key[j] || key[j++] != raw.p[i]) return false;
    }
    return !key[j];
}
static Str prefix_field(Str text, const char *key, int field_kind, bool empty) {
    int depth = 0;
    size_t i = 0;
    while (i < text.n) {
        char c = text.p[i];
        if (c == '{') { depth++; i++; }
        else if (c == '}') { depth--; i++; }
        else if (c == '"') {
            Str name;
            if (!prefix_string(text,&i,&name)) break;
            if (depth != 1 || !prefix_name(name,key)) continue;
            prefix_space(text,&i);
            if (i == text.n || text.p[i] != ':') continue;
            i++; prefix_space(text,&i);
            if (field_kind == 1) {
                if (i < text.n && text.p[i] == '{') return (Str){text.p+i,text.n-(uint32_t)i};
            } else if (field_kind == 2) {
                if (i == text.n || (text.p[i] != '-' && (text.p[i] < '0' || text.p[i] > '9'))) continue;
                size_t start = i;
                while (i < text.n && !ascii_space((unsigned char)text.p[i]) &&
                       text.p[i] != ',' && text.p[i] != '}' && text.p[i] != ']') i++;
                Str value = {text.p+start,(uint32_t)(i-start)};
                if (value.n && i < text.n) return value;
            } else {
                Str value;
                if (prefix_string(text,&i,&value) && (empty || value.n)) return value;
            }
        } else i++;
    }
    return (Str){0};
}
typedef struct PrefixDecoded PrefixDecoded;
struct PrefixDecoded { Str raw, value; PrefixDecoded *next; };
typedef struct PrefixObject PrefixObject;
struct PrefixObject { TokenStream *stream; Str text; Err *error; PrefixDecoded **decoded; PrefixObject **objects, *next; };
static Err prefix_value(TokenStream *s, Str text, const char *key, bool empty, Str *out);
static Str prefix_get_string(void *context, const char *key, bool empty) {
    PrefixObject *object = context;
    Str value = {0};
    if (!object || object->error->code) return value;
    Str raw = prefix_field(object->text,key,0,empty);
    if (!raw.p) return value;
    for (PrefixDecoded *entry = *object->decoded; entry; entry = entry->next)
        if (entry->raw.p == raw.p && entry->raw.n == raw.n) return entry->value;
    /* Original JSON_INVALID emitted no successful-decode events. Each selected
     * scalar range owns its conversion once; only arena copies survive here. */
    JsonRead read = json_read((Str){raw.p-1,raw.n+2},BYTES,JSON_CONSTANTS_ALLOW,"log.line");
    yyjson_val *root = read.doc ? yyjson_doc_get_root(read.doc) : NULL;
    PrefixDecoded *entry = NULL;
    entry = malloc(sizeof *entry);
    if (!entry) *object->error = err_make(ERR_NOMEM,"token prefix scalar");
    if (!object->error->code) {
        *entry = (PrefixDecoded){.raw = raw,.next = *object->decoded};
        *object->decoded = entry;
        if (yyjson_is_str(root)) *object->error = retain(object->stream,record_string(root),&entry->value);
        value = entry->value;
    }
    if (read.status == JSON_NOMEM) *object->error = err_make(ERR_NOMEM,"token prefix JSON string");
    json_read_free(&read);
    return value;
}
static void *prefix_get_object(void *context, const char *key) {
    PrefixObject *object = context, *child = NULL;
    if (!object || object->error->code) return NULL;
    Str text = prefix_field(object->text,key,1,false);
    if (!text.p) return NULL;
    child = malloc(sizeof *child);
    if (!child) *object->error = err_make(ERR_NOMEM,"token prefix object");
    if (!object->error->code) {
        *child = (PrefixObject){object->stream,text,object->error,object->decoded,object->objects,*object->objects};
        *object->objects = child;
    }
    return child;
}
static TokenInteger prefix_get_integer(void *context, const char *key, bool component) {
    PrefixObject *object = context;
    if (!object) return (TokenInteger){0};
    Str raw = prefix_field(object->text,key,2,false);
    if (!raw.p) return (TokenInteger){0};
    JsonRead read = json_read(raw,BYTES,JSON_CONSTANTS_ALLOW,"log.line");
    yyjson_val *root = read.doc ? yyjson_doc_get_root(read.doc) : NULL;
    TokenInteger value = integer_value(root,component,NULL);
    if (read.status == JSON_NOMEM) *object->error = err_make(ERR_NOMEM,"token prefix JSON number");
    json_read_free(&read);
    return value;
}
static Err incomplete_prepass(TokenStream *s, const ReaderRawLine *line, const JsonRead *json) {
    if (s->has_prepass || json->status != JSON_INVALID) return ERR_SUCCESS;
    Str bytes = line->bytes;
    size_t i = 0;
    while (i < bytes.n && ascii_space((unsigned char)bytes.p[i])) i++;
    if (i == bytes.n || bytes.p[i] != '{') return ERR_SUCCESS;
    JsonStats stats = {0};
    if (wtf8_validate(bytes,BYTES,&stats) != JSON_OK) return ERR_SUCCESS;
    Err err = ERR_SUCCESS;
    PrefixDecoded *decoded = NULL;
    PrefixObject *objects = NULL;
    PrefixObject root = {s,{bytes.p+i,bytes.n-(uint32_t)i},&err,&decoded,&objects,NULL};
    Str kind = prefix_get_string(&root,"type",false);
    if (!err.code && str_equal(kind,STR_LIT("session_meta"))) {
        void *payload = prefix_get_object(&root,"payload");
        TokenMeta meta = {0};
        Err projection = metadata_project(s,&root,payload,&meta,prefix_get_string,prefix_get_object,prefix_get_integer);
        if (projection.code) err = projection;
        if (!err.code) {
            s->prepass = meta; s->has_prepass = true;
            event_note("token_prepass_prefix","tokenstream",1);
        }
    }
    while (decoded) { PrefixDecoded *next = decoded->next; free(decoded); decoded = next; }
    while (objects) { PrefixObject *next = objects->next; free(objects); objects = next; }
    return err;
}
#ifdef COLOPHON_TESTING
/* Directly exercise callback-local repeated lookup without expanding the
 * production command surface or making production consume extra fields. */
Err tokenstream_prefix_probe(TokenStream *s, Str bytes, JsonWriter *out) {
    Err err = ERR_SUCCESS;
    PrefixDecoded *decoded = NULL;
    PrefixObject *objects = NULL;
    PrefixObject root = {s,bytes,&err,&decoded,&objects,NULL};
    jsonw_raw(out,"[");
    for (size_t i = 0; i < 6 && !err.code; i++) {
        if (i) jsonw_raw(out,",");
        Str value = prefix_get_string(&root,i < 3 ? "id" : "session_id",false);
        if (value.p) jsonw_string(out,value); else jsonw_raw(out,"null");
    }
    jsonw_raw(out,"]\n");
    while (decoded) { PrefixDecoded *next = decoded->next; free(decoded); decoded = next; }
    while (objects) { PrefixObject *next = objects->next; free(objects); objects = next; }
    return err;
}
#endif
static Err prefix_value(TokenStream *s, Str text, const char *key, bool empty, Str *out) {
    Str raw = prefix_field(text,key,false,empty);
    *out = raw;
    if (!raw.p) return ERR_SUCCESS;
    char *buffer;
    Err err = arena_alloc(s->arena,raw.n+1,1,(void **)&buffer);
    if (err.code) return err;
    size_t n = 0;
    for (size_t i = 0; i < raw.n; i++) { if (raw.p[i] == '\\') i++; buffer[n++] = raw.p[i]; }
    buffer[n] = 0;
    *out = (Str){buffer,(uint32_t)n};
    return ERR_SUCCESS;
}
static bool prefix_complete(Str text) {
    if (!text.n || text.p[0] != '{') return false;
    size_t i = 0, depth = 0;
    while (i < text.n) {
        char c = text.p[i];
        if (c == '"') { Str ignored; if (!prefix_string(text,&i,&ignored)) return false; continue; }
        if (c == '{') depth++;
        else if (c == '}' && (!depth || !--depth)) return true;
        i++;
    }
    return false;
}
static Err prefix_route(TokenStream *s, const ReaderRawLine *line) {
    uint64_t uidx = s->uidx++;
    Str text = {line->bytes.p,TOKEN_LINE_LIMIT};
    if (text.n >= 3 && !memcmp(text.p,"\xef\xbb\xbf",3)) { text.p += 3; text.n -= 3; }
    JsonStats stats = {0};
    size_t dropped = 0;
    while (wtf8_validate(text,STRICT,&stats) != JSON_OK && dropped++ < 4) text.n--;
    if (wtf8_validate(text,STRICT,&stats) != JSON_OK) return ERR_SUCCESS;
    Str kind, timestamp;
    Err err = prefix_value(s,text,"type",false,&kind);
    if (err.code) return err;
    Str payload = prefix_field(text,"payload",true,false);
    TokenObservation obs = {.line = line->index,.uidx = uidx};
    if (str_equal(kind,STR_LIT("session_meta"))) {
        obs.tag = TOKEN_XM;
        const char *ids[] = {"id","session_id","sessionId"};
        for (size_t i = 0; i < 3; i++) {
            Str value;
            err = prefix_value(s,payload,ids[i],false,&value);
            if (err.code) return err;
            if (value.p) { err = retain(s,value,&obs.meta.session_id); break; }
        }
        if (!err.code) err = append(s,obs);
    } else if (str_equal(kind,STR_LIT("turn_context")) && payload.p) {
        err = prefix_value(s,text,"timestamp",false,&timestamp);
        if (err.code || !timestamp_valid(timestamp)) return err;
        Str info = prefix_field(payload,"info",true,false), values[4];
        const char *names[] = {"model","model_name","model","model_name"};
        for (size_t i = 0; i < 4; i++) {
            err = prefix_value(s,i < 2 ? payload : info,names[i],true,&values[i]);
            if (err.code) return err;
        }
        obs.tag = TOKEN_XC;
        err = model_state(s,values,&obs.model_state);
        if (obs.model_state.kind == MODEL_CLEAR && !prefix_complete(payload)) obs.model_state.kind = MODEL_UNCHANGED;
        if (!err.code) err = append(s,obs);
    }
    return err;
}
Err tokenstream_raw(void *context, const ReaderRawLine *line) {
    TokenStream *s = context;
    if (line->bytes.n <= TOKEN_LINE_LIMIT) return ERR_SUCCESS;
    if (!line->terminated && !token_tail_complete(line->bytes)) { s->unconsumed_tail = true; return ERR_SUCCESS; }
    return prefix_route(s,line);
}
static bool marker(Str bytes, const char *text) { return memmem(bytes.p,bytes.n,text,strlen(text)) != NULL; }
static Err bare(TokenStream *s, yyjson_val *root, TokenObservation *obs, bool *present) {
    yyjson_val *usage = object(root,"usage"), *data = object(root,"data");
    const char *containers[] = {"data","result","response"};
    for (size_t i = 0; !usage && i < 3; i++) usage = object(object(root,containers[i]),"usage");
    if (!usage) return ERR_SUCCESS;
    const char *aliases[3][3] = {{"input_tokens","prompt_tokens","input"},
        {"output_tokens","completion_tokens","output"}, {"cached_input_tokens","cache_read_input_tokens","cached_tokens"}};
    TokenInteger values[3] = {{0}};
    for (size_t i = 0; i < 3; i++) for (size_t j = 0; j < 3; j++) {
        values[i] = integer(usage,aliases[i][j],true);
        if (values[i].present) break;
    }
    if (!values[0].present || !values[1].present) return ERR_SUCCESS;
    obs->last = (TokenTotals){.present = true,.input = values[0].value > values[2].value ? values[0].value-values[2].value : 0,
        .output = values[1].value,.cached = values[2].value};
    if (!obs->last.input && !obs->last.output && !obs->last.cached) return ERR_SUCCESS;
    Str models[] = {string(root,"model",true),string(root,"model_name",true),string(data,"model",true),string(data,"model_name",true)};
    TokenModel model = {0};
    Err err = model_state(s,models,&model);
    if (err.code) return err;
    obs->model = model.model;
    err = retain(s,string(root,"timestamp",true),&obs->timestamp);
    *present = !err.code;
    return err;
}
Err tokenstream_decoded(void *context, const ReaderRawLine *line, const JsonRead *json) {
    TokenStream *s = context;
    if (line->bytes.n > TOKEN_LINE_LIMIT) return ERR_SUCCESS;
    yyjson_val *root = json->doc ? yyjson_doc_get_root(json->doc) : NULL;
    yyjson_val *payload = object(root,"payload"), *info = object(payload,"info");
    Str kind = string(root,"type",false);
    TokenObservation obs = {.line = line->index};
    bool meta_ready = false;
    Err err = ERR_SUCCESS;
    if (!s->has_prepass && str_equal(kind,STR_LIT("session_meta"))) {
        err = metadata_project(s,root,payload,&obs.meta,dom_string,dom_object,dom_integer);
        if (err.code) return err;
        meta_ready = true;
        if (!s->has_prepass) { s->prepass = obs.meta; s->has_prepass = true; }
    }
    if (!line->terminated && line->bytes.n && (!token_tail_complete(line->bytes) || !root)) {
        if (!token_tail_complete(line->bytes)) {
            err = incomplete_prepass(s,line,json);
            if (err.code) return err;
        }
        s->unconsumed_tail = true;
        return ERR_SUCCESS;
    }
    if (!line->bytes.n) return ERR_SUCCESS;
    obs.uidx = s->uidx++;
    if (!yyjson_is_obj(root)) return ERR_SUCCESS;
    if (marker(line->bytes,"\"usage\"")) {
        if (obj_get_last(root,STR_LIT("type"))) return ERR_SUCCESS;
        bool present = false;
        obs.tag = TOKEN_B;
        err = bare(s,root,&obs,&present);
        return err.code || !present ? err : append(s,obs);
    }
    if (!(marker(line->bytes,"\"event_msg\"") || marker(line->bytes,"\"turn_context\"") ||
          marker(line->bytes,"\"session_meta\"") || marker(line->bytes,"\"inter_agent_communication_metadata\""))) return ERR_SUCCESS;
    if (marker(line->bytes,"\"type\":\"event_msg\"") && !marker(line->bytes,"\"token_count\"") &&
        !marker(line->bytes,"\"task_started\"")) return ERR_SUCCESS;
    if (!str_equal(kind,STR_LIT("session_meta")) && !timestamp_valid(string(root,"timestamp",false))) return ERR_SUCCESS;
    obs.ordinal = integer(root,"ordinal",false);
    if (str_equal(kind,STR_LIT("session_meta"))) {
        obs.tag = TOKEN_M;
        if (!meta_ready) err = metadata_project(s,root,payload,&obs.meta,dom_string,dom_object,dom_integer);
    }
    else if (str_equal(kind,STR_LIT("turn_context"))) {
        obs.tag = TOKEN_C;
        Str values[] = {string(payload,"model",true),string(payload,"model_name",true),string(info,"model",true),string(info,"model_name",true)};
        err = model_state(s,values,&obs.model_state);
        if (!err.code) err = retain(s,string(root,"timestamp",false),&obs.timestamp);
    } else if (str_equal(kind,STR_LIT("inter_agent_communication_metadata"))) {
        obs.tag = TOKEN_I; obs.trigger = yyjson_is_true(typed(payload,"trigger_turn",YYJSON_TYPE_BOOL));
    } else if (str_equal(kind,STR_LIT("event_msg"))) {
        Str type = string(payload,"type",false);
        if (str_equal(type,STR_LIT("task_started"))) obs.tag = TOKEN_S;
        else if (str_equal(type,STR_LIT("token_count"))) obs.tag = TOKEN_T;
        else return ERR_SUCCESS;
        const char *ids[] = {"turn_id","turnId","id"};
        for (size_t i = 0; i < 6; i++) {
            Str id = string(i < 3 ? payload : info,ids[i%3],false);
            if (id.p) { err = retain(s,id,&obs.turn_id); break; }
        }
        if (!err.code && obs.tag == TOKEN_T) {
            Str values[] = {string(info,"model",true),string(info,"model_name",true),string(payload,"model",true),string(root,"model",true)};
            TokenModel model = {0};
            err = model_state(s,values,&model);
            obs.model = model.model;
            if (!err.code) err = retain(s,string(root,"timestamp",false),&obs.timestamp);
            if (!err.code) { obs.last = totals(object(info,"last_token_usage")); obs.total = totals(object(info,"total_token_usage")); }
        }
    } else return ERR_SUCCESS;
    return err.code ? err : append(s,obs);
}
