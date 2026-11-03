#define _DARWIN_C_SOURCE
#include "runner.h"
#include "price/ledger.h"
#include "util/fileio.h"
#include "util/json_read.h"
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>

#define ENTRY "{\"model\":\"synthetic-ledger\",\"effective_from\":\"2026-01-02T00:00:00Z\",\"source\":\"manual\",\"per_million\":{\"input\":1,\"cached_input\":0.5,\"cache_write\":0,\"output\":2}}"
#define ORIGINAL "{\"schema\":1,\"entries\":[" ENTRY "]}"
static void ledger_fixture(char *path, size_t size, struct stat *st) {
    char home[1024];snprintf(home,sizeof home,"%s/synthetic-ledger-XXXXXX",getenv("COLOPHON_HOME"));
    ASSERT_TRUE(mkdtemp(home));snprintf(path,size,"%s/price-history.json",home);
    FILE *f=fopen(path,"wb");ASSERT_TRUE(f);ASSERT_TRUE(fputs(ORIGINAL,f)>=0);ASSERT_EQ(0,fclose(f));
    ASSERT_EQ(0,chmod(path,0600));ASSERT_EQ(0,stat(path,st));
}
static int64_t ledger_clock(struct stat *st) {return (int64_t)st->st_mtimespec.tv_sec*1000000000+st->st_mtimespec.tv_nsec;}
static void append_case(const char *fault) {
    char path[1100];struct stat st;ledger_fixture(path,sizeof path,&st);
    JsonRead entries=json_read(STR_LIT("[{\"model\":\"synthetic-second\",\"effective_from\":\"2026-01-03T00:00:00Z\",\"source\":\"manual\",\"per_million\":{\"input\":3,\"cached_input\":1,\"cache_write\":0,\"output\":5}}]"),STRICT,JSON_CONSTANTS_REJECT,"test.ledger.entries");
    ASSERT_EQ(JSON_OK,entries.status);LedgerAppend append={0};
    if(fault)ASSERT_EQ(0,setenv("COLOPHON_TEST_FAULT",fault,1));
    Err e=append_user_ledger(path,yyjson_doc_get_root(entries.doc),true,ledger_clock(&st),&append);
    if(fault)ASSERT_EQ(0,unsetenv("COLOPHON_TEST_FAULT"));
    ASSERT_EQ(ERR_OK,e.code);char *bytes=NULL;size_t n=0;ASSERT_EQ(ERR_OK,file_read_all(path,&bytes,&n).code);
    if(fault) {
        ASSERT_FALSE(append.appended);ASSERT_EQ(strlen(ORIGINAL),n);ASSERT_TRUE(!memcmp(bytes,ORIGINAL,n));
        if(!strcmp(fault,"append_ledger_reread_edit")) ASSERT_TRUE(str_equal(append.warning,STR_LIT("price-history.json changed during the run; recording skipped")));
        else ASSERT_TRUE(append.warning.n>=39 && !memcmp(append.warning.p,"price-history.json: recording skipped: ",39));
    } else {
        ASSERT_TRUE(append.appended);ASSERT_EQ(0,stat(path,&st));ASSERT_EQ(0600,st.st_mode & 0777);
        JsonRead saved=json_read((Str){bytes,(uint32_t)n},STRICT,JSON_CONSTANTS_REJECT,"test.ledger.saved");
        ASSERT_EQ(JSON_OK,saved.status);LedgerCheck check={0};ASSERT_EQ(ERR_OK,validate_ledger(yyjson_doc_get_root(saved.doc),false,&check).code);
        ASSERT_EQ(0,check.errors.count);ASSERT_EQ(2,check.count);
        ASSERT_TRUE(strstr(bytes,"synthetic-ledger"));ASSERT_TRUE(strstr(bytes,"synthetic-second"));
        ledger_check_destroy(&check);json_read_free(&saved);
    }
    free(bytes);ledger_append_destroy(&append);json_read_free(&entries);
}
TEST(ledger_append_preserves_existing_entries_with_private_mode) {append_case(NULL);}
TEST(ledger_append_skips_when_file_changes_during_run) {append_case("append_ledger_reread_edit");}
TEST(ledger_append_write_failure_is_warning_not_fatal) {append_case("append_ledger");}
TEST(ledger_user_entries_reject_null_effective_from_and_unknown_source) {
    const char *bad="{\"schema\":1,\"entries\":[{\"model\":\"synthetic-ledger\",\"effective_from\":null,\"source\":\"synthetic\",\"per_million\":{\"input\":1,\"cached_input\":0.5,\"cache_write\":0,\"output\":2}}]}";
    JsonRead read=json_read((Str){bad,(uint32_t)strlen(bad)},STRICT,JSON_CONSTANTS_REJECT,"test.ledger.bad");LedgerCheck check={0};
    ASSERT_EQ(JSON_OK,read.status);ASSERT_EQ(ERR_OK,validate_ledger(yyjson_doc_get_root(read.doc),false,&check).code);ASSERT_EQ(2,check.errors.count);
    ledger_check_destroy(&check);json_read_free(&read);
    const char *curated="{\"schema\":1,\"entries\":[{\"model\":\"synthetic-ledger\",\"effective_from\":null,\"source\":\"curated\",\"per_million\":{\"input\":1,\"cached_input\":0.5,\"cache_write\":0,\"output\":2}}]}";
    read=json_read((Str){curated,(uint32_t)strlen(curated)},STRICT,JSON_CONSTANTS_REJECT,"test.ledger.curated");
    ASSERT_EQ(JSON_OK,read.status);ASSERT_EQ(ERR_OK,validate_ledger(yyjson_doc_get_root(read.doc),true,&check).code);ASSERT_EQ(0,check.errors.count);
    ledger_check_destroy(&check);json_read_free(&read);
}
