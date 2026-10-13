#include "totals.h"
#include "util/events.h"
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

static __int128 max(__int128 a, __int128 b) { return a > b ? a : b; }
static __int128 min(__int128 a, __int128 b) { return a < b ? a : b; }
static __int128 subtract(__int128 a, __int128 b) { return max(0, a - b); }
static __int128 divergent(__int128 raw, __int128 counted, __int128 cur) {
  return subtract(cur, cur >= raw ? raw : counted);
}
static __int128 contained(__int128 water, __int128 counted, __int128 cur) {
  return subtract(cur, cur >= water ? max(water, counted) : counted);
}
OptionalTokens totals_optional_add(OptionalTokens a, OptionalTokens b) {
  return (OptionalTokens){a.present && b.present,
                          a.present && b.present ? a.value + b.value : 0};
}
OptionalTokens totals_optional_min(OptionalTokens a, OptionalTokens b) {
  return (OptionalTokens){a.present && b.present,
                          a.present && b.present ? min(a.value, b.value) : 0};
}
OptionalTokens totals_optional_max(OptionalTokens a, OptionalTokens b) {
  return !a.present   ? b
         : !b.present ? a
                      : (OptionalTokens){true, max(a.value, b.value)};
}
OptionalTokens totals_optional_subtract(OptionalTokens a, OptionalTokens b) {
  return (OptionalTokens){a.present && b.present,
                          a.present && b.present ? subtract(a.value, b.value)
                                                 : 0};
}
OptionalTokens totals_optional_delta(OptionalTokens base, OptionalTokens cur,
                                     bool has_base) {
  return has_base ? totals_optional_subtract(cur, base) : cur;
}
OptionalTokens totals_optional_divergent(OptionalTokens raw,
                                         OptionalTokens counted,
                                         OptionalTokens cur) {
  bool present = raw.present && counted.present && cur.present;
  return (OptionalTokens){
      present, present ? divergent(raw.value, counted.value, cur.value) : 0};
}
OptionalTokens totals_optional_contained(OptionalTokens water,
                                         OptionalTokens counted,
                                         OptionalTokens cur) {
  bool present = water.present && counted.present && cur.present;
  return (OptionalTokens){
      present, present ? contained(water.value, counted.value, cur.value) : 0};
}
bool totals_equal(const Totals *a, const Totals *b) {
  return !a || !b ? a == b
                  : a->input == b->input && a->cached == b->cached &&
                        a->output == b->output;
}
bool totals_at_least(Totals a, Totals b) {
  return a.input >= b.input && a.cached >= b.cached && a.output >= b.output;
}
bool totals_at_most(Totals a, Totals b) {
  return a.input <= b.input && a.cached <= b.cached && a.output <= b.output;
}
bool totals_stale_regression(Totals cur, Totals prev, Totals last) {
  if (totals_at_least(cur, prev) &&
      !(cur.reasoning.present && prev.reasoning.present &&
        cur.reasoning.value < prev.reasoning.value))
    return false;
  __int128 p = prev.input + prev.cached + prev.output +
               (prev.reasoning.present ? prev.reasoning.value : 0);
  __int128 c = cur.input + cur.cached + cur.output +
               (cur.reasoning.present ? cur.reasoning.value : 0);
  __int128 l = last.input + last.cached + last.output +
               (last.reasoning.present ? last.reasoning.value : 0);
  return p > 0 && c > 0 && l > 0 && (c * 100 >= p * 98 || c + 2 * l >= p);
}
bool totals_prefer_delta(const Totals *raw, Totals cur, Totals delta,
                         Totals last, bool saw_divergent) {
  return !saw_divergent && raw && totals_at_least(cur, *raw) &&
         totals_at_most(delta, last);
}
Totals totals_add(Totals a, Totals b) {
  return (Totals){a.input + b.input, a.cached + b.cached, a.output + b.output,
                  totals_optional_add(a.reasoning, b.reasoning)};
}
Totals totals_min(Totals a, Totals b) {
  return (Totals){min(a.input, b.input), min(a.cached, b.cached),
                  min(a.output, b.output),
                  totals_optional_min(a.reasoning, b.reasoning)};
}
Totals totals_max(const Totals *a, Totals b) {
  return !a ? b
            : (Totals){max(a->input, b.input), max(a->cached, b.cached),
                       max(a->output, b.output),
                       totals_optional_max(a->reasoning, b.reasoning)};
}
Totals totals_delta(const Totals *base, Totals cur) {
  Totals b = base ? *base : (Totals){0};
  return (Totals){
      subtract(cur.input, b.input), subtract(cur.cached, b.cached),
      subtract(cur.output, b.output),
      totals_optional_delta(b.reasoning, cur.reasoning, base != NULL)};
}
Totals totals_divergent_delta(const Totals *raw, const Totals *counted,
                              Totals cur) {
  Totals r = raw ? *raw : (Totals){0}, c = counted ? *counted : (Totals){0};
  return (Totals){
      divergent(r.input, c.input, cur.input),
      divergent(r.cached, c.cached, cur.cached),
      divergent(r.output, c.output, cur.output),
      totals_optional_divergent(r.reasoning, c.reasoning, cur.reasoning)};
}
Totals totals_contained_delta(const Totals *water, const Totals *counted,
                              Totals cur) {
  Totals w = water ? *water : (Totals){0}, c = counted ? *counted : (Totals){0};
  return (Totals){
      contained(w.input, c.input, cur.input),
      contained(w.cached, c.cached, cur.cached),
      contained(w.output, c.output, cur.output),
      totals_optional_contained(w.reasoning, c.reasoning, cur.reasoning)};
}
Totals totals_post_latch_delta(const Totals *water, const Totals *counted,
                               Totals cur, const Totals *last) {
  Totals c = totals_contained_delta(water, counted, cur);
  return last ? totals_min(*last, c) : c;
}
void totals_note_state(Totals t, const char *site) {
  const __int128 values[] = {t.input, t.cached, t.output,
                            t.reasoning.present ? t.reasoning.value : 0};
  const char *fields[] = {"input", "cached", "output", "reasoning"};
  for (size_t i = 0; i < (t.reasoning.present ? 4u : 3u); i++) {
    if (values[i] >= INT64_MIN && values[i] <= INT64_MAX)
      continue;
    /* The base is a literal schema path supplied by the owning assignment.
     * Suffixes are fixed; identifiers, indices and values never enter it. */
    char field_site[128];
    snprintf(field_site, sizeof field_site, "%s.%s", site, fields[i]);
    event_note("int128_state", field_site, 1);
  }
}
