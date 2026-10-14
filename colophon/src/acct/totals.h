#ifndef CP_TOTALS_H
#define CP_TOTALS_H
#include <stdbool.h>
/* Raw token components stay int64; all derived accounting values are exact. */
typedef struct {
  bool present;
  __int128 value;
} OptionalTokens;
typedef struct {
  __int128 input, cached, output;
  OptionalTokens reasoning;
} Totals;
OptionalTokens totals_optional_add(OptionalTokens a, OptionalTokens b);
OptionalTokens totals_optional_min(OptionalTokens a, OptionalTokens b);
OptionalTokens totals_optional_max(OptionalTokens a, OptionalTokens b);
OptionalTokens totals_optional_subtract(OptionalTokens value,
                                        OptionalTokens base);
OptionalTokens totals_optional_delta(OptionalTokens base, OptionalTokens cur,
                                     bool has_base);
OptionalTokens totals_optional_divergent(OptionalTokens raw,
                                         OptionalTokens counted,
                                         OptionalTokens cur);
OptionalTokens totals_optional_contained(OptionalTokens water,
                                         OptionalTokens counted,
                                         OptionalTokens cur);
bool totals_equal(const Totals *a, const Totals *b);
bool totals_at_least(Totals a, Totals b);
bool totals_at_most(Totals a, Totals b);
bool totals_stale_regression(Totals cur, Totals prev, Totals last);
bool totals_prefer_delta(const Totals *raw, Totals cur, Totals delta,
                         Totals last, bool saw_divergent);
Totals totals_add(Totals a, Totals b);
Totals totals_min(Totals a, Totals b);
Totals totals_max(const Totals *a, Totals b);
Totals totals_delta(const Totals *base, Totals cur);
Totals totals_divergent_delta(const Totals *raw, const Totals *counted,
                              Totals cur);
Totals totals_contained_delta(const Totals *water, const Totals *counted,
                              Totals cur);
Totals totals_post_latch_delta(const Totals *water, const Totals *counted,
                               Totals cur, const Totals *last);
/* Note each completed wide scalar state once, never from serialization/helpers.
 * site is a fixed schema base path; fixed component suffixes are appended. */
void totals_note_state(Totals total, const char *site);
#endif
