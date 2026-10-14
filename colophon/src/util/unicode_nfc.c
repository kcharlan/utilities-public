#include "unicode_nfc.h"
#include "gen/unicode_nfc.h"
#include <stdlib.h>
#include <string.h>

typedef struct { uint32_t *data; size_t length, capacity; } Codepoints;

static uint32_t combining(uint32_t cp) {
    size_t lo = 0, hi = cp_unicode_combining_count;
    while (lo < hi) {
        size_t mid = lo + (hi - lo) / 2;
        if (cp_unicode_combining[mid][0] < cp) lo = mid + 1;
        else hi = mid;
    }
    return lo < cp_unicode_combining_count && cp_unicode_combining[lo][0] == cp
        ? cp_unicode_combining[lo][1] : 0;
}

static bool append_ordered(Codepoints *out, uint32_t cp) {
    if (out->length == out->capacity) {
        if (out->capacity > SIZE_MAX / 2 / sizeof(uint32_t)) return false;
        size_t capacity = out->capacity ? out->capacity * 2 : 32;
        uint32_t *data = realloc(out->data, capacity * sizeof(*data));
        if (!data) return false;
        out->data = data;
        out->capacity = capacity;
    }
    size_t pos = out->length++;
    uint32_t cc = combining(cp);
    while (cc && pos && combining(out->data[pos - 1]) > cc) {
        out->data[pos] = out->data[pos - 1];
        --pos;
    }
    out->data[pos] = cp;
    return true;
}

static bool decompose(Codepoints *out, uint32_t cp) {
    if (cp >= 0xac00 && cp < 0xac00 + 11172) {
        uint32_t index = cp - 0xac00;
        return append_ordered(out, 0x1100 + index / 588)
            && append_ordered(out, 0x1161 + (index % 588) / 28)
            && (!(index % 28) || append_ordered(out, 0x11a7 + index % 28));
    }
    size_t lo = 0, hi = cp_unicode_decomposition_count;
    while (lo < hi) {
        size_t mid = lo + (hi - lo) / 2;
        if (cp_unicode_decomposition[mid].cp < cp) lo = mid + 1;
        else hi = mid;
    }
    if (lo == cp_unicode_decomposition_count || cp_unicode_decomposition[lo].cp != cp)
        return append_ordered(out, cp);
    const CpUnicodeMapping *map = &cp_unicode_decomposition[lo];
    for (uint32_t i = 0; i < map->length; ++i)
        if (!decompose(out, cp_unicode_decomposition_data[map->offset + i])) return false;
    return true;
}

static uint32_t compose(uint32_t first, uint32_t second) {
    if (first >= 0x1100 && first < 0x1100 + 19 && second >= 0x1161 && second < 0x1161 + 21)
        return 0xac00 + ((first - 0x1100) * 21 + second - 0x1161) * 28;
    if (first >= 0xac00 && first < 0xac00 + 11172 && (first - 0xac00) % 28 == 0
        && second > 0x11a7 && second < 0x11a7 + 28)
        return first + second - 0x11a7;
    size_t lo = 0, hi = cp_unicode_composition_count;
    while (lo < hi) {
        size_t mid = lo + (hi - lo) / 2;
        const uint32_t *row = cp_unicode_composition[mid];
        if (row[0] < first || (row[0] == first && row[1] < second)) lo = mid + 1;
        else hi = mid;
    }
    if (lo < cp_unicode_composition_count && cp_unicode_composition[lo][0] == first
        && cp_unicode_composition[lo][1] == second) return cp_unicode_composition[lo][2];
    return 0;
}

bool cp_unicode_nfc(const uint32_t *input, size_t length,
                    uint32_t **output, size_t *output_length) {
    if (!output || !output_length) return false;
    *output = NULL;
    *output_length = 0;
    if ((!input && length) || length > SIZE_MAX / sizeof(uint32_t)) return false;
    bool ascii = true;
    for (size_t i = 0; i < length; ++i) {
        if (input[i] > 0x10ffff) return false;
        if (input[i] > 0x7f) ascii = false;
    }
    if (ascii) {
        if (!length) return true;
        *output = malloc(length * sizeof(uint32_t));
        if (!*output) return false;
        memcpy(*output, input, length * sizeof(uint32_t));
        *output_length = length;
        return true;
    }
    Codepoints out = {0};
    for (size_t i = 0; i < length; ++i) {
        if (!decompose(&out, input[i])) { free(out.data); return false; }
    }
    size_t used = 1, starter = 0;
    uint32_t last_cc = combining(out.data[0]);
    for (size_t i = 1; i < out.length; ++i) {
        uint32_t cp = out.data[i], cc = combining(cp);
        uint32_t composite = (last_cc < cc || last_cc == 0) ? compose(out.data[starter], cp) : 0;
        if (composite) out.data[starter] = composite;
        else {
            if (!cc) starter = used;
            out.data[used++] = cp;
            last_cc = cc;
        }
    }
    *output = out.data;
    *output_length = used;
    return true;
}
