#include "pynum.h"
#include "events.h"
#include "time.h"
#include "yyjson.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
bool floordiv_i64(int64_t a, int64_t b, int64_t *out) {
    if (!b || (a == INT64_MIN && b == -1))
        return false;
    int64_t q = a / b, r = a % b;
    if (r && ((r < 0) != (b < 0)))
        q--;
    *out = q;
    return true;
}
bool pynum_equal(PyNum a, PyNum b) {
    if (!a.is_float && !b.is_float)
        return a.i == b.i;
    if (a.is_float && b.is_float)
        return a.f == b.f;
    double d = a.is_float ? a.f : b.f;
    int64_t i = a.is_float ? b.i : a.i;
    return isfinite(d) && d >= -0x1p63 && d < 0x1p63 && trunc(d) == d && (int64_t)d == i;
}
static double floating(PyNum v) {
    return v.is_float ? v.f : (double)v.i;
}
int pynum_compare(PyNum a, PyNum b) {
    if (pynum_equal(a,b)) return 0;
    if (!a.is_float&&!b.is_float) return a.i<b.i?-1:1;
    if (a.is_float&&b.is_float) return a.f<b.f?-1:1;
    /* long double is binary64 on Apple arm64. Truncation within the checked
     * int64 bounds preserves exact integer ordering and fractional signs. */
    PyNum integer=a.is_float?b:a, real=a.is_float?a:b;
    int order;
    if(real.f>=0x1p63) order=-1;
    else if(real.f< -0x1p63) order=1;
    else {
        int64_t truncated=(int64_t)real.f;
        if(integer.i!=truncated) order=integer.i<truncated?-1:1;
        else order=(double)truncated<real.f?-1:1;
    }
    return a.is_float?-order:order;
}
static bool range_once(const char *site, bool *noted) {
    if (!noted || !*noted) {
        event_note("tier2_time", site, 1);
        if (noted)
            *noted = true;
    }
    return false;
}
static bool range(const char *site) {
    return range_once(site, NULL);
}
bool pynum_timing(PyNum value, const char *site, PyNum *out) {
    return pynum_timing_once(value, site, NULL, out);
}
bool pynum_timing_once(PyNum value, const char *site, bool *range_noted, PyNum *out) {
    if (value.is_float) {
        if (!isfinite(value.f))
            return false;
        if (value.f >= 0x1p63 || value.f < -0x1p63)
            return range_once(site, range_noted);
        event_note("float_timing", site, 1);
    }
    *out = value;
    return true;
}
static bool operation(PyNum a, PyNum b, int op, const char *site, PyNum *out) {
    PyNum v = {0};
    if (a.is_float || b.is_float) {
        double x = floating(a), y = floating(b);
        v.is_float = true;
        if (op == 0)
            v.f = x + y;
        else if (op == 1)
            v.f = x - y;
        else if (op == 2)
            v.f = x * y;
        else {
            if (y == 0)
                return false;
            double mod = fmod(x, y), div = (x - mod) / y;
            if (mod && ((mod < 0) != (y < 0)))
                div--;
            v.f = div ? floor(div) : copysign(0.0, x / y);
            if (div - v.f > 0.5)
                v.f++;
        }
        if (!isfinite(v.f))
            return range(site);
    } else {
        bool overflow = false;
        if (op == 0)
            overflow = __builtin_add_overflow(a.i, b.i, &v.i);
        else if (op == 1)
            overflow = __builtin_sub_overflow(a.i, b.i, &v.i);
        else if (op == 2)
            overflow = __builtin_mul_overflow(a.i, b.i, &v.i);
        else {
            if (!b.i)
                return false;
            overflow = !floordiv_i64(a.i, b.i, &v.i);
        }
        if (overflow)
            return range(site);
    }
    return pynum_timing(v, site, out);
}
bool pynum_add(PyNum a, PyNum b, const char *s, PyNum *o) {
    return operation(a, b, 0, s, o);
}
bool pynum_sub(PyNum a, PyNum b, const char *s, PyNum *o) {
    return operation(a, b, 1, s, o);
}
bool pynum_mul(PyNum a, PyNum b, const char *s, PyNum *o) {
    return operation(a, b, 2, s, o);
}
bool pynum_floordiv(PyNum a, PyNum b, const char *s, PyNum *o) {
    return operation(a, b, 3, s, o);
}
/* One shortest-roundtrip decomposition for exact clock comparisons and
 * truncation. exponent is the decimal power attached to the digit integer. */
bool pynum_decimal(double value, PyDecimal *out) {
    if (!isfinite(value))
        return false;
    yyjson_mut_doc *doc = yyjson_mut_doc_new(NULL);
    if (!doc)
        return false;
    yyjson_mut_doc_set_root(doc, yyjson_mut_real(doc, value));
    char *s = yyjson_mut_write(doc, 0, NULL);
    yyjson_mut_doc_free(doc);
    if (!s)
        return false;
    *out = (PyDecimal){.negative = *s == '-'};
    int decimals = 0;
    bool point = false;
    char *p = s + out->negative;
    for (; *p && *p != 'e' && *p != 'E'; p++) {
        if (*p == '.') {
            point = true;
            continue;
        }
        out->digits[out->length++] = *p;
        if (point)
            decimals++;
    }
    out->exponent = (*p ? atoi(p + 1) : 0) - decimals;
    free(s);
    while (out->length > 1 && out->digits[0] == '0') {
        memmove(out->digits, out->digits + 1, (size_t)--out->length);
    }
    if (out->length == 1 && out->digits[0] == '0')
        out->negative = false;
    return true;
}
bool pynum_context_int(PyNum number) {
    if (!number.is_float) return true;
    if (!isfinite(number.f) || number.f < -0x1p63 || number.f >= 0x1p63) return false;
    PyDecimal decimal;
    if (!pynum_decimal(number.f,&decimal)) return false;
    int fractional=decimal.exponent<0?-decimal.exponent:0;
    for (int i=0;i<fractional;i++) {
        int at=decimal.length-1-i;
        if (at>=0 && decimal.digits[at]!='0') return false;
    }
    int positions=decimal.length+decimal.exponent;
    if(positions>19)return false;
    uint64_t magnitude=0,limit=decimal.negative?(UINT64_C(1)<<63):INT64_MAX;
    for(int i=0;i<positions;i++) {
        unsigned digit=i<decimal.length?(unsigned)(decimal.digits[i]-'0'):0;
        if(magnitude>(limit-digit)/10)return false;
        magnitude=magnitude*10+digit;
    }
    return true;
}
bool pynum_catalog_context(const char *spelling, double binary, int64_t *out) {
    if (!isfinite(binary) || trunc(binary)!=binary || binary < -0x1p63 || binary >= 0x1p63)
        return false;
    if (fabs(binary)<0x1p53) { *out=(int64_t)binary; return true; }
    bool negative=*spelling=='-';
    const char *p=spelling+negative;
    unsigned __int128 coefficient=0, maximum=~(unsigned __int128)0;
    int fractional=0, discarded=0;
    bool point=false, significant=false;
    while (*p && *p!='e' && *p!='E') {
        if (*p=='.') { point=true; p++; continue; }
        unsigned digit=(unsigned)(*p++-'0');
        if (digit>9) return false;
        if (point) fractional++;
        if (!significant && !digit) continue;
        significant=true;
        if (discarded || coefficient>(maximum-digit)/10) discarded++;
        else coefficient=coefficient*10+digit;
    }
    long exponent=0;
    if (*p) {
        char *end;
        exponent=strtol(p+1,&end,10);
        if (*end || exponent < -100000 || exponent > 100000) return false;
    }
    exponent=exponent-fractional+discarded;
    if (exponent < -128 || exponent > 127) return false;
    while (coefficient && coefficient%10==0 && exponent<127) { coefficient/=10; exponent++; }
    if (coefficient>UINT64_MAX) return false;
    if (exponent>=0) {
        while (exponent--) {
            if (coefficient>(unsigned __int128)INT64_MAX/10) return false;
            coefficient*=10;
        }
    } else while (exponent++) coefficient/=10;
    if (coefficient>(unsigned __int128)INT64_MAX) return false;
    *out=negative?-(int64_t)coefficient:(int64_t)coefficient;
    return true;
}
/* yyjson's shortest roundtrip decimal has the same significand as repr(double).
 * Scale/truncate its decimal digits directly, avoiding binary multiplication. */
bool pynum_epoch_ms(PyNum value, bool milliseconds, const char *site, int64_t *out) {
    return pynum_epoch_ms_once(value, milliseconds, site, NULL, out);
}
bool pynum_epoch_ms_once(PyNum value, bool milliseconds, const char *site, bool *range_noted,
                         int64_t *out) {
    if (!value.is_float)
        return time_ms_from_i64_once(value.i, milliseconds, site, range_noted, out);
    PyDecimal decimal;
    if (!pynum_decimal(value.f, &decimal))
        return false;
    bool neg = decimal.negative;
    int count = decimal.length + decimal.exponent + (milliseconds ? 0 : 3);
    uint64_t result = 0, limit = neg ? (UINT64_C(1) << 63) : INT64_MAX;
    bool ok = true;
    if (count > 20)
        ok = false;
    for (int i = 0; ok && i < count; i++) {
        unsigned d = i < decimal.length ? (unsigned)(decimal.digits[i] - '0') : 0;
        if (result > (limit - d) / 10)
            ok = false;
        else
            result = result * 10 + d;
    }
    if (!ok)
        return range_once(site, range_noted);
    *out = neg ? (result == (UINT64_C(1) << 63) ? INT64_MIN : -(int64_t)result) : (int64_t)result;
    return true;
}
bool pynum_epoch_compare(PyNum seconds, int64_t milliseconds, int *order) {
    if (!seconds.is_float) {
        __int128 scaled = (__int128)seconds.i * 1000;
        *order = (scaled > milliseconds) - (scaled < milliseconds);
        return true;
    }
    PyDecimal decimal;
    if (!pynum_decimal(seconds.f, &decimal))
        return false;
    bool negative = milliseconds < 0;
    bool zero = decimal.length == 1 && decimal.digits[0] == '0';
    if (decimal.negative != negative) {
        *order = decimal.negative ? -1 : 1;
        return true;
    }
    uint64_t magnitude = negative ? (uint64_t)(-(milliseconds + 1)) + 1 : (uint64_t)milliseconds;
    if (zero || !magnitude) {
        *order = zero ? (magnitude ? (negative ? 1 : -1) : 0) : (decimal.negative ? -1 : 1);
        return true;
    }
    char digits[32];
    int length = snprintf(digits, sizeof digits, "%llu", (unsigned long long)magnitude);
    int positions = decimal.length + decimal.exponent + 3,
        cmp = (positions > length) - (positions < length);
    if (!cmp) {
        int total = decimal.length > length ? decimal.length : length;
        for (int i = 0; i < total && !cmp; i++) {
            char a = i < decimal.length ? decimal.digits[i] : '0', b = i < length ? digits[i] : '0';
            cmp = (a > b) - (a < b);
        }
    }
    *order = negative ? -cmp : cmp;
    return true;
}
