#ifndef CP_JSON_NUMBER_H
#define CP_JSON_NUMBER_H
#include "str.h"
#include "pynum.h"
#include "yyjson.h"
bool json_number_is_integer(Str lexeme);
/* Conversion alone emits tier2_int, only for a consumed oversized integer. */
bool json_number(yyjson_val *value, const char *site, PyNum *out);
bool json_number_equal(yyjson_val *a, yyjson_val *b);
#endif
