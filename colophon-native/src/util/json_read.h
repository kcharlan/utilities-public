#ifndef CP_JSON_READ_H
#define CP_JSON_READ_H
#include "str.h"
#include "omap.h"
#include "yyjson.h"
typedef enum { BYTES, STRICT, STR } JsonMode;
typedef enum { JSON_CONSTANTS_ALLOW, JSON_CONSTANTS_REJECT } JsonConstants;
typedef enum { JSON_OK, JSON_INVALID, JSON_NOMEM, JSON_T2_NEST, JSON_T2_ENCODING, JSON_T2_SENTINEL } JsonStatus;
typedef struct {
    uint64_t invalid_unicode, raw_surrogates, bom, nonfinite, lone_surrogates;
    uint64_t invalid_number_spellings, integer_digit_limit;
    unsigned first_constant; /* 1 NaN, 2 Infinity, 3 -Infinity; rejected too. */
} JsonStats;
typedef struct { yyjson_doc *doc; JsonStatus status; JsonStats stats; } JsonRead;
JsonStatus wtf8_validate(Str input, JsonMode mode, JsonStats *stats);
JsonRead json_read(Str input, JsonMode mode, JsonConstants constants, const char *site);
void json_read_free(JsonRead *read);
/* One iterative whole-document spelling/depth check; no integer conversion. */
JsonStatus json_doc_check(yyjson_doc *doc, size_t max_depth, JsonConstants constants, JsonStats *stats);
JsonStatus json_depth_check(yyjson_doc *doc, size_t max_depth);
yyjson_val *obj_get_last(yyjson_val *object, Str key);
yyjson_val *obj_get_first_typed(yyjson_val *object, Str key, yyjson_type type);
/* Caller owns the returned mutable document; numbers retain raw spellings. */
Err json_load_dict_semantics(yyjson_doc *source, yyjson_mut_doc **out);
/* Iterative owned freeze of a well-formed mutable tree. Callers validate depth
 * before creating it. Does not validate semantics or emit events. Copies tags,
 * raw/string bytes including NUL, and key order; no duplicate reconciliation.
 * Uses yyjson's default allocator for doc+aligned values and independent strings,
 * compatible with yyjson_doc_free; source may be freed after success. On any
 * allocation/size failure returns ERR_NOMEM and leaves *out NULL. */
Err json_freeze(yyjson_mut_doc *source, yyjson_doc **out);
/* Zero-initialized map owns copied keys/entries; values borrow source doc. */
Err json_object_dict(yyjson_val *object, Omap *out);
#endif
