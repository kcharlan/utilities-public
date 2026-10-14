#include "tracker.h"

bool tracker_seen(const TotalsTracker *t, Totals total) {
  for (size_t i = 0; i < t->count; i++)
    if (totals_equal(&t->seen[(t->start + i) % TOTALS_SEEN_LIMIT], &total))
      return true;
  return false;
}
void tracker_latch(TotalsTracker *t, Totals total) {
  if (t->has_watermark && !totals_at_least(total, t->watermark))
    t->saw_interleaved = true;
}
void tracker_raise(TotalsTracker *t, Totals total) {
  t->watermark = totals_max(t->has_watermark ? &t->watermark : NULL, total);
  t->has_watermark = true;
  totals_note_state(t->watermark, "accounting.tracker.watermark");
}
void tracker_commit(TotalsTracker *t, Totals total) {
  tracker_raise(t, total);
  if (tracker_seen(t, total))
    return;
  if (t->count == TOTALS_SEEN_LIMIT) {
    t->start = (t->start + 1) % TOTALS_SEEN_LIMIT;
    t->count--;
  }
  t->seen[(t->start + t->count++) % TOTALS_SEEN_LIMIT] = total;
  totals_note_state(total, "accounting.tracker.seen_raw_totals[*]");
}
Totals snapshot_apply(SnapshotAccumulator *a, const Totals *last,
                      const Totals *total) {
  /* Python Totals are immutable: preserve event values when callers borrow
   * inputs from accumulator fields that this operation updates. */
  Totals last_value = last ? *last : (Totals){0};
  Totals total_value = total ? *total : (Totals){0};
  if (last)
    last = &last_value;
  if (total)
    total = &total_value;
  if (!a->has_counted && total && last) {
    a->counted = totals_delta(last, *total);
    a->has_counted = true;
    totals_note_state(a->counted, "accounting.snapshot.counted_totals");
  }
  bool has_reasoning =
      (last && last->reasoning.present) || (total && total->reasoning.present);
  Totals base =
      a->has_counted ? a->counted : (Totals){0, 0, 0, {has_reasoning, 0}};
  const Totals *water = a->tracker.has_watermark ? &a->tracker.watermark
                        : a->has_raw_baseline    ? &a->raw_baseline
                                                 : NULL;
  if (total) {
    if (tracker_seen(&a->tracker, *total))
      return base;
    if (water &&
        totals_stale_regression(*total, *water, last ? *last : (Totals){0}))
      return base;
    tracker_latch(&a->tracker, *total);
  }
  if (!last && !total)
    return base;
  Totals delta;
  if (last) {
    delta = *last;
    if (total) {
      if (a->tracker.saw_interleaved)
        delta = totals_post_latch_delta(
            water, a->has_counted ? &a->counted : NULL, *total, last);
      else {
        Totals td = totals_delta(water, *total);
        if (totals_prefer_delta(water, *total, td, *last, a->saw_divergent))
          delta = td;
      }
    }
  } else if (a->tracker.saw_interleaved)
    delta = totals_contained_delta(water, a->has_counted ? &a->counted : NULL,
                                   *total);
  else if (a->saw_divergent)
    delta = totals_divergent_delta(water, a->has_counted ? &a->counted : NULL,
                                   *total);
  else
    delta = totals_delta(water, *total);
  a->counted = totals_add(base, delta);
  a->has_counted = true;
  totals_note_state(a->counted, "accounting.snapshot.counted_totals");
  a->raw_baseline = total ? *total : a->counted;
  a->has_raw_baseline = true;
  totals_note_state(a->raw_baseline, "accounting.snapshot.raw_totals_baseline");
  if (total) {
    if (!totals_equal(total, &a->counted))
      a->saw_divergent = true;
    tracker_commit(&a->tracker, *total);
  } else
    tracker_raise(&a->tracker, a->counted);
  return a->counted;
}
