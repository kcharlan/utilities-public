#ifndef CP_JSONW_H
#define CP_JSONW_H
#include "util/str.h"
#include "yyjson.h"
typedef struct { char *data; size_t length, capacity; Err error; } JsonWriter;
/* Ordered streaming bytes. The caller supplies punctuation/keys in schema order.
 * String and number methods validate and latch the first failure. */
void jsonw_bytes(JsonWriter *w,const void *bytes,size_t length);
void jsonw_raw(JsonWriter *w,const char *literal);
void jsonw_string(JsonWriter *w,Str text);
void jsonw_i64(JsonWriter *w,int64_t value);
void jsonw_i128(JsonWriter *w,__int128 value);
void jsonw_double(JsonWriter *w,double value);
void jsonw_value(JsonWriter *w,yyjson_val *value);
void jsonw_free(JsonWriter *w);
#endif
