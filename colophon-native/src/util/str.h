#ifndef CP_STR_H
#define CP_STR_H
#include "arena.h"
#include <stdbool.h>
#include <stdint.h>
typedef struct {
    const char *p;
    uint32_t n;
} Str;
#define STR_LIT(s) ((Str){(s), sizeof(s) - 1})
bool str_equal(Str a, Str b);
int str_compare(Str a, Str b);
uint64_t str_hash(Str s);
Err str_copy(Arena *arena, Str input, Str *output);
/* Strict WTF-8; raw surrogate pairs remain two codepoints. */
Err str_codepoints(Str input, size_t *count);
bool str_decode_next(Str input, size_t *offset, uint32_t *codepoint);
/* Strict UTF-8 scalar membership only: empty/BOM/NUL are valid, surrogates
 * (including adjacent raw surrogate pairs) are invalid. No site policy/events. */
bool str_utf8_scalar_valid(Str input);
/* Python Unicode 16 regex \w: isalnum or underscore, per scalar. */
bool str_word_codepoint(uint32_t codepoint);
bool str_space_codepoint(uint32_t codepoint);
/* Unicode 16 NFKC gains an ASCII URL delimiter for this scalar. */
bool str_url_delimiter_codepoint(uint32_t codepoint);
bool str_linebreak_codepoint(uint32_t codepoint);
/* Borrowed Python lstrip/strip slice; right=false preserves trailing space. */
Str str_trim(Str text, bool right);
size_t str_encode_codepoint(uint32_t codepoint, char output[4]);
/* trusted_site is a schema field path, never a content value or log path.
 * The shared wrapper notes nfc_non_ascii once per non-ASCII invocation. */
Err str_nfc(Arena *arena, Str input, const char *trusted_site, Str *output);
/* Python Unicode lowercase, including contextual Final_Sigma; no NFC change. */
Err str_lower(Arena *arena, Str input, Str *output);
#endif
