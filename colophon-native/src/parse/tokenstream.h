#ifndef CP_TOKENSTREAM_H
#define CP_TOKENSTREAM_H
#include "reader.h"
#include "util/intern.h"

#define TOKEN_LINE_LIMIT 262144
typedef struct { bool present; int64_t value; } TokenInteger;
typedef struct {
    bool present, has_reasoning;
    int64_t input, cached, output, reasoning;
} TokenTotals;
typedef struct { enum { MODEL_UNCHANGED, MODEL_SET, MODEL_CLEAR } kind; Str model; } TokenModel;
typedef struct {
    Str session_id, forked_from_id, fork_ts, project_path, history_base_thread_id;
    bool is_subagent;
    TokenInteger history_start_ordinal;
} TokenMeta;
typedef enum { TOKEN_M, TOKEN_C, TOKEN_I, TOKEN_S, TOKEN_T, TOKEN_B, TOKEN_XM, TOKEN_XC } TokenTag;
typedef struct {
    TokenTag tag;
    uint64_t line, uidx;
    TokenInteger ordinal;
    TokenMeta meta;
    Str timestamp, model, turn_id;
    TokenModel model_state;
    bool trigger;
    TokenTotals last, total;
} TokenObservation;
typedef struct {
    TokenObservation *observations;
    size_t count, capacity;
    bool has_prepass, unconsumed_tail;
    TokenMeta prepass;
    uint64_t uidx;
    Arena *arena; /* Borrowed record arena; owns copied observations/text. */
    Intern *identifiers; /* Borrowed run intern owner. */
} TokenStream;
/* No raw bytes or JSON pointers survive either callback. raw handles oversized
 * physical routes; decoded consumes only the original borrowed document. */
Err tokenstream_raw(void *context, const ReaderRawLine *line);
Err tokenstream_decoded(void *context, const ReaderRawLine *line, const JsonRead *json);
bool token_tail_complete(Str bytes);
/* Foundation trim shared by observation production and accounting evidence. */
Str token_model_trim(Str value);
bool token_foundation_space(uint32_t codepoint);
#endif
