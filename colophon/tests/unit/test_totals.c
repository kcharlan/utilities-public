#define _DARWIN_C_SOURCE
#include "acct/tracker.h"
#include "out/jsonw.h"
#include "runner.h"
#include "util/events.h"
#include "util/json_number.h"
#include "util/json_read.h"
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static Totals t(__int128 i, __int128 c, __int128 o, bool r,
                __int128 reasoning) {
  return (Totals){i, c, o, {r, reasoning}};
}
TEST(totals_optional_null_and_exact_wide_arithmetic) {
  Totals a = t(INT64_MAX, 4, 5, true, 2), b = t(1, 3, 7, false, 0);
  Totals sum = totals_add(a, b);
  ASSERT_TRUE(sum.input == (__int128)INT64_MAX + 1);
  ASSERT_FALSE(sum.reasoning.present);
  ASSERT_TRUE(totals_equal(&a, &(Totals){INT64_MAX, 4, 5, {false, 0}}));
  ASSERT_FALSE(
      totals_optional_add((OptionalTokens){false, 0}, (OptionalTokens){true, 1})
          .present);
  ASSERT_EQ(2,
            totals_optional_max((OptionalTokens){false, 0}, a.reasoning).value);
  ASSERT_EQ(2, totals_delta(NULL, a).reasoning.value);
  ASSERT_FALSE(totals_delta(&b, a).reasoning.present);
  ASSERT_TRUE(totals_stale_regression(t(INT64_MAX - 1, 4, 5, true, 2), a,
                                      t(1, 0, 0, false, 0)));
}
TEST(tracker_fifo_repeat_and_reasoning_latch) {
  TotalsTracker tracker = {0};
  for (int i = 0; i < 64; i++)
    tracker_commit(&tracker, t(i, 0, 0, false, 0));
  tracker_commit(&tracker, t(0, 0, 0, true, 42));
  ASSERT_EQ(64, tracker.count);
  tracker_commit(&tracker, t(64, 0, 0, false, 0));
  Totals zero = t(0, 0, 0, false, 0), one = t(1, 0, 0, false, 0);
  ASSERT_FALSE(tracker_seen(&tracker, zero));
  ASSERT_TRUE(tracker_seen(&tracker, one));
  ASSERT_EQ(1, tracker.seen[tracker.start].input);
  Totals same = t(64, 0, 0, true, 0);
  tracker_latch(&tracker, same);
  ASSERT_FALSE(tracker.saw_interleaved);
  tracker_latch(&tracker, one);
  ASSERT_TRUE(tracker.saw_interleaved);
}
TEST(snapshot_prefix_seen_stale_and_last_only) {
  SnapshotAccumulator accumulator = {0};
  Totals last = t(10, 2, 4, true, 2), total = t(100, 20, 40, true, 20);
  Totals result = snapshot_apply(&accumulator, &last, &total);
  ASSERT_EQ(100, result.input);
  ASSERT_EQ(1, accumulator.tracker.count);
  total.reasoning.value = 1;
  result = snapshot_apply(&accumulator, &last, &total);
  ASSERT_EQ(20, result.reasoning.value);
  ASSERT_EQ(1, accumulator.tracker.count);
  total = t(99, 20, 40, true, 20);
  result = snapshot_apply(&accumulator, &last, &total);
  ASSERT_EQ(100, result.input);
  ASSERT_EQ(1, accumulator.tracker.count);
  ASSERT_FALSE(accumulator.tracker.saw_interleaved);
  result = snapshot_apply(&accumulator, &last, NULL);
  ASSERT_EQ(110, result.input);
  ASSERT_EQ(110, accumulator.tracker.watermark.input);
  ASSERT_EQ(1, accumulator.tracker.count);
  result = snapshot_apply(&accumulator, NULL, NULL);
  ASSERT_EQ(110, result.input);
}
TEST(snapshot_post_latch_uses_prior_counted_and_sticky_null) {
  SnapshotAccumulator accumulator = {
      .has_counted = true,
      .counted = {200, 0, 0, {false, 0}},
      .tracker = {.has_watermark = true,
                  .watermark = {100, 0, 0, {true, 10}},
                  .saw_interleaved = true}};
  Totals last = t(50, 0, 0, true, 1), total = t(150, 0, 0, true, 11);
  Totals result = snapshot_apply(&accumulator, &last, &total);
  ASSERT_EQ(200, result.input);
  ASSERT_FALSE(result.reasoning.present);
  ASSERT_TRUE(accumulator.saw_divergent);
}
TEST(totals_delta_stale_and_preference_boundaries) {
  Totals cur = t(98, 0, 0, false, 0), prev = t(100, 0, 0, false, 0),
         last = t(1, 0, 0, false, 0);
  ASSERT_TRUE(totals_stale_regression(cur, prev, last));
  cur.input = 97;
  ASSERT_FALSE(totals_stale_regression(cur, prev, last));
  last.input = 2;
  ASSERT_TRUE(totals_stale_regression(cur, prev, last));
  ASSERT_FALSE(totals_stale_regression(cur, prev, (Totals){0}));
  ASSERT_TRUE(totals_prefer_delta(&cur, prev, totals_delta(&cur, prev),
                                  t(3, 0, 0, false, 0), false));
  ASSERT_FALSE(totals_prefer_delta(&cur, prev, totals_delta(&cur, prev),
                                   t(3, 0, 0, false, 0), true));
  ASSERT_FALSE(
      totals_prefer_delta(NULL, prev, totals_delta(NULL, prev), prev, false));
  Totals counted = t(105, 30, 90, true, 30), water = t(100, 40, 80, true, 40),
         current = t(120, 35, 95, true, 35);
  Totals div = totals_divergent_delta(&water, &counted, current);
  Totals cont = totals_contained_delta(&water, &counted, current);
  ASSERT_EQ(20, div.input);
  ASSERT_EQ(5, div.cached);
  ASSERT_EQ(15, div.output);
  ASSERT_EQ(15, cont.input);
  ASSERT_EQ(5, cont.cached);
  ASSERT_EQ(5, cont.output);
  ASSERT_EQ(5, cont.reasoning.value);
  ASSERT_FALSE(
      totals_contained_delta(NULL, &counted, current).reasoning.present);
}
TEST(totals_reasoning_regression_and_optional_branches) {
  Totals previous = t(100, 0, 10, true, 10), current = t(100, 0, 10, true, 9);
  TotalsTracker tracker = {.has_watermark = true, .watermark = previous};
  tracker_latch(&tracker, current);
  ASSERT_FALSE(tracker.saw_interleaved);
  ASSERT_TRUE(totals_stale_regression(current, previous, t(1, 0, 0, false, 0)));
  ASSERT_TRUE(totals_equal(&current, &previous));
  ASSERT_TRUE(totals_equal(NULL, NULL));
  ASSERT_FALSE(totals_equal(NULL, &current));
  OptionalTokens absent = {0}, five = {true, 5}, ten = {true, 10};
  ASSERT_FALSE(totals_optional_min(absent, five).present);
  ASSERT_FALSE(totals_optional_max(absent, absent).present);
  ASSERT_EQ(5, totals_optional_max(five, absent).value);
  ASSERT_EQ(0, totals_optional_subtract(five, ten).value);
  ASSERT_EQ(5, totals_optional_delta(absent, five, false).value);
  ASSERT_FALSE(totals_optional_delta(absent, five, true).present);
  ASSERT_FALSE(totals_optional_divergent(absent, five, ten).present);
  ASSERT_EQ(0, totals_optional_contained(five, ten, five).value);
}
TEST(snapshot_input_values_survive_aliasing_state_update) {
  SnapshotAccumulator a = {
      .has_counted = true,
      .counted = {50, 0, 0, {false, 0}},
      .tracker = {.has_watermark = true, .watermark = {20, 0, 0, {false, 0}}}};
  Totals last = t(10, 0, 0, false, 0);
  Totals result = snapshot_apply(&a, &last, &a.counted);
  ASSERT_EQ(60, result.input);
  ASSERT_EQ(50, a.raw_baseline.input);
  ASSERT_TRUE(a.saw_divergent);
  ASSERT_EQ(50, a.tracker.seen[a.tracker.start].input);
}
TEST(tracker_wide_scalar_events_once_before_repeated_formatting) {
  event_flush(NULL);
  TotalsTracker tracker = {0};
  Totals raw = t(INT64_MAX, 0, 0, true, INT64_MAX);
  Totals wide = totals_add(raw, raw);
  tracker_commit(&tracker, wide);
  JsonWriter writer = {0};
  for (int i = 0; i < 3; i++) {
    jsonw_i128(&writer, tracker.watermark.input);
    jsonw_free(&writer);
  }
  char directory[] = "/tmp/colophon-totals-events.XXXXXX";
  ASSERT_TRUE(mkdtemp(directory));
  event_flush(directory);
  char path[128];
  snprintf(path, sizeof path, "%s/native-events.jsonl", directory);
  FILE *file = fopen(path, "r");
  ASSERT_TRUE(file);
  const char *sites[] = {"accounting.tracker.watermark.input",
                         "accounting.tracker.watermark.reasoning",
                         "accounting.tracker.seen_raw_totals[*].input",
                         "accounting.tracker.seen_raw_totals[*].reasoning"};
  char line[512];
  for (size_t i = 0; i < 4; i++) {
    ASSERT_TRUE(fgets(line, sizeof line, file));
    JsonRead parsed = json_read((Str){line, (uint32_t)strlen(line)}, BYTES,
                                JSON_CONSTANTS_REJECT, "test.events");
    ASSERT_EQ(JSON_OK, parsed.status);
    yyjson_val *event = yyjson_doc_get_root(parsed.doc);
    ASSERT_STREQ("int128_state",
                 yyjson_get_str(yyjson_obj_get(event, "event")));
    ASSERT_STREQ(sites[i], yyjson_get_str(yyjson_obj_get(event, "site")));
    PyNum count;
    ASSERT_TRUE(json_number(yyjson_obj_get(event, "count"), "test.events.count",
                            &count));
    ASSERT_EQ(1, count.i);
    json_read_free(&parsed);
  }
  ASSERT_FALSE(fgets(line, sizeof line, file));
  fclose(file);
  ASSERT_EQ(0, unlink(path));
  ASSERT_EQ(0, rmdir(directory));
}
