#ifndef CP_CLASSIFY_H
#define CP_CLASSIFY_H
#include "util/json_read.h"
/* Caller frees key.p, including on successful empty-string classification.
 * Input is a borrowed object; duplicate members use last-value semantics. */
Err record_type_key(yyjson_val *record, Str *key);
bool record_type_known(Str key);
#endif
