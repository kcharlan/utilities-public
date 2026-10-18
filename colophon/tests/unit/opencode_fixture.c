#define _DARWIN_C_SOURCE
#include "opencode_fixture.h"
#include "runner.h"
#include "util/fileio.h"
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
void opencode_fixture_sql(OpencodeFixture *f, const char *sql) {
    int rc=sqlite3_exec(f->writer,sql,NULL,NULL,NULL);
    if(rc!=SQLITE_OK) fprintf(stderr,"synthetic fixture SQL: %s\n",sqlite3_errmsg(f->writer));
    ASSERT_EQ(SQLITE_OK,rc);
}
void opencode_fixture_open(OpencodeFixture *f) {
    memset(f,0,sizeof *f);
    const char *scratch=getenv("TMPDIR");ASSERT_TRUE(scratch&&scratch[0]);
    int length=snprintf(f->home,sizeof f->home,"%s/opencode-unit.XXXXXX",scratch);
    ASSERT_TRUE(length>0&&(size_t)length<sizeof f->home);
    ASSERT_TRUE(mkdtemp(f->home)); snprintf(f->path,sizeof f->path,"%s/synthetic.db",f->home);
    ASSERT_EQ(SQLITE_OK,sqlite3_open(f->path,&f->writer));
    char *sql=NULL;size_t size=0;
    ASSERT_EQ(ERR_OK,file_read_all("tests/fixtures/opencode/schema_v2.sql",&sql,&size).code);
    opencode_fixture_sql(f,sql); free(sql);
    opencode_fixture_sql(f,"INSERT INTO migration VALUES ('20261010180456_project_time_archived',1);"
        "INSERT INTO project VALUES ('synthetic-project','/synthetic/work',1,2,NULL)");
}
void opencode_fixture_session(OpencodeFixture *f,const char *id) {
    char *sql=sqlite3_mprintf("INSERT INTO session_v2 (id,project_id,directory,title,version,time_created,time_updated) VALUES (%Q,'synthetic-project','/synthetic/work','Synthetic title','synthetic-version',1000,9000)",id);
    ASSERT_TRUE(sql);opencode_fixture_sql(f,sql);sqlite3_free(sql);
}
void opencode_fixture_message(OpencodeFixture *f,const char *id,const char *session,const char *type,int seq,const char *json) {
    sqlite3_stmt *st=NULL;
    ASSERT_EQ(SQLITE_OK,sqlite3_prepare_v2(f->writer,"INSERT INTO session_message VALUES (?,?,?,?,2000,2000,?)",-1,&st,NULL));
    sqlite3_bind_text(st,1,id,-1,SQLITE_STATIC);sqlite3_bind_text(st,2,session,-1,SQLITE_STATIC);
    sqlite3_bind_text(st,3,type,-1,SQLITE_STATIC);sqlite3_bind_int(st,4,seq);sqlite3_bind_text(st,5,json,-1,SQLITE_STATIC);
    ASSERT_EQ(SQLITE_DONE,sqlite3_step(st));ASSERT_EQ(SQLITE_OK,sqlite3_finalize(st));
}
void opencode_fixture_close(OpencodeFixture *f) {
    if(f->writer) ASSERT_EQ(SQLITE_OK,sqlite3_close(f->writer));
    char path[300];const char *suffixes[]={"","-wal","-shm","-journal"};
    for(size_t i=0;i<4;i++){snprintf(path,sizeof path,"%s%s",f->path,suffixes[i]);unlink(path);}
    ASSERT_EQ(0,rmdir(f->home));memset(f,0,sizeof *f);
}
