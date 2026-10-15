#ifndef CP_CLAUDE_FOUNDATION_H
#define CP_CLAUDE_FOUNDATION_H
#include "util/str.h"
/* System Foundation, matching ClaudeJSONObject.decode's JSONSerialization.
 * No objects or autoreleased storage escape these calls. */
bool claude_foundation_object_valid(Str bytes);
bool claude_foundation_number(Str literal, int64_t *integer, bool *boolean);
/* Pinned normalizeClaudeModel regexes, with Swift grapheme-boundary checks.
 * SIZE_MAX means no suffix; otherwise output is an original UTF-8 offset. */
Err claude_foundation_model_suffix(Str model,bool version,size_t *offset);
#endif
