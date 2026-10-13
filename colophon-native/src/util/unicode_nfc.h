#ifndef COLOPHON_UTIL_UNICODE_NFC_H
#define COLOPHON_UTIL_UNICODE_NFC_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
/* Codepoint interface for the shared WTF-8 string wrapper. Surrogates are
 * opaque codepoints. On success caller owns *output (free); empty output may
 * be NULL. On invalid input/allocation failure outputs are NULL/0. */
bool cp_unicode_nfc(const uint32_t *input, size_t length,
                    uint32_t **output, size_t *output_length);
#endif
