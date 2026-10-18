#define _DARWIN_C_SOURCE
#include "runner.h"
#include "opencode_fixture.h"
#include "opencode/db.h"
#include "opencode/corpus.h"
#include "opencode/compose.h"
#include "out/jsonw.h"

#include "util/fileio.h"
#include <dirent.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
static void add(OpencodeStore *s,OpencodeFixture *f) {
    ASSERT_EQ(ERR_OK,opencode_store_add_database(s,(Str){f->path,(uint32_t)strlen(f->path)},true).code);
}
static void read_store(OpencodeStore *s) { ASSERT_EQ(ERR_OK,opencode_store_read(s,NULL).code); }
static uint64_t count(const Omap *map,const char *key) {
    uint64_t *v=omap_get(map,(Str){key,(uint32_t)strlen(key)});return v?*v:0;
}
static void migration_conversion_oom(bool phase) {
    OpencodeFixture f,good;opencode_fixture_open(&f);opencode_fixture_open(&good);
    /* Rebuild only this synthetic scratch database in UTF-16. A large TEXT
     * value requires a UTF-8 conversion allocation outside SQLite lookaside. */
    ASSERT_EQ(SQLITE_OK,sqlite3_close(f.writer));f.writer=NULL;ASSERT_EQ(0,unlink(f.path));
    ASSERT_EQ(SQLITE_OK,sqlite3_open(f.path,&f.writer));
    opencode_fixture_sql(&f,"PRAGMA encoding='UTF-16le'");
    char *schema=NULL;size_t schema_size=0;
    ASSERT_EQ(ERR_OK,file_read_all("tests/fixtures/opencode/schema_v2.sql",&schema,&schema_size).code);
    opencode_fixture_sql(&f,schema);free(schema);
    char padding[16385];memset(padding,'x',sizeof padding-1);padding[sizeof padding-1]=0;
    char *sql;
    if(phase)sql=sqlite3_mprintf("INSERT INTO migration VALUES ('20261010180456_project_time_archived',1);CREATE TABLE session(id);INSERT INTO kv VALUES ('migration.v1-v2','{\"phase\":\"completed\",\"syntheticPadding\":\"%q\"}',1,1)",padding);
    else sql=sqlite3_mprintf("INSERT INTO migration VALUES ('99999999999999_synthetic_%q',1)",padding);
    ASSERT_TRUE(sql);opencode_fixture_sql(&f,sql);sqlite3_free(sql);
    opencode_fixture_session(&good,"synthetic-good-sibling");
    OpencodeStore control={0};add(&control,&f);read_store(&control);
    ASSERT_EQ(OC_DB_OK,control.databases[0].status);opencode_store_destroy(&control);
    OpencodeStore s={0};add(&s,&f);add(&s,&good);
    ASSERT_EQ(0,setenv("COLOPHON_TEST_FAULT",phase?"opencode.migration.phase.oom":"opencode.migration.id.oom",1));
    Err attempt=opencode_store_read(&s,NULL);
    ASSERT_EQ(0,unsetenv("COLOPHON_TEST_FAULT"));
    ASSERT_EQ(ERR_NOMEM,attempt.code);ASSERT_EQ(0,s.session_count);
    ASSERT_EQ(0,s.databases[1].accepted_sessions);
    opencode_store_destroy(&s);opencode_fixture_close(&f);opencode_fixture_close(&good);
}
TEST(opencode_db_migration_id_conversion_oom_is_fatal) { migration_conversion_oom(false); }
TEST(opencode_db_migration_phase_conversion_oom_is_fatal) { migration_conversion_oom(true); }
TEST(opencode_db_reads_v2_sessions_messages_and_archive) {
    OpencodeFixture f;opencode_fixture_open(&f);opencode_fixture_session(&f,"synthetic-session");
    opencode_fixture_session(&f,"synthetic-orphan-project");
    opencode_fixture_sql(&f,"UPDATE session_v2 SET project_id='synthetic-missing' WHERE id='synthetic-orphan-project';"
       "UPDATE project SET time_archived=8000; UPDATE session_v2 SET time_archived=7000 WHERE id='synthetic-session'");
    opencode_fixture_message(&f,"msg_second","synthetic-session","assistant",2,
       "{\"id\":\"msg_copied_parent\",\"type\":\"assistant\",\"agent\":\"synthetic-agent\",\"model\":{\"id\":\"synthetic-model\",\"providerID\":\"synthetic-provider\"},\"time\":{\"created\":3000,\"completed\":4000},\"content\":[{\"type\":\"text\",\"text\":\"Synthetic \"},{\"type\":\"reasoning\",\"text\":\"ignored\"},{\"type\":\"text\",\"text\":\"answer\"},{\"type\":\"tool\",\"id\":\"synthetic-tool\",\"name\":\"subagent\",\"state\":{\"status\":\"error\",\"metadata\":{\"sessionID\":\"synthetic-child\"}},\"time\":{\"created\":3001,\"ran\":3002,\"completed\":3003}},{\"type\":\"tool\",\"id\":\"synthetic-legacy\",\"name\":\"task\",\"state\":{\"status\":\"completed\",\"metadata\":{\"sessionId\":\"synthetic-old-child\"}},\"time\":{\"created\":3001}}],\"tokens\":{\"input\":11,\"output\":7,\"reasoning\":2,\"cache\":{\"read\":3,\"write\":4}},\"cost\":0.125}");
    opencode_fixture_message(&f,"msg_first","synthetic-session","user",1,
       "{\"id\":\"msg_first\",\"type\":\"user\",\"time\":{\"created\":2001},\"text\":\"Synthetic question\",\"files\":[{\"mime\":\"image/png\"},{\"mime\":\"text/plain\"},{\"mime\":\"image/jpeg\"}]}");
    opencode_fixture_message(&f,"msg_compact","synthetic-session","compaction",3,
       "{\"id\":\"msg_compact\",\"type\":\"compaction\",\"time\":{\"created\":5000},\"status\":\"completed\",\"reason\":\"manual\",\"summary\":\"Synthetic summary\",\"recent\":\"\",\"tokens\":{\"input\":5,\"output\":1},\"cost\":0}");
    OpencodeStore s={0};add(&s,&f);read_store(&s);ASSERT_EQ(2,s.session_count);
    OpencodeSession *r=omap_get(&s.session_ids,STR_LIT("synthetic-session"));ASSERT_TRUE(r);
    ASSERT_TRUE(r->archived&&r->project_archived);ASSERT_EQ(3,r->message_count);
    ASSERT_EQ(OC_MSG_USER,r->messages[0].kind);ASSERT_EQ(2,r->messages[0].images);
    OpencodeMessage *m=&r->messages[1];ASSERT_EQ(OC_MSG_ASSISTANT,m->kind);
    ASSERT_TRUE(str_equal(m->id,STR_LIT("msg_second")));ASSERT_EQ(2000,m->row_created_ms.value);ASSERT_EQ(3000,m->created_ms.value);
    ASSERT_TRUE(str_equal(m->text,STR_LIT("Synthetic answer")));ASSERT_EQ(2,m->tool_count);ASSERT_TRUE(m->tools[0].failed);
    ASSERT_TRUE(str_equal(m->tools[0].child_session_id,STR_LIT("synthetic-child")));
    ASSERT_TRUE(str_equal(m->tools[1].child_session_id,STR_LIT("synthetic-old-child")));
    ASSERT_TRUE(m->tokens_valid&&m->cost_valid);ASSERT_EQ(11,m->tokens.input);ASSERT_EQ(0.125,m->cost);
    ASSERT_EQ(OC_MSG_COMPACTION,r->messages[2].kind);ASSERT_TRUE(r->messages[2].tokens_valid&&r->messages[2].cost_valid);
    ASSERT_EQ(2,s.databases[0].accepted_sessions);ASSERT_EQ(3,s.databases[0].accepted_messages);
    opencode_store_destroy(&s);opencode_fixture_close(&f);
}
TEST(opencode_db_known_types_are_not_unknown) {
    OpencodeFixture f;opencode_fixture_open(&f);opencode_fixture_session(&f,"synthetic-session");
    const char *types[]={"agent-switched","model-switched","location-switched","user","synthetic","system","skill","shell","assistant","compaction","idle"};
    const char *extras[]={"\"agent\":\"synthetic\"","\"model\":{\"id\":\"synthetic\",\"providerID\":\"synthetic\"}","\"location\":{}","\"text\":\"synthetic\"","\"text\":\"synthetic\"","\"text\":\"synthetic\"","\"text\":\"synthetic\",\"skill\":\"synthetic\",\"name\":\"synthetic\"","\"command\":\"synthetic\",\"status\":\"completed\"","\"content\":[],\"model\":{\"id\":\"synthetic\",\"providerID\":\"synthetic\"}","\"status\":\"failed\",\"reason\":\"auto\",\"error\":{\"type\":\"synthetic\",\"message\":\"sensitive omitted\"}","\"outcome\":\"succeeded\""};
    for(int i=0;i<11;i++){char id[64],json[1024];snprintf(id,sizeof id,"msg_synthetic_%d",i);snprintf(json,sizeof json,"{\"id\":\"%s\",\"type\":\"%s\",\"time\":{\"created\":1000},%s}",id,types[i],extras[i]);opencode_fixture_message(&f,id,"synthetic-session",types[i],i,json);}
    opencode_fixture_message(&f,"msg_unknown","synthetic-session","future-synthetic",20,"{}");
    opencode_fixture_message(&f,"msg_bad","synthetic-session","assistant",21,"{bad");
    opencode_fixture_message(&f,"msg_badshape","synthetic-session","user",22,"{\"type\":\"user\"}");
    opencode_fixture_message(&f,"msg_content","synthetic-session","assistant",23,"{\"id\":\"msg_content\",\"type\":\"assistant\",\"content\":[{\"type\":\"future-content\"}],\"time\":{\"created\":1000}}");
    opencode_fixture_message(&f,"msg_badcontent","synthetic-session","assistant",24,"{\"id\":\"msg_badcontent\",\"type\":\"assistant\",\"content\":[{\"text\":\"synthetic\"}],\"time\":{\"created\":1000}}");
    OpencodeStore s={0};add(&s,&f);read_store(&s);ASSERT_EQ(1,s.session_count);
    ASSERT_EQ(12,s.sessions[0]->message_count);ASSERT_EQ(3,s.malformed_messages);
    ASSERT_EQ(1,count(&s.unknown_message_types,"future-synthetic"));ASSERT_EQ(1,s.unknown_message_types.size);
    ASSERT_EQ(1,count(&s.unknown_content_types,"future-content"));ASSERT_FALSE(s.sessions[0]->provenance_complete);
    opencode_store_destroy(&s);opencode_fixture_close(&f);
}
TEST(opencode_db_numeric_validation) {
    OpencodeFixture f;opencode_fixture_open(&f);opencode_fixture_session(&f,"synthetic-session");
    opencode_fixture_sql(&f,"UPDATE session_v2 SET title=NULL,model=NULL,tokens_input='invalid',cost=0.75,time_created='invalid'");
    const char *tokens[]={"{\"input\":4,\"output\":2}","{\"input\":4,\"output\":2,\"reasoning\":null}","{\"input\":4.5,\"output\":2}","{\"input\":9223372036854775808,\"output\":2}","{\"input\":true,\"output\":2}","{\"input\":4,\"output\":2,\"cache\":{\"read\":-1}}","null","{\"input\":9223372036854775807,\"output\":2}","{\"input\":4,\"output\":2}","{}"};
    const char *costs[]={"0.5","0.5","0.5","0.5","0.5","0.5","-1","1e999","true","9223372036854775808"};
    for(int i=0;i<10;i++){char id[64],json[1024];snprintf(id,sizeof id,"msg_numeric_%d",i);snprintf(json,sizeof json,"{\"id\":\"%s\",\"type\":\"assistant\",\"content\":[],\"time\":{\"created\":\"invalid\",\"completed\":-1},\"tokens\":%s,\"cost\":%s}",id,tokens[i],costs[i]);opencode_fixture_message(&f,id,"synthetic-session","assistant",i,json);}
    opencode_fixture_message(&f,"msg_fraction","synthetic-session","assistant",10,"{\"id\":\"msg_fraction\",\"type\":\"assistant\",\"content\":[],\"time\":{\"created\":1000.00000000000001},\"tokens\":{\"input\":9007199254740992.5,\"output\":1},\"cost\":0.5}");
    opencode_fixture_message(&f,"msg_float","synthetic-session","assistant",11,"{\"id\":\"msg_float\",\"type\":\"assistant\",\"content\":[],\"time\":{\"created\":2000},\"tokens\":{\"input\":4.0,\"output\":1},\"cost\":0.5}");
    const char *decimal[]={"9007199254740993.0","9.223372036854775807e18","1e3","1.00000000000000001"};
    for(int i=0;i<4;i++){
        char id[64],json[1024];snprintf(id,sizeof id,"msg_decimal_%d",i);
        snprintf(json,sizeof json,"{\"id\":\"%s\",\"type\":\"assistant\",\"content\":[],\"time\":{\"created\":2000},\"tokens\":{\"input\":%s,\"output\":1},\"cost\":0.5}",id,decimal[i]);
        opencode_fixture_message(&f,id,"synthetic-session","assistant",i+12,json);
    }
    static const struct {const char *value;bool valid;int64_t expected;} scaled[]={
        {"1000e-3",true,1},{"0.001e3",true,1},{"-0.0",true,0},
        {"0e99999999999999999999",true,0},{"1e99999999999999999999",false,0},
        {"1e-99999999999999999999",false,0},{"9.223372036854775808e18",false,0},
        {"1.001e0",false,0},{"0.000000000000000000001e21",true,1}
    };
    for(size_t i=0;i<sizeof scaled/sizeof *scaled;i++){
        char id[64],json[1024];snprintf(id,sizeof id,"msg_scaled_%zu",i);
        snprintf(json,sizeof json,"{\"id\":\"%s\",\"type\":\"assistant\",\"content\":[],\"time\":{\"created\":2000},\"tokens\":{\"input\":%s,\"output\":1},\"cost\":0.5}",id,scaled[i].value);
        opencode_fixture_message(&f,id,"synthetic-session","assistant",(int)i+16,json);
    }
    OpencodeStore s={0};add(&s,&f);read_store(&s);ASSERT_EQ(1,s.session_count);OpencodeSession *r=s.sessions[0];
    ASSERT_FALSE(r->tokens_valid);ASSERT_TRUE(r->cost_valid);ASSERT_EQ(0.75,r->cost);ASSERT_FALSE(r->created_ms.present);ASSERT_FALSE(r->title.p);
    ASSERT_EQ(25,r->message_count);ASSERT_TRUE(r->messages[0].tokens_valid);ASSERT_EQ(0,r->messages[0].tokens.reasoning);
    for(int i=1;i<7;i++)ASSERT_FALSE(r->messages[i].tokens_valid);
    for(int i=0;i<6;i++)ASSERT_TRUE(r->messages[i].cost_valid);
    for(int i=6;i<9;i++)ASSERT_FALSE(r->messages[i].cost_valid);
    ASSERT_TRUE(r->messages[7].tokens_valid);ASSERT_EQ(INT64_MAX,r->messages[7].tokens.input);
    ASSERT_TRUE(r->messages[9].cost_valid);ASSERT_EQ(0x1p63,r->messages[9].cost);
    ASSERT_FALSE(r->messages[10].tokens_valid);ASSERT_TRUE(r->messages[11].tokens_valid);
    ASSERT_TRUE(r->messages[10].cost_valid&&r->messages[11].cost_valid);
    ASSERT_EQ(4,r->messages[11].tokens.input);
    ASSERT_TRUE(r->messages[12].tokens_valid);ASSERT_EQ((__int128)INT64_C(9007199254740993),r->messages[12].tokens.input);
    ASSERT_TRUE(r->messages[13].tokens_valid);ASSERT_EQ(INT64_MAX,r->messages[13].tokens.input);
    ASSERT_TRUE(r->messages[14].tokens_valid);ASSERT_EQ(1000,r->messages[14].tokens.input);
    ASSERT_FALSE(r->messages[15].tokens_valid);
    ASSERT_FALSE(r->messages[10].created_ms.present);
    for(size_t i=0;i<sizeof scaled/sizeof *scaled;i++){
        ASSERT_EQ(scaled[i].valid,r->messages[i+16].tokens_valid);
        if(scaled[i].valid)ASSERT_EQ(scaled[i].expected,r->messages[i+16].tokens.input);
        ASSERT_TRUE(r->messages[i+16].cost_valid);
    }
    ASSERT_FALSE(r->messages[0].created_ms.present);ASSERT_FALSE(r->messages[0].completed_ms.present);ASSERT_TRUE(r->invalid_numbers>0);
    opencode_store_destroy(&s);opencode_fixture_close(&f);
}
TEST(opencode_db_authorizer_denies_credentials) {
    OpencodeFixture f;opencode_fixture_open(&f);opencode_fixture_sql(&f,"CREATE TABLE credential (value TEXT); INSERT INTO credential VALUES ('SYNTHETIC_CREDENTIAL_CANARY'); CREATE TABLE account (value); CREATE TABLE control_account (value)");
    sqlite3 *db=NULL;ASSERT_EQ(ERR_OK,opencode_db_open(f.path,&db).code);ASSERT_TRUE(db);
    ASSERT_EQ(SQLITE_OK,sqlite3_exec(db,"BEGIN;SELECT id FROM project;PRAGMA table_info(session_v2);ROLLBACK",NULL,NULL,NULL));
    const char *denied[]={"SELECT * FROM credential","SELECT * FROM account","SELECT * FROM control_account","ATTACH ':memory:' AS other","UPDATE project SET worktree='synthetic'","PRAGMA user_version","PRAGMA table_info(credential)","PRAGMA journal_mode=WAL"};
    for(size_t i=0;i<sizeof denied/sizeof *denied;i++){ASSERT_TRUE(sqlite3_exec(db,denied[i],NULL,NULL,NULL)!=SQLITE_OK);ASSERT_FALSE(strstr(sqlite3_errmsg(db),"SYNTHETIC_CREDENTIAL_CANARY"));}
    ASSERT_EQ(SQLITE_OK,sqlite3_close(db));opencode_fixture_close(&f);
    /* Exercise SQLite's real allocation failure rather than a reader stub. */
    opencode_fixture_open(&f);
    sqlite3_int64 previous_limit=sqlite3_hard_heap_limit64(1);
    Err attempt=opencode_db_open(f.path,&db);
    sqlite3_hard_heap_limit64(previous_limit);
    ASSERT_EQ(ERR_NOMEM,attempt.code);ASSERT_FALSE(db);
    OpencodeStore s={0};add(&s,&f);
    previous_limit=sqlite3_hard_heap_limit64(1);
    attempt=opencode_store_read(&s,NULL);
    sqlite3_hard_heap_limit64(previous_limit);
    ASSERT_EQ(ERR_NOMEM,attempt.code);ASSERT_EQ(0,s.session_count);
    opencode_store_destroy(&s);opencode_fixture_close(&f);
}
TEST(opencode_db_schema_guards) {
    const char *changes[]={"CREATE TABLE session (id);","CREATE TABLE session (id);INSERT INTO kv VALUES ('migration.v1-v2','{\"phase\":\"sessions\"}',1,1)","CREATE TABLE session (id);INSERT INTO kv VALUES ('migration.v1-v2','broken',1,1)","ALTER TABLE session_v2 DROP COLUMN tokens_output","CREATE TABLE session_v3 (id)","INSERT INTO kv VALUES ('migration.synthetic-future','{}',1,1)","DROP TABLE session_message;DROP TABLE session_v2;CREATE TABLE session (id)","ALTER TABLE project DROP COLUMN time_archived;ALTER TABLE session_v2 DROP COLUMN time_archived;ALTER TABLE session_v2 DROP COLUMN fork_session_id","CREATE TABLE session (id);INSERT INTO kv VALUES ('migration.v1-v2','{\"phase\":\"completed\"}',1,1)","INSERT INTO migration VALUES ('99999999999999_synthetic_future',1)"};
    for(size_t i=0;i<sizeof changes/sizeof *changes;i++){
        OpencodeFixture f;opencode_fixture_open(&f);opencode_fixture_session(&f,"synthetic-session");opencode_fixture_sql(&f,changes[i]);
        OpencodeStore s={0};add(&s,&f);read_store(&s);ASSERT_EQ(1,s.database_count);
        bool ok=i>=7;ASSERT_EQ(ok?OC_DB_OK:OC_DB_UNSUPPORTED,s.databases[0].status);ASSERT_EQ(ok?1:0,s.session_count);
        if(!ok)ASSERT_TRUE(s.databases[0].reason.n);if(i==9)ASSERT_TRUE(s.databases[0].untested);
        opencode_store_destroy(&s);opencode_fixture_close(&f);
    }
    /* This independent contract list prevents an accidentally optional field
     * from passing merely because another required field is still present. */
    static const struct {const char *table,*columns;} required[]={
        {"session_v2","id project_id parent_id directory title version agent model cost tokens_input tokens_output tokens_reasoning tokens_cache_read tokens_cache_write time_created time_updated time_idle idle_outcome"},
        {"session_message","id session_id type seq time_created data"},
        {"project","id"},{"migration","id"},{"kv","key value"}
    };
    for(size_t table=0;table<sizeof required/sizeof *required;table++){
        char columns[512];snprintf(columns,sizeof columns,"%s",required[table].columns);
        char *save=NULL;
        for(char *column=strtok_r(columns," ",&save);column;column=strtok_r(NULL," ",&save)){
            OpencodeFixture f;opencode_fixture_open(&f);opencode_fixture_session(&f,"synthetic-session");
            char sql[2048],select[1024]="";size_t used=0;sqlite3_stmt *st=NULL;
            snprintf(sql,sizeof sql,"PRAGMA table_info(%s)",required[table].table);
            ASSERT_EQ(SQLITE_OK,sqlite3_prepare_v2(f.writer,sql,-1,&st,NULL));
            while(sqlite3_step(st)==SQLITE_ROW){
                const char *name=(const char *)sqlite3_column_text(st,1);
                if(strcmp(name,column))used+=(size_t)snprintf(select+used,sizeof select-used,"%s\"%s\"",used?",":"",name);
            }
            ASSERT_EQ(SQLITE_OK,sqlite3_finalize(st));
            snprintf(sql,sizeof sql,"ALTER TABLE %s RENAME TO synthetic_old;CREATE TABLE %s AS SELECT %s FROM synthetic_old;DROP TABLE synthetic_old",required[table].table,required[table].table,select);
            opencode_fixture_sql(&f,sql);
            OpencodeStore s={0};add(&s,&f);read_store(&s);
            ASSERT_EQ(OC_DB_UNSUPPORTED,s.databases[0].status);ASSERT_EQ(0,s.session_count);
            ASSERT_TRUE(strstr(s.databases[0].reason.p,column));
            opencode_store_destroy(&s);opencode_fixture_close(&f);
        }
    }
}
TEST(opencode_db_deduplication_commits_only_successful_databases) {
    OpencodeFixture bad,good;opencode_fixture_open(&bad);opencode_fixture_open(&good);
    opencode_fixture_session(&bad,"synthetic-shared");opencode_fixture_session(&good,"synthetic-shared");
    opencode_fixture_sql(&bad,"DROP TABLE session_message;CREATE VIEW session_message AS SELECT 1 AS id");
    OpencodeStore s={0};add(&s,&bad);add(&s,&good);read_store(&s);
    ASSERT_EQ(1,s.session_count);ASSERT_TRUE(str_equal(s.sessions[0]->database,(Str){good.path,(uint32_t)strlen(good.path)}));
    ASSERT_EQ(0,s.duplicate_sessions);ASSERT_EQ(0,s.databases[0].accepted_sessions);ASSERT_EQ(1,s.databases[1].accepted_sessions);
    opencode_store_destroy(&s);
    /* Fail after staging facts and diagnostics: neither may leak to siblings. */
    opencode_fixture_sql(&bad,"DROP VIEW session_message;CREATE TABLE session_message (id TEXT PRIMARY KEY,session_id TEXT NOT NULL,type TEXT NOT NULL,seq INTEGER NOT NULL,time_created INTEGER NOT NULL,time_updated INTEGER NOT NULL,data TEXT NOT NULL)");
    opencode_fixture_message(&bad,"msg_bad_unknown","synthetic-shared","synthetic-unknown",1,"{}");
    opencode_fixture_message(&bad,"msg_bad_partial","synthetic-shared","user",2,"{}");
    ASSERT_EQ(0,setenv("COLOPHON_TEST_FAULT","opencode.read.messages:2",1));
    s=(OpencodeStore){0};add(&s,&bad);add(&s,&good);read_store(&s);
    ASSERT_EQ(OC_DB_UNREADABLE,s.databases[0].status);ASSERT_EQ(1,s.session_count);
    ASSERT_EQ(0,s.unknown_message_types.size);ASSERT_EQ(0,s.malformed_messages);ASSERT_EQ(0,s.duplicate_sessions);
    ASSERT_TRUE(str_equal(s.sessions[0]->database,(Str){good.path,(uint32_t)strlen(good.path)}));
    opencode_store_destroy(&s);ASSERT_EQ(0,unsetenv("COLOPHON_TEST_FAULT"));
    s=(OpencodeStore){0};add(&s,&good);add(&s,&good);read_store(&s);ASSERT_EQ(1,s.session_count);ASSERT_EQ(1,s.duplicate_sessions);opencode_store_destroy(&s);
    opencode_fixture_close(&bad);opencode_fixture_close(&good);
}
TEST(opencode_db_lock_and_snapshot) {
    OpencodeFixture f;opencode_fixture_open(&f);opencode_fixture_session(&f,"synthetic-session");
    opencode_fixture_sql(&f,"BEGIN EXCLUSIVE");OpencodeStore s={0};add(&s,&f);read_store(&s);ASSERT_EQ(1,s.database_count);ASSERT_EQ(OC_DB_UNREADABLE,s.databases[0].status);ASSERT_EQ(0,s.session_count);opencode_store_destroy(&s);
    opencode_fixture_sql(&f,"ROLLBACK;PRAGMA journal_mode=WAL;UPDATE session_v2 SET title='Synthetic WAL title'");
    char wal[300];snprintf(wal,sizeof wal,"%s-wal",f.path);char *main_before=NULL,*wal_before=NULL,*after=NULL;size_t main_n=0,wal_n=0,n=0;
    ASSERT_EQ(ERR_OK,file_read_all(f.path,&main_before,&main_n).code);ASSERT_EQ(ERR_OK,file_read_all(wal,&wal_before,&wal_n).code);
    s=(OpencodeStore){0};add(&s,&f);read_store(&s);ASSERT_EQ(1,s.session_count);ASSERT_TRUE(str_equal(s.sessions[0]->title,STR_LIT("Synthetic WAL title")));opencode_store_destroy(&s);
    ASSERT_EQ(ERR_OK,file_read_all(f.path,&after,&n).code);ASSERT_EQ(main_n,n);ASSERT_EQ(0,memcmp(main_before,after,n));free(after);
    ASSERT_EQ(ERR_OK,file_read_all(wal,&after,&n).code);ASSERT_EQ(wal_n,n);ASSERT_EQ(0,memcmp(wal_before,after,n));free(after);free(main_before);free(wal_before);
    opencode_fixture_close(&f);
    opencode_fixture_open(&f);opencode_fixture_sql(&f,"DROP TABLE session_message;DROP TABLE session_v2;DROP TABLE project;DROP TABLE migration;DROP TABLE kv");
    ASSERT_EQ(SQLITE_OK,sqlite3_close(f.writer));f.writer=NULL;FILE *out=fopen(f.path,"wb");ASSERT_TRUE(out);fputs("SYNTHETIC_NOT_A_DATABASE",out);fclose(out);
    s=(OpencodeStore){0};add(&s,&f);read_store(&s);ASSERT_EQ(1,s.database_count);ASSERT_EQ(OC_DB_UNREADABLE,s.databases[0].status);opencode_store_destroy(&s);opencode_fixture_close(&f);
}
static size_t descriptors(void) { DIR *d=opendir("/dev/fd");ASSERT_TRUE(d);size_t n=0;struct dirent *e;while((e=readdir(d)))if(e->d_name[0]!='.')n++;closedir(d);return n; }
TEST(opencode_db_cancellation_and_cleanup) {
    OpencodeFixture f;opencode_fixture_open(&f);opencode_fixture_session(&f,"synthetic-session");size_t before=descriptors();
    for(int i=0;i<16;i++){OpencodeStore s={0};add(&s,&f);volatile sig_atomic_t stop=1;ASSERT_EQ(ERR_IO,opencode_store_read(&s,&stop).code);ASSERT_EQ(0,s.session_count);opencode_store_destroy(&s);ASSERT_EQ(before,descriptors());}
    opencode_fixture_message(&f,"msg_cleanup_unknown","synthetic-session","synthetic-unknown",1,"{}");
    for(int i=0;i<16;i++){OpencodeStore s={0};add(&s,&f);read_store(&s);ASSERT_EQ(1,s.session_count);ASSERT_EQ(1,s.unknown_message_types.size);opencode_store_destroy(&s);ASSERT_EQ(before,descriptors());}
    /* Existing fault infrastructure makes cancellation boundaries deterministic. */
    const char *points[]={"opencode.cancel.sessions","opencode.cancel.progress","opencode.cancel.commit"};
    opencode_fixture_sql(&f,"WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<4000) INSERT INTO session_message SELECT 'msg_synthetic_bulk_'||x,'synthetic-session','synthetic-unknown',x+10,2000,2000,'{}' FROM n");
    for(size_t i=0;i<sizeof points/sizeof *points;i++){
        ASSERT_EQ(0,setenv("COLOPHON_TEST_FAULT",points[i],1));
        OpencodeStore s={0};add(&s,&f);volatile sig_atomic_t stop=0;
        ASSERT_EQ(ERR_IO,opencode_store_read(&s,&stop).code);ASSERT_TRUE(stop);ASSERT_EQ(0,s.session_count);ASSERT_EQ(0,s.unknown_message_types.size);
        opencode_store_destroy(&s);ASSERT_EQ(before,descriptors());ASSERT_EQ(0,unsetenv("COLOPHON_TEST_FAULT"));
    }
    opencode_fixture_sql(&f,"ALTER TABLE session_v2 DROP COLUMN tokens_input");
    for(int i=0;i<16;i++){OpencodeStore s={0};add(&s,&f);read_store(&s);ASSERT_EQ(OC_DB_UNSUPPORTED,s.databases[0].status);opencode_store_destroy(&s);ASSERT_EQ(before,descriptors());}
    opencode_fixture_close(&f);
}

TEST(opencode_db_fragmented_text_has_linear_arena_retention) {
    OpencodeFixture f;opencode_fixture_open(&f);opencode_fixture_session(&f,"synthetic-fragments");
    JsonWriter w={0};jsonw_raw(&w,"{\"id\":\"synthetic-answer\",\"type\":\"assistant\",\"time\":{},\"content\":[");
    char fragment[1025];memset(fragment,'x',1024);fragment[1024]=0;
    const size_t fragments=128,total=fragments*1024;
    for(size_t i=0;i<fragments;i++) {
        if(i)jsonw_raw(&w,",");
        memset(fragment,'a'+i%26,1024);
        jsonw_raw(&w,"{\"type\":\"text\",\"text\":");jsonw_string(&w,(Str){fragment,1024});jsonw_raw(&w,"}");
    }
    jsonw_raw(&w,"]}");ASSERT_EQ(ERR_OK,w.error.code);
    opencode_fixture_message(&f,"synthetic-answer","synthetic-fragments","assistant",1,w.data);jsonw_free(&w);
    OpencodeStore s={0};add(&s,&f);read_store(&s);ASSERT_EQ(1,s.session_count);
    Str answer=s.sessions[0]->messages[0].text;ASSERT_EQ(total,answer.n);
    for(size_t i=0;i<total;i++)ASSERT_EQ('a'+(i/1024)%26,answer.p[i]);
    ASSERT_EQ(0,answer.p[total]);
    ASSERT_TRUE(cp_test_arena_capacity(&s.databases[0].arena)<total*4+131072);
    opencode_store_destroy(&s);opencode_fixture_close(&f);
}

TEST(opencode_db_effective_clocks_reach_corpus_and_usage_without_changing_raw_facts) {
    const char *clocks[]={"{}","{\"created\":-1}","{\"created\":3000}","{}","{\"created\":-1}","{\"created\":3000,\"completed\":4000}","{\"created\":3000}","{}","{\"created\":500}","{\"completed\":4000}"};
    const char *rows[]={"2000","2000","2000","NULL","'invalid'","2000","500","500","2000","2000"};
    const int64_t effective[]={2000,2000,3000,0,0,3000,3000,500,500,2000};
    for(size_t k=0;k<10;k++) {
        OpencodeFixture f;opencode_fixture_open(&f);opencode_fixture_session(&f,"synthetic-clocks");
        /* Nullable synthetic shape exercises absent row facts in structurally
         * compatible databases without weakening the pinned schema fixture. */
        opencode_fixture_sql(&f,"DROP TABLE session_message; CREATE TABLE session_message(id TEXT,session_id TEXT,type TEXT,seq INTEGER,time_created,time_updated,data TEXT)");
        char json[512];snprintf(json,sizeof json,"{\"id\":\"synthetic-user\",\"type\":\"user\",\"time\":%s,\"text\":\"Synthetic request\"}",clocks[k]);
        opencode_fixture_message(&f,"synthetic-user","synthetic-clocks","user",1,json);
        snprintf(json,sizeof json,"{\"id\":\"synthetic-answer\",\"type\":\"assistant\",\"time\":%s,\"content\":[],\"tokens\":{\"input\":1,\"output\":0},\"cost\":0,\"error\":{\"type\":\"aborted\"}}",clocks[k]);
        opencode_fixture_message(&f,"synthetic-answer","synthetic-clocks","assistant",2,json);
        char *sql=sqlite3_mprintf("UPDATE session_message SET time_created=%s",rows[k]);ASSERT_TRUE(sql);opencode_fixture_sql(&f,sql);sqlite3_free(sql);
        if(k>=6)opencode_fixture_sql(&f,"UPDATE session_v2 SET fork_session_id='synthetic-parent'");
        OpencodeStore s={0};Corpus c={0};add(&s,&f);read_store(&s);
        OpencodeSession *raw=s.sessions[0];ASSERT_EQ(2,raw->message_count);
        bool payload_valid=k==2||k==5||k==6||k==8;
        ASSERT_EQ(payload_valid,raw->messages[0].created_ms.present);
        ASSERT_EQ(k!=3&&k!=4,raw->messages[0].row_created_ms.present);
        uint64_t diagnostics=raw->invalid_numbers;
        ASSERT_EQ(ERR_OK,opencode_corpus_add(&s,9000,&c).code);ASSERT_EQ(ERR_OK,opencode_compose(&s,&c).code);
        SessionModel *p=omap_get(&c.sessions,raw->id);ASSERT_TRUE(p);
        ASSERT_EQ(diagnostics,raw->invalid_numbers);ASSERT_EQ(payload_valid,raw->messages[0].created_ms.present);
        if(k==6||k==7) {
            ASSERT_TRUE(raw->messages[0].inherited&&raw->messages[1].inherited);
            ASSERT_EQ(0,p->turn_count);ASSERT_EQ(0,p->unit_count);ASSERT_EQ(2,s.usage->inherited);
        } else {
            ASSERT_EQ(1,p->turn_count);ASSERT_EQ(1,p->unit_count);
            ASSERT_EQ(effective[k]!=0,p->requests[0].at_ms.present);
            ASSERT_EQ(effective[k]!=0,p->turns[0].start_ms.present);
            ASSERT_EQ(effective[k]!=0,p->units[0].at_ms.present);
            if(effective[k]) {
                ASSERT_EQ(effective[k],p->requests[0].at_ms.value);
                ASSERT_EQ(effective[k],p->turns[0].start_ms.value.i);
                ASSERT_EQ(k==5||k==9?4000:effective[k],p->units[0].at_ms.value);
                ASSERT_EQ(k==5||k==9?4000:effective[k],p->end_ms.value);
                ASSERT_EQ(k==5||k==9?4000:effective[k],p->turns[0].end_ms.value.i);
            }
        }
        corpus_destroy(&c);opencode_store_destroy(&s);opencode_fixture_close(&f);
    }
}
