#define _DARWIN_C_SOURCE
#include "runner.h"
#include "parse/record.h"
#include "scan/scan.h"
#include <sys/sysctl.h>
#include <stdlib.h>
#include <stdio.h>
#include <unistd.h>
static Err stop_second_chunk(void *context) {
    size_t *calls = context;
    return ++*calls == 2 ? err_make(ERR_INVALID,"synthetic chunk cancellation") : ERR_SUCCESS;
}
static Err fail_record_allocation(void *context,const ReaderRecord *record) {
    (void)record;
    return ++*(size_t *)context==4096?err_make(ERR_NOMEM,"synthetic allocation failure"):ERR_SUCCESS;
}
TEST(record_builder_scratch_is_released_after_all_fact_consumers) {
    char path[1024];
    snprintf(path,sizeof path,"%s/synthetic-facts-XXXXXX",getenv("COLOPHON_HOME"));
    int fd=mkstemp(path);ASSERT_TRUE(fd>=0);
    const char line[]="{\"type\":\"world_state\",\"payload\":{}}\n";
    for(size_t i=0;i<8192;i++)ASSERT_EQ(sizeof line-1,write(fd,line,sizeof line-1));
    ASSERT_EQ(0,close(fd));
    Intern ids;ASSERT_EQ(ERR_OK,intern_init(&ids).code);
    DiscoveredLog key={.path={path,(uint32_t)strlen(path)},.size=8192*(sizeof line-1)};
    LogRecord record={0};ASSERT_EQ(ERR_OK,record_parse(&key,&ids,NULL,&record).code);
    ASSERT_EQ(8192,record.reader.physical_lines);
    ASSERT_TRUE(cp_test_arena_capacity(&record.arena)<1024*1024);
    record_destroy(&record);record=(LogRecord){0};
    size_t calls=0;ReaderCallbacks owner={.context=&calls,.record=fail_record_allocation};
    ASSERT_EQ(ERR_NOMEM,record_parse(&key,&ids,&owner,&record).code);
    ASSERT_EQ(4096,calls);ASSERT_TRUE(cp_test_arena_capacity(&record.arena)<1024*1024);
    record_destroy(&record);intern_destroy(&ids);ASSERT_EQ(0,unlink(path));
}
TEST(scan_worker_precedence_default_and_clamp) {
    unsetenv("COLOPHON_TEST_WORKERS");
    long expected;
#ifdef COLOPHON_WORKERS
    expected=COLOPHON_WORKERS;
#else
    int physical=1; size_t n=sizeof physical;
    if (sysctlbyname("hw.perflevel0.physicalcpu",&physical,&n,NULL,0)) physical=1;
    expected=physical;
#endif
    if (expected<1) expected=1;
    if (expected>16) expected=16;
    ASSERT_EQ((size_t)expected,scan_worker_count());
    setenv("COLOPHON_TEST_WORKERS","8",1); ASSERT_EQ(8,scan_worker_count());
    setenv("COLOPHON_TEST_WORKERS","1",1); ASSERT_EQ(1,scan_worker_count());
    setenv("COLOPHON_TEST_WORKERS","100",1); ASSERT_EQ(16,scan_worker_count());
    setenv("COLOPHON_TEST_WORKERS","0",1); ASSERT_EQ((size_t)expected,scan_worker_count());
    setenv("COLOPHON_TEST_WORKERS","bad",1); ASSERT_EQ((size_t)expected,scan_worker_count());
    unsetenv("COLOPHON_TEST_WORKERS");
}
TEST(scan_record_forwards_chunk_cancellation_before_unterminated_line) {
    char path[1024];
    snprintf(path,sizeof path,"%s/synthetic-chunks-XXXXXX",getenv("COLOPHON_HOME"));
    int fd=mkstemp(path); ASSERT_TRUE(fd>=0);
    char *chunk=malloc(1024*1024); ASSERT_TRUE(chunk); memset(chunk,' ',1024*1024);
    ASSERT_EQ(1024*1024,write(fd,chunk,1024*1024));
    ASSERT_EQ(1024*1024,write(fd,chunk,1024*1024));
    free(chunk); ASSERT_EQ(0,close(fd));
    Intern ids; ASSERT_EQ(ERR_OK,intern_init(&ids).code);
    DiscoveredLog key={.path={path,(uint32_t)strlen(path)},.size=2*1024*1024};
    LogRecord record={0}; size_t calls=0;
    ReaderCallbacks callbacks={.context=&calls,.chunk=stop_second_chunk};
    Err e=record_parse(&key,&ids,&callbacks,&record);
    ASSERT_EQ(ERR_INVALID,e.code); ASSERT_STREQ("synthetic chunk cancellation",e.message);
    ASSERT_EQ(2,calls); ASSERT_EQ(0,record.reader.physical_lines);
    record_destroy(&record); intern_destroy(&ids); ASSERT_EQ(0,unlink(path));
}
