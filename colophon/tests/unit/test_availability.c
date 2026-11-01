#define _DARWIN_C_SOURCE
#include "runner.h"
#include "parse/reader.h"
#include "parse/record.h"

#include "scan/discover.h"
#include "opencode/db.h"
#include "opencode_fixture.h"
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

TEST(reader_limits_suffix_recovery_attempts) {
    char input[1024] = "broken";
    for (int i=0;i<16;i++) strcat(input,"{\"type\":");
    strcat(input,"{\"type\":\"synthetic\"}");
    DecodedLine decoded={0};
    ASSERT_EQ(ERR_OK,reader_decode((Str){input,(uint32_t)strlen(input)},true,&decoded).code);
    ASSERT_EQ(LINE_MALFORMED,decoded.status);
    json_read_free(&decoded.json);
}
TEST(reader_line_size_boundary_is_a_per_log_io_failure) {
    ASSERT_EQ(ERR_OK,reader_check_line_size(UINT32_MAX-1,1).code);
    ASSERT_EQ(ERR_IO,reader_check_line_size(UINT32_MAX-1,2).code);
    ASSERT_EQ(ERR_IO,reader_check_line_size((size_t)UINT32_MAX+1,0).code);
}
TEST(reader_rejects_short_frozen_snapshot) {
    char path[]="/tmp/colophon-short-XXXXXX";int fd=mkstemp(path);ASSERT_TRUE(fd>=0);
    ASSERT_EQ(3,write(fd,"abc",3));
    DiscoveredLog snapshot={.path={path,(uint32_t)strlen(path)},.size=10};ReaderResult result={0};
    ASSERT_EQ(ERR_IO,reader_read_fd(fd,&snapshot,NULL,&result).code);
    reader_result_destroy(&result);close(fd);unlink(path);
}
TEST(discovery_excludes_fifo_logs) {
    char dir[]="/tmp/colophon-fifo-XXXXXX";ASSERT_TRUE(mkdtemp(dir));
    char sessions[256],path[300];snprintf(sessions,sizeof sessions,"%s/sessions",dir);ASSERT_EQ(0,mkdir(sessions,0700));
    snprintf(path,sizeof path,"%s/synthetic.jsonl",sessions);ASSERT_EQ(0,mkfifo(path,0600));
    Discovery d={0};ASSERT_EQ(ERR_OK,discover_logs(dir,&d).code);ASSERT_EQ(0,d.count);
    discovery_destroy(&d);unlink(path);rmdir(sessions);rmdir(dir);
}
TEST(opencode_connection_disables_trusted_schema) {
    OpencodeFixture f;opencode_fixture_open(&f);sqlite3 *db=NULL;int enabled=-1;
    ASSERT_EQ(ERR_OK,opencode_db_open(f.path,&db).code);
    ASSERT_EQ(SQLITE_OK,sqlite3_db_config(db,SQLITE_DBCONFIG_TRUSTED_SCHEMA,-1,&enabled));
    ASSERT_EQ(0,enabled);
    ASSERT_EQ(SQLITE_OK,sqlite3_db_config(db,SQLITE_DBCONFIG_DEFENSIVE,-1,&enabled));
    ASSERT_EQ(1,enabled);sqlite3_close(db);opencode_fixture_close(&f);
}

TEST(reader_rejects_fifo_without_blocking) {
    char dir[]="/tmp/colophon-pipe-XXXXXX";ASSERT_TRUE(mkdtemp(dir));
    char path[256];snprintf(path,sizeof path,"%s/synthetic.jsonl",dir);ASSERT_EQ(0,mkfifo(path,0600));
    pid_t child=fork();ASSERT_TRUE(child>=0);
    if(!child){alarm(2);DiscoveredLog log={.path={path,(uint32_t)strlen(path)}};ReaderResult result={0};
        Err e=reader_read_log(&log,NULL,&result);reader_result_destroy(&result);_exit(e.code==ERR_IO?0:1);}
    int status=0;ASSERT_EQ(child,waitpid(child,&status,0));ASSERT_TRUE(WIFEXITED(status));ASSERT_EQ(0,WEXITSTATUS(status));
    unlink(path);rmdir(dir);
}

static Err truncate_log(void *context) {
    return ftruncate(*(int *)context,0) ? err_make(ERR_IO,"test truncate failed") : ERR_SUCCESS;
}
TEST(reader_rejects_shrink_after_fingerprint) {
    char path[]="/tmp/colophon-shrink-XXXXXX";int fd=mkstemp(path);ASSERT_TRUE(fd>=0);
    ASSERT_EQ(3,write(fd,"abc",3));DiscoveredLog log={.path={path,(uint32_t)strlen(path)},.size=3};
    ReaderCallbacks callbacks={.context=&fd,.chunk=truncate_log};ReaderResult result={0};
    ASSERT_EQ(ERR_IO,reader_read_fd(fd,&log,&callbacks,&result).code);
    reader_result_destroy(&result);close(fd);unlink(path);
}

TEST(record_scalar_rejects_nonfinite_metadata) {
    JsonRead input=json_read(STR_LIT("Infinity"),BYTES,JSON_CONSTANTS_ALLOW,"synthetic");
    ASSERT_EQ(JSON_OK,input.status);LogRecord record={0};JScalar scalar={0};
    ASSERT_EQ(ERR_OK,record_scalar(&record,yyjson_doc_get_root(input.doc),"synthetic",&scalar).code);
    ASSERT_EQ(JS_NULL,scalar.kind);json_read_free(&input);
}
