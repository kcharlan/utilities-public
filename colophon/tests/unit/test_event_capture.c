#include "runner.h"
#include "util/events.h"
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
TEST(event_capture_replays_only_selected_prefix_in_order) {
    event_flush(NULL);
    char path[1024];
    snprintf(path, sizeof path, "%s/native-events.jsonl", getenv("COLOPHON_HOME"));
    unlink(path);
    EventCapture a = {0}, b = {0}, speculative = {0};
    event_capture_begin(&b); event_note("second", "synthetic", 2); event_capture_end();
    event_capture_begin(&speculative); event_note("discarded", "synthetic", 5); event_capture_end();
    event_capture_begin(&a); event_note("first", "synthetic", 1); event_capture_end();
    event_capture_replay(&a); event_capture_replay(&b); event_capture_destroy(&speculative);
    event_flush(getenv("COLOPHON_HOME"));
    FILE *f = fopen(path, "r"); ASSERT_TRUE(f);
    char line[1024]; ASSERT_TRUE(fgets(line, sizeof line, f)); ASSERT_TRUE(strstr(line, "\"event\":\"first\""));
    ASSERT_TRUE(fgets(line, sizeof line, f)); ASSERT_TRUE(strstr(line, "\"event\":\"second\""));
    ASSERT_FALSE(fgets(line, sizeof line, f));
    ASSERT_EQ(0, fclose(f)); ASSERT_EQ(0, unlink(path));
}
