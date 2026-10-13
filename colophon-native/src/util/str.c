#include "str.h"
#include "events.h"
#include "unicode_nfc.h"
#include "gen/unicode_nfc.h"
#include <stdlib.h>
#include <string.h>
bool str_equal(Str a, Str b) {
    return a.n == b.n && (!a.n || memcmp(a.p, b.p, a.n) == 0);
}
int str_compare(Str a, Str b) {
    size_t n = a.n < b.n ? a.n : b.n;
    int c = n ? memcmp(a.p, b.p, n) : 0;
    return c ? c : (a.n > b.n) - (a.n < b.n);
}
uint64_t str_hash(Str s) {
    uint64_t h = UINT64_C(14695981039346656037);
    for (uint32_t i = 0; i < s.n; i++) {
        h ^= (unsigned char)s.p[i];
        h *= UINT64_C(1099511628211);
    }
    return h;
}
Err str_copy(Arena *a, Str in, Str *out) {
    char *p;
    Err e = arena_alloc(a, (size_t)in.n + 1, 1, (void **)&p);
    if (e.code)
        return e;
    if (in.n)
        memcpy(p, in.p, in.n);
    p[in.n] = 0;
    *out = (Str){p, in.n};
    return ERR_SUCCESS;
}
bool str_utf8_scalar_valid(Str input) {
    size_t offset = 0;
    uint32_t cp;
    while (offset < input.n)
        if (!str_decode_next(input, &offset, &cp) || (cp >= 0xd800 && cp <= 0xdfff))
            return false;
    return true;
}
bool str_decode_next(Str s, size_t *at, uint32_t *cp) {
    if (*at >= s.n)
        return false;
    unsigned char c = (unsigned char)s.p[(*at)++];
    unsigned need;
    uint32_t min;
    if (c < 128) {
        *cp = c;
        return true;
    }
    if (c >= 0xc2 && c <= 0xdf) {
        need = 1;
        *cp = c & 31;
        min = 128;
    } else if (c >= 0xe0 && c <= 0xef) {
        need = 2;
        *cp = c & 15;
        min = 2048;
    } else if (c >= 0xf0 && c <= 0xf4) {
        need = 3;
        *cp = c & 7;
        min = 65536;
    } else
        return false;
    if (need > s.n - *at)
        return false;
    while (need--) {
        c = (unsigned char)s.p[(*at)++];
        if ((c & 0xc0) != 0x80)
            return false;
        *cp = (*cp << 6) | (c & 63);
    }
    return *cp >= min && *cp <= 0x10ffff;
}
size_t str_encode_codepoint(uint32_t c, char p[4]) {
    if (c < 128) {
        p[0] = (char)c;
        return 1;
    }
    if (c < 2048) {
        p[0] = (char)(0xc0 | (c >> 6));
        p[1] = (char)(0x80 | (c & 63));
        return 2;
    }
    if (c < 65536) {
        p[0] = (char)(0xe0 | (c >> 12));
        p[1] = (char)(0x80 | ((c >> 6) & 63));
        p[2] = (char)(0x80 | (c & 63));
        return 3;
    }
    if (c <= 0x10ffff) {
        p[0] = (char)(0xf0 | (c >> 18));
        p[1] = (char)(0x80 | ((c >> 12) & 63));
        p[2] = (char)(0x80 | ((c >> 6) & 63));
        p[3] = (char)(0x80 | (c & 63));
        return 4;
    }
    return 0;
}
Err str_codepoints(Str s, size_t *count) {
    size_t i = 0, n = 0;
    uint32_t cp;
    while (i < s.n) {
        if (!str_decode_next(s, &i, &cp))
            return err_make(ERR_INVALID, "invalid WTF-8");
        n++;
    }
    *count = n;
    return ERR_SUCCESS;
}
Err str_nfc(Arena *a, Str s, const char *site, Str *out) {
    size_t count;
    Err e = str_codepoints(s, &count);
    if (e.code)
        return e;
    if (count == s.n)
        return str_copy(a, s, out);
    event_note("nfc_non_ascii", site, 1);
    uint32_t *input = malloc(count * sizeof(*input)), *normalized = NULL;
    size_t n = 0, i = 0;
    if (!input)
        return err_make(ERR_NOMEM, "NFC allocation failed");
    for (size_t j = 0; j < count; j++)
        (void)str_decode_next(s, &i, &input[j]);
    bool ok = cp_unicode_nfc(input, count, &normalized, &n);
    free(input);
    if (!ok)
        return err_make(ERR_NOMEM, "NFC allocation failed");
    if (n > UINT32_MAX / 4) {
        free(normalized);
        return err_make(ERR_NOMEM, "NFC string too large");
    }
    char *p;
    e = arena_alloc(a, n * 4 + 1, 1, (void **)&p);
    if (e.code) {
        free(normalized);
        return e;
    }
    size_t at = 0;
    for (i = 0; i < n; i++)
        at += str_encode_codepoint(normalized[i], p + at);
    free(normalized);
    p[at] = 0;
    *out = (Str){p, (uint32_t)at};
    return ERR_SUCCESS;
}
static bool in_ranges(uint32_t cp,const uint32_t ranges[][2],size_t n){
    size_t lo=0,hi=n;while(lo<hi){size_t m=lo+(hi-lo)/2;if(cp<ranges[m][0])hi=m;else if(cp>ranges[m][1])lo=m+1;else return true;}return false;
}
bool str_word_codepoint(uint32_t cp) {
    return cp == '_' || in_ranges(cp, cp_unicode_alphanumeric, cp_unicode_alphanumeric_count);
}
bool str_space_codepoint(uint32_t cp) {
    return in_ranges(cp, cp_unicode_whitespace, cp_unicode_whitespace_count);
}
bool str_url_delimiter_codepoint(uint32_t cp) {
    return in_ranges(cp,cp_unicode_url_delimiter,cp_unicode_url_delimiter_count);
}
bool str_linebreak_codepoint(uint32_t cp) {
    return in_ranges(cp, cp_unicode_linebreak, cp_unicode_linebreak_count);
}
Str str_trim(Str value, bool right) {
    size_t offset = 0, first = 0, last = 0;
    uint32_t cp;
    bool leading = true;
    while (str_decode_next(value, &offset, &cp)) {
        if (leading && str_space_codepoint(cp)) {
            first = offset;
            continue;
        }
        leading = false;
        if (!str_space_codepoint(cp))
            last = offset;
    }
    size_t end = right ? last : value.n;
    return (Str){value.p ? value.p + first : NULL, (uint32_t)(end >= first ? end - first : 0)};
}
static bool final_sigma(const uint32_t *cps,size_t n,size_t at){
    size_t before=at,after=at+1;
    while(before&&in_ranges(cps[before-1],cp_unicode_case_ignorable,cp_unicode_case_ignorable_count))before--;
    if(!before||!in_ranges(cps[before-1],cp_unicode_cased,cp_unicode_cased_count))return false;
    while(after<n&&in_ranges(cps[after],cp_unicode_case_ignorable,cp_unicode_case_ignorable_count))after++;
    return after==n||!in_ranges(cps[after],cp_unicode_cased,cp_unicode_cased_count);
}
Err str_lower(Arena *arena,Str s,Str *out){
    size_t count;Err e=str_codepoints(s,&count);if(e.code!=ERR_OK)return e;
    if(count>UINT32_MAX/12)return err_make(ERR_NOMEM,"lowercase string too large");
    uint32_t *cps=malloc((count?count:1)*sizeof *cps);if(!cps)return err_make(ERR_NOMEM,"lowercase allocation failed");
    size_t pos=0;for(size_t i=0;i<count;i++)(void)str_decode_next(s,&pos,&cps[i]);
    char *bytes=NULL;e=arena_alloc(arena,count*12+1,1,(void **)&bytes);if(e.code!=ERR_OK){free(cps);return e;}
    size_t used=0;
    for(size_t i=0;i<count;i++){uint32_t cp=cps[i];
        if(cp==0x3a3&&final_sigma(cps,count,i)){used+=str_encode_codepoint(0x3c2,bytes+used);continue;}
        size_t lo=0,hi=cp_unicode_lowercase_count;while(lo<hi){size_t m=lo+(hi-lo)/2;if(cp_unicode_lowercase[m].cp<cp)lo=m+1;else hi=m;}
        if(lo<cp_unicode_lowercase_count&&cp_unicode_lowercase[lo].cp==cp){CpUnicodeMapping map=cp_unicode_lowercase[lo];for(size_t j=0;j<map.length;j++)used+=str_encode_codepoint(cp_unicode_lowercase_data[map.offset+j],bytes+used);}
        else used+=str_encode_codepoint(cp,bytes+used);
    }free(cps);bytes[used]=0;*out=(Str){bytes,(uint32_t)used};return ERR_SUCCESS;
}
