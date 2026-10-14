#define _DARWIN_C_SOURCE
#include "runner.h"
#include "util/time.h"
#include "util/events.h"
#include "util/fileio.h"
#include <limits.h>
#include <math.h>
#include <stdlib.h>
#include <time.h>
#include <stdio.h>
#include <unistd.h>

TEST(cli_original_timestamp_and_epoch_helpers) {
    int64_t ms;char output[21];
    const char *instants[]={"2030-01-15T12:00:00.123Z","2030-01-15T14:00:00.123+02:00"};
    for(size_t i=0;i<2;i++){ASSERT_TRUE(time_parse_rfc3339((Str){instants[i],(uint32_t)strlen(instants[i])},"test.time",&ms));ASSERT_EQ(INT64_C(1894708800123),ms);}
    const char *invalid[]={"invalid","2030-01-15T12:00:00","2030-02-30T12:00:00Z",
        "2030-01-15T12:00:00+00:60","2030-01-15T12:00:00+01:99",
        "2030-01-15T12:00:00-00:60","2030-01-15T12:00:00-01:99",
        "2030-01-15T12:00:00+24:00","2030-01-15T12:00:00-24:00"};
    for(size_t i=0;i<sizeof invalid/sizeof *invalid;i++)ASSERT_FALSE(time_parse_rfc3339((Str){invalid[i],(uint32_t)strlen(invalid[i])},"test.time",&ms));
    int64_t boundary;
    ASSERT_TRUE(time_parse_rfc3339(STR_LIT("2030-01-15T12:00:00+23:59"),"test.time",&ms));
    ASSERT_TRUE(time_parse_rfc3339(STR_LIT("2030-01-14T12:01:00Z"),"test.time",&boundary));ASSERT_EQ(boundary,ms);
    ASSERT_TRUE(time_parse_rfc3339(STR_LIT("2030-01-15T12:00:00-23:59"),"test.time",&ms));
    ASSERT_TRUE(time_parse_rfc3339(STR_LIT("2030-01-16T11:59:00Z"),"test.time",&boundary));ASSERT_EQ(boundary,ms);
    ASSERT_TRUE(time_format_rfc3339(INT64_C(1894708800999),output));ASSERT_STREQ("2030-01-15T12:00:00Z",output);
    ASSERT_TRUE(time_format_rfc3339(0,output));ASSERT_STREQ("1970-01-01T00:00:00Z",output);
    ASSERT_TRUE(time_truncate_ms(1234.567*1000,"test.time",&ms));ASSERT_EQ(1234567,ms);
    ASSERT_TRUE(time_ms_from_i64(1234567,true,"test.time",&ms));ASSERT_EQ(1234567,ms);
    ASSERT_TRUE(time_ms_from_i64(0,false,"test.time",&ms));ASSERT_EQ(0,ms);
    ASSERT_TRUE(time_truncate_ms(-0.001*1000,"test.time",&ms));ASSERT_EQ(-1,ms);
    ASSERT_FALSE(time_truncate_ms(INFINITY,"test.time",&ms));ASSERT_FALSE(time_truncate_ms(NAN,"test.time",&ms));
}

TEST(timestamp_fraction_calendar_and_offsets) {
    int64_t ms;
    ASSERT_TRUE(time_parse_rfc3339(STR_LIT("1969-12-31T23:59:59.9995Z"), "test.time", &ms));
    ASSERT_EQ(-1, ms);
    ASSERT_TRUE(time_parse_rfc3339(STR_LIT("1970-01-01t01:00:00.012345z"), "test.time", &ms));
    ASSERT_EQ(3600012, ms);
    ASSERT_TRUE(time_parse_rfc3339(STR_LIT("1970-01-01T01:00:00+01:00"), "test.time", &ms));
    ASSERT_EQ(0, ms);
    ASSERT_FALSE(time_parse_rfc3339(STR_LIT("2030-02-31T25:61:62Z"), "test.time", &ms));
    ASSERT_TRUE(time_parse_rfc3339(STR_LIT("1970-01-01T24:00:00Z"), "test.time", &ms)); ASSERT_EQ(86400000, ms);
    ASSERT_TRUE(time_parse_rfc3339(STR_LIT("1970-01-01T24:00:00.0000001Z"), "test.time", &ms)); ASSERT_EQ(86400000, ms);
    ASSERT_FALSE(time_parse_rfc3339(STR_LIT("1970-01-01T24:00:00.0001Z"), "test.time", &ms));
    ASSERT_FALSE(time_parse_rfc3339(STR_LIT("1970-01-01T24:01:00Z"), "test.time", &ms));
    ASSERT_FALSE(time_parse_rfc3339(STR_LIT("9999-12-31T24:00:00+01:00"), "test.time", &ms));
    ASSERT_FALSE(time_parse_rfc3339(STR_LIT("1970-01-01T00:00:00+23:60"), "test.time", &ms));
    ASSERT_FALSE(time_parse_rfc3339(STR_LIT("0001-01-01T00:00:00+01:00"), "test.time", &ms));
}
TEST(day_keys_keep_lenient_normalization) {
    setenv("TZ", "UTC", 1); tzset();
    int64_t ms; char day[11];
    ASSERT_TRUE(time_day_key(STR_LIT("2030-02-31T25:61:62Z"), "test.time", day, &ms));
    ASSERT_STREQ("2030-03-04", day);
    ASSERT_EQ(INT64_C(1898820122000), ms);
    ASSERT_TRUE(time_day_key(STR_LIT("1970-01-01 12:34:56Z"), "test.time", day, &ms));
    ASSERT_STREQ("1970-01-01", day); ASSERT_EQ(0, ms);
    ASSERT_TRUE(time_day_key(STR_LIT("1970-01-01T00:00:00.999Z"), "test.time", day, &ms));
    ASSERT_EQ(0, ms);
    ASSERT_FALSE(time_day_key(STR_LIT("1970-01-01T00:00:00+19:00"), "test.time", day, &ms));
    setenv("TZ", "America/New_York", 1); tzset();
    ASSERT_TRUE(time_day_key(STR_LIT("1970-01-01T00:00:00Z"), "test.time", day, &ms));
    ASSERT_STREQ("1969-12-31", day);
    ASSERT_FALSE(time_day_key_iso(STR_LIT("1970-01-01t00:00:00z"), "test.time", day, &ms));
    setenv("TZ", "UTC", 1); tzset();
}
TEST(milliseconds_int64_and_rounding_boundaries) {
    int64_t ms;
    ASSERT_TRUE(time_ms_from_i64(INT64_MAX, true, "test.time", &ms)); ASSERT_EQ(INT64_MAX, ms);
    ASSERT_TRUE(time_ms_from_i64(INT64_MIN, true, "test.time", &ms)); ASSERT_EQ(INT64_MIN, ms);
    ASSERT_FALSE(time_ms_from_i64(INT64_MAX / 1000 + 1, false, "test.time", &ms));
    ASSERT_TRUE(time_ms_from_i64(INT64_MIN / 1000, false, "test.time", &ms));
    ASSERT_FALSE(time_truncate_ms(0x1p63, "test.time", &ms));
    ASSERT_TRUE(time_truncate_ms(-0x1p63, "test.time", &ms)); ASSERT_EQ(INT64_MIN, ms);
    ASSERT_FALSE(time_truncate_ms(NAN, "test.time", &ms));
    ASSERT_TRUE(time_round_swift_ms(0.0005, "test.time", &ms)); ASSERT_EQ(1, ms);
    ASSERT_TRUE(time_round_swift_ms(-0.0005, "test.time", &ms)); ASSERT_EQ(-1, ms);
}
TEST(time_range_telemetry_uses_trusted_sites_once) {
    char root[]="/tmp/colophon-time-events.XXXXXX";ASSERT_TRUE(mkdtemp(root));
    char path[512];snprintf(path,sizeof(path),"%s/native-events.jsonl",root);
    event_flush(root);unlink(path); /* Drain previous unit cases before this batch. */
    int64_t ms=17;
    ASSERT_FALSE(time_parse_rfc3339(STR_LIT("9999-12-31T23:59:59-01:00"),"log.timestamp",&ms));ASSERT_EQ(17,ms);
    ASSERT_FALSE(time_ms_from_i64(INT64_MAX,false,"log.started_at",&ms));ASSERT_EQ(17,ms);
    ASSERT_FALSE(time_truncate_ms(0x1p63,"log.completed_at_ms",&ms));ASSERT_EQ(17,ms);
    ASSERT_FALSE(time_parse_rfc3339(STR_LIT("0001-01-01T00:00:00+01:00"),"log.timestamp",&ms));
    setenv("COLOPHON_TEST_WALL_MS","123",1);event_flush(root);unsetenv("COLOPHON_TEST_WALL_MS");
    char *bytes=NULL;size_t n=0;ASSERT_EQ(ERR_OK,file_read_all(path,&bytes,&n).code);
    ASSERT_STREQ("{\"ts\":123,\"event\":\"tier2_time\",\"site\":\"log.timestamp\",\"count\":1}\n"
                 "{\"ts\":123,\"event\":\"tier2_time\",\"site\":\"log.started_at\",\"count\":1}\n"
                 "{\"ts\":123,\"event\":\"tier2_time\",\"site\":\"log.completed_at_ms\",\"count\":1}\n",bytes);
    free(bytes);unlink(path);rmdir(root);
}
TEST(timestamp_shape_validation_precedes_range_telemetry) {
    char root[]="/tmp/colophon-time-shape.XXXXXX";ASSERT_TRUE(mkdtemp(root));
    char path[512];snprintf(path,sizeof(path),"%s/native-events.jsonl",root);
    event_flush(root);unlink(path);
    int64_t ms=17;
    bool past=true;
    ASSERT_FALSE(time_parse_rfc3339_status(STR_LIT("10000-01-01T00:00:00Z"),"log.timestamp",&ms,&past));ASSERT_FALSE(past);ASSERT_EQ(17,ms);
    ASSERT_FALSE(time_parse_rfc3339(STR_LIT("9999-12-31T24:00:00?"),"log.timestamp",&ms));ASSERT_EQ(17,ms);
    ASSERT_FALSE(time_parse_rfc3339(STR_LIT("9999-12-31T24:00:00+24:00"),"log.timestamp",&ms));ASSERT_EQ(17,ms);
    ASSERT_FALSE(time_parse_rfc3339(STR_LIT("9999-12-31T24:00:00Ztail"),"log.timestamp",&ms));ASSERT_EQ(17,ms);
    ASSERT_TRUE(time_parse_rfc3339(STR_LIT("1970-01-01T00:00:00Z"),"log.timestamp",&ms));ASSERT_EQ(0,ms);
    event_flush(root);ASSERT_EQ(-1,access(path,F_OK));
    ms=17;
    ASSERT_FALSE(time_parse_rfc3339(STR_LIT("9999-12-31T24:00:00Z"),"log.timestamp",&ms));ASSERT_EQ(17,ms);
    setenv("COLOPHON_TEST_WALL_MS","123",1);event_flush(root);unsetenv("COLOPHON_TEST_WALL_MS");
    char *bytes=NULL;size_t n=0;ASSERT_EQ(ERR_OK,file_read_all(path,&bytes,&n).code);
    ASSERT_STREQ("{\"ts\":123,\"event\":\"tier2_time\",\"site\":\"log.timestamp\",\"count\":1}\n",bytes);
    free(bytes);unlink(path);rmdir(root);
}
