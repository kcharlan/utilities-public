#ifndef CP_PYNUM_H
#define CP_PYNUM_H
#include <stdbool.h>
#include <stdint.h>
typedef struct {
    bool is_float;
    int64_t i;
    double f;
} PyNum;
typedef struct {
    bool negative;
    char digits[32];
    int length, exponent;
} PyDecimal;
bool pynum_decimal(double value, PyDecimal *out);
/* Foundation catalog context Int slow path; spelling belongs to JSON layer. */
bool pynum_catalog_context(const char *spelling, double binary, int64_t *out);
bool pynum_context_int(PyNum number);
bool floordiv_i64(int64_t a, int64_t b, int64_t *out);
bool pynum_equal(PyNum a, PyNum b);
/* Exact order for finite numbers; never converts an int64 to binary64 first. */
int pynum_compare(PyNum a, PyNum b);
/* Direct timing consumption: preserve int/float, validate range, note floats. */
bool pynum_timing(PyNum value, const char *site, PyNum *out);
bool pynum_timing_once(PyNum value, const char *site, bool *range_noted, PyNum *out);
bool pynum_add(PyNum a, PyNum b, const char *site, PyNum *out);
bool pynum_sub(PyNum a, PyNum b, const char *site, PyNum *out);
bool pynum_mul(PyNum a, PyNum b, const char *site, PyNum *out);
bool pynum_floordiv(PyNum a, PyNum b, const char *site, PyNum *out);
bool pynum_epoch_ms(PyNum value, bool milliseconds, const char *site, int64_t *out);
bool pynum_epoch_ms_once(PyNum value, bool milliseconds, const char *site, bool *range_noted,
                         int64_t *out);
/* Exact Decimal(repr(seconds))*1000 comparison, before truncation. Pure: does
 * not emit timing events or reject finite magnitudes outside ms range. */
bool pynum_epoch_compare(PyNum seconds, int64_t milliseconds, int *order);
#endif
