#define _DARWIN_C_SOURCE
#include "antigravity_fixture.h"
#include "runner.h"
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>
void antigravity_fixture_sql(AntigravityFixture *f,const char *sql){ASSERT_EQ(SQLITE_OK,sqlite3_exec(f->writer,sql,NULL,NULL,NULL));}
void antigravity_fixture_open(AntigravityFixture *f){
    *f=(AntigravityFixture){0};const char *tmp=getenv("TMPDIR");ASSERT_TRUE(tmp&&*tmp);
    snprintf(f->home,sizeof f->home,"%s/antigravity-unit.XXXXXX",tmp);ASSERT_TRUE(mkdtemp(f->home));
    char directory[512];snprintf(directory,sizeof directory,"%s/antigravity",f->home);ASSERT_EQ(0,mkdir(directory,0700));
    snprintf(directory,sizeof directory,"%s/antigravity/conversations",f->home);ASSERT_EQ(0,mkdir(directory,0700));
    snprintf(f->path,sizeof f->path,"%s/" AG_SYNTHETIC_ID ".db",directory);ASSERT_EQ(SQLITE_OK,sqlite3_open(f->path,&f->writer));
    antigravity_fixture_sql(f,"CREATE TABLE trajectory_meta(trajectory_id,cascade_id,trajectory_type,source);CREATE TABLE trajectory_metadata_blob(id,data);CREATE TABLE steps(idx,step_type,status,metadata,step_payload,step_format);CREATE TABLE gen_metadata(idx,data)");
}
void antigravity_fixture_annotation(AntigravityFixture *f,const char *bytes){
    char path[512];snprintf(path,sizeof path,"%s/antigravity/annotations",f->home);ASSERT_EQ(0,mkdir(path,0700));
    snprintf(path,sizeof path,"%s/antigravity/annotations/" AG_SYNTHETIC_ID ".pbtxt",f->home);FILE *out=fopen(path,"w");ASSERT_TRUE(out);ASSERT_EQ(strlen(bytes),fwrite(bytes,1,strlen(bytes),out));ASSERT_EQ(0,fclose(out));
}
void antigravity_fixture_summary(AntigravityFixture *f,const char *sql){
    char path[512];snprintf(path,sizeof path,"%s/antigravity/conversation_summaries.db",f->home);sqlite3 *db=NULL;ASSERT_EQ(SQLITE_OK,sqlite3_open(path,&db));ASSERT_EQ(SQLITE_OK,sqlite3_exec(db,sql,NULL,NULL,NULL));ASSERT_EQ(SQLITE_OK,sqlite3_close(db));
}
void antigravity_fixture_read(AntigravityFixture *f,AntigravityStore *s){
    Args args={.antigravity_home=f->home};ASSERT_EQ(ERR_OK,antigravity_discover(&args,s).code);ASSERT_EQ(ERR_OK,antigravity_store_read(s,NULL).code);
}
void antigravity_fixture_close(AntigravityFixture *f){
    if(f->writer)ASSERT_EQ(SQLITE_OK,sqlite3_close(f->writer));
    char path[600];const char *suffix[]={"","-wal","-shm","-journal"};for(size_t i=0;i<4;i++){snprintf(path,sizeof path,"%s%s",f->path,suffix[i]);unlink(path);}
    snprintf(path,sizeof path,"%s/antigravity/annotations/" AG_SYNTHETIC_ID ".pbtxt",f->home);unlink(path);
    snprintf(path,sizeof path,"%s/antigravity/annotations",f->home);rmdir(path);
    snprintf(path,sizeof path,"%s/antigravity/conversation_summaries.db",f->home);unlink(path);
    snprintf(path,sizeof path,"%s/antigravity/conversations",f->home);ASSERT_EQ(0,rmdir(path));
    snprintf(path,sizeof path,"%s/antigravity",f->home);ASSERT_EQ(0,rmdir(path));ASSERT_EQ(0,rmdir(f->home));
}
