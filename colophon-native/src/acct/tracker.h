#ifndef CP_TRACKER_H
#define CP_TRACKER_H
#include "totals.h"
#include <stddef.h>
enum { TOTALS_SEEN_LIMIT = 64 };
typedef struct {
  bool has_watermark, saw_interleaved;
  Totals watermark, seen[TOTALS_SEEN_LIMIT];
  size_t start, count;
} TotalsTracker;
typedef struct {
  bool has_counted, has_raw_baseline, saw_divergent;
  Totals counted, raw_baseline;
  TotalsTracker tracker;
} SnapshotAccumulator;
bool tracker_seen(const TotalsTracker *tracker, Totals total);
void tracker_latch(TotalsTracker *tracker, Totals total);
void tracker_raise(TotalsTracker *tracker, Totals total);
void tracker_commit(TotalsTracker *tracker, Totals total);
Totals snapshot_apply(SnapshotAccumulator *accumulator, const Totals *last,
                      const Totals *total);
#endif
