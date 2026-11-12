#include "runner.h"
#include "util/jobpool.h"
#include "util/events.h"
#include <unistd.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>

typedef struct { size_t next; } Context;
static Err work(size_t i, void *context) {
    (void)context;
    if (!i) usleep(30000);
    return ERR_SUCCESS;
}
static Err collect(size_t i, Err result, void *context) {
    Context *c = context;
    if (i != c->next++) return err_make(ERR_INVALID, "out of order");
    return result;
}
TEST(jobpool_collects_in_index_order) {
    Context c = {0}; JobStats stats = {0};
    ASSERT_EQ(ERR_OK, jobpool_run(8, 8, NULL, work, collect, &c, &stats).code);
    ASSERT_EQ(8, c.next);
    ASSERT_TRUE(stats.engaged > 0 && stats.engaged <= 8);
}
static Err stop_at_two(size_t i, Err result, void *context) {
    Context *c = context;
    c->next++;
    return i == 2 ? err_make(ERR_INVALID, "selected error") : result;
}
TEST(jobpool_stops_collecting_at_first_error) {
    Context c = {0};
    Err e = jobpool_run(8, 8, NULL, work, stop_at_two, &c, NULL);
    ASSERT_EQ(ERR_INVALID, e.code);
    ASSERT_STREQ("selected error", e.message);
    ASSERT_EQ(3, c.next);
}
TEST(jobpool_zero_and_interrupted) {
    Context c = {0}; JobStats stats = {99};
    ASSERT_EQ(ERR_OK, jobpool_run(0, 8, NULL, work, collect, &c, &stats).code);
    ASSERT_EQ(0, stats.engaged);
    volatile sig_atomic_t flag = 1;
    Err e = jobpool_run(2, 16, &flag, work, collect, &c, &stats);
    ASSERT_EQ(ERR_IO, e.code);
    ASSERT_STREQ("interrupted", e.message);
    ASSERT_EQ(0, c.next);
    ASSERT_TRUE(stats.engaged <= 2);
}
static Err fail_reverse(size_t i, void *context) {
    atomic_bool *second = context;
    if (!i) {
        for (size_t n=0; n<1000 && !atomic_load(second); n++) usleep(1000);
        return atomic_load(second) ? err_make(ERR_INVALID, "first job") : err_make(ERR_IO, "second worker missing");
    }
    atomic_store(second,true);
    return err_make(ERR_NOMEM, "second job");
}
static Err return_result(size_t i, Err result, void *context) {
    (void)i; (void)context; return result;
}
TEST(jobpool_selects_first_error_despite_reverse_completion) {
    atomic_bool second=false;
    Err e=jobpool_run(2,2,NULL,fail_reverse,return_result,&second,NULL);
    ASSERT_EQ(ERR_INVALID,e.code);ASSERT_STREQ("first job",e.message);
}
typedef struct { atomic_bool second; EventCapture captures[2]; } EventJobs;
static Err event_work(size_t i, void *context) {
    EventJobs *jobs=context;
    event_capture_begin(&jobs->captures[i]);
    if (!i) {
        for (size_t n=0;n<1000 && !atomic_load(&jobs->second);n++) usleep(1000);
        if (!atomic_load(&jobs->second)) { event_capture_end(); return err_make(ERR_IO,"second worker missing"); }
        event_note("first","synthetic",2);
    } else { event_note("second","synthetic",3); atomic_store(&jobs->second,true); }
    event_capture_end(); return ERR_SUCCESS;
}
static Err event_collect(size_t i, Err result, void *context) {
    EventJobs *jobs=context; event_capture_replay(&jobs->captures[i]); return result;
}
TEST(jobpool_replays_events_in_order_after_reverse_completion) {
    EventJobs jobs={0};event_flush(NULL);
    char path[1024];snprintf(path,sizeof path,"%s/native-events.jsonl",getenv("COLOPHON_HOME"));unlink(path);
    ASSERT_EQ(ERR_OK,jobpool_run(2,2,NULL,event_work,event_collect,&jobs,NULL).code);
    event_flush(getenv("COLOPHON_HOME"));FILE *f=fopen(path,"r");ASSERT_TRUE(f);
    char line[1024];ASSERT_TRUE(fgets(line,sizeof line,f));ASSERT_TRUE(strstr(line,"\"event\":\"first\""));ASSERT_TRUE(strstr(line,"\"count\":2"));
    ASSERT_TRUE(fgets(line,sizeof line,f));ASSERT_TRUE(strstr(line,"\"event\":\"second\""));ASSERT_TRUE(strstr(line,"\"count\":3"));
    ASSERT_FALSE(fgets(line,sizeof line,f));ASSERT_EQ(0,fclose(f));ASSERT_EQ(0,unlink(path));
}
