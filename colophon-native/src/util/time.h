#ifndef CP_TIME_H
#define CP_TIME_H
#include "str.h"
#include <stdbool.h>
#include <stdint.h>
/* False is an absent/invalid value; output is unchanged. trusted_site is schema,
 * never user data. Out-of-range results note tier2_time once. */
bool time_parse_rfc3339(Str text, const char *trusted_site, int64_t *ms);
/* Same parser, additionally classifies valid grammar past the supported year. */
bool time_parse_rfc3339_status(Str text, const char *trusted_site, int64_t *ms, bool *past_year_limit);
bool time_day_key(Str text, const char *trusted_site, char day[11], int64_t *ms);
bool time_day_key_iso(Str text, const char *trusted_site, char day[11], int64_t *ms);
/* Retained Codex accounting native date branch (year>=1900, T, <=9 digits).
 * Historical ICU inputs take the approved absent path. No local day conversion. */
bool time_codex_timestamp(Str text,const char *trusted_site,int64_t *ms);
bool time_round_swift_ms(double seconds, const char *trusted_site, int64_t *ms);
/* Integer milliseconds never pass through double. The double helper accepts
 * an already-scaled millisecond result, not epoch seconds or JSON lexemes. */
bool time_ms_from_i64(int64_t value, bool milliseconds, const char *trusted_site, int64_t *ms);
/* A caller-owned ticket is scoped to one consumed field occurrence. */
bool time_ms_from_i64_once(int64_t value, bool milliseconds, const char *trusted_site,
                           bool *range_noted, int64_t *ms);
bool time_truncate_ms(double scaled_ms, const char *trusted_site, int64_t *ms);
bool time_format_rfc3339(int64_t milliseconds,char output[21]);
#endif
