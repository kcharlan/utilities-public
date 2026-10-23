#include "antigravity_fixture.h"
#include "runner.h"
#include <stdlib.h>

TEST(antigravity_db_empty_schema_and_independent_identity){
    AntigravityFixture f;antigravity_fixture_open(&f);AntigravityStore s={0};antigravity_fixture_read(&f,&s);
    ASSERT_EQ(1,s.session_count);ASSERT_EQ(0,s.sessions[0]->meta_count);ASSERT_EQ(0,s.sessions[0]->step_count);ASSERT_FALSE(s.sessions[0]->archived);antigravity_store_destroy(&s);
    antigravity_fixture_sql(&f,"INSERT INTO trajectory_meta VALUES ('synthetic-independent-trajectory','synthetic-independent-cascade',1,2)");antigravity_fixture_read(&f,&s);
    ASSERT_EQ(1,s.session_count);ASSERT_TRUE(str_equal(s.sessions[0]->id,STR_LIT(AG_SYNTHETIC_ID)));ASSERT_EQ(1,s.diagnostic_count);
    ASSERT_TRUE(str_equal(s.sessions[0]->meta[0].cascade_id,STR_LIT("synthetic-independent-cascade")));antigravity_store_destroy(&s);antigravity_fixture_close(&f);
}
TEST(antigravity_db_rejects_missing_columns_but_allows_extra_tables){
    AntigravityFixture f;antigravity_fixture_open(&f);AntigravityStore s={0};
    antigravity_fixture_sql(&f,"CREATE TABLE synthetic_credentials(secret); INSERT INTO synthetic_credentials VALUES ('SYNTHETIC-NEVER-READ')");antigravity_fixture_read(&f,&s);ASSERT_EQ(1,s.session_count);antigravity_store_destroy(&s);
    antigravity_fixture_sql(&f,"ALTER TABLE steps RENAME COLUMN status TO synthetic_missing");antigravity_fixture_read(&f,&s);
    ASSERT_EQ(AG_DB_UNSUPPORTED,s.databases[0].status);ASSERT_EQ(0,s.session_count);ASSERT_TRUE(strstr(s.databases[0].reason.p,"status"));antigravity_store_destroy(&s);antigravity_fixture_close(&f);
}
TEST(antigravity_db_retains_valid_blob_siblings_and_raw_generators){
    AntigravityFixture f;antigravity_fixture_open(&f);AntigravityStore s={0};
    antigravity_fixture_sql(&f,"INSERT INTO trajectory_metadata_blob VALUES(1,x'0a020a00'); INSERT INTO trajectory_metadata_blob VALUES(2,x'0a0180'); INSERT INTO steps VALUES(1,1,1,x'',x'9a01030a0178',0); INSERT INTO steps VALUES(2,1,1,x'80',x'',0); INSERT INTO gen_metadata VALUES(7,x'120201020a0422021009')");
    antigravity_fixture_read(&f,&s);ASSERT_EQ(1,s.session_count);AntigravitySession *r=s.sessions[0];
    ASSERT_EQ(1,r->metadata_count);ASSERT_EQ(1,r->step_count);ASSERT_EQ(1,r->generator_count);ASSERT_EQ(7,r->generators[0].idx);ASSERT_EQ(2,s.malformed_blobs);
    AgField chat={0},usage={0},input={0};ASSERT_EQ(AG_FOUND,ag_wire_last(r->generators[0].data,1,&chat));ASSERT_EQ(AG_FOUND,ag_wire_last(chat.bytes,4,&usage));ASSERT_EQ(AG_FOUND,ag_wire_last(usage.bytes,2,&input));ASSERT_EQ(9,input.integer);
    antigravity_store_destroy(&s);antigravity_fixture_close(&f);
}
TEST(antigravity_db_annotation_default_overrides_summary_archive){
    AntigravityFixture f;antigravity_fixture_open(&f);
    antigravity_fixture_summary(&f,"CREATE TABLE conversation_summaries(conversation_id,title,raw_summary);INSERT INTO conversation_summaries VALUES('" AG_SYNTHETIC_ID "','Synthetic summary',x'7a022001')");
    antigravity_fixture_annotation(&f," title: \"Synthetic \\n\\x6b\\151te\" unknown { deeper { quoted: \"{archived:true}\" } } ");
    AntigravityStore s={0};antigravity_fixture_read(&f,&s);ASSERT_EQ(1,s.session_count);AntigravitySession *r=s.sessions[0];
    ASSERT_FALSE(r->archived);ASSERT_TRUE(r->annotation_valid);ASSERT_TRUE(r->summary_valid);ASSERT_EQ(1,s.archive_disagreements);ASSERT_TRUE(str_equal(r->title,STR_LIT("Synthetic \nkite")));ASSERT_EQ(0,r->archive_reason.n);
    antigravity_store_destroy(&s);antigravity_fixture_close(&f);
}
TEST(antigravity_db_malformed_annotation_falls_back_to_summary){
    const char *bad[]={"archived: tru","unknown { title: \"Synthetic\"","title: \"Synthetic\\q\"","title: \"unfinished","unknown { } }","archived:","archived true","title \"Synthetic missing colon\""};
    for(size_t i=0;i<sizeof bad/sizeof *bad;i++){
        AntigravityFixture f;antigravity_fixture_open(&f);antigravity_fixture_annotation(&f,bad[i]);
        antigravity_fixture_summary(&f,"CREATE TABLE conversation_summaries(conversation_id,title,raw_summary);INSERT INTO conversation_summaries VALUES('" AG_SYNTHETIC_ID "','Synthetic summary',x'7a022001')");
        AntigravityStore s={0};antigravity_fixture_read(&f,&s);ASSERT_TRUE(s.sessions[0]->archived);ASSERT_TRUE(str_equal(s.sessions[0]->archive_reason,STR_LIT("session")));ASSERT_EQ(1,s.annotation_errors);antigravity_store_destroy(&s);antigravity_fixture_close(&f);
    }
}
TEST(antigravity_db_annotation_recursion_limit_is_recoverable){
    AntigravityFixture f;antigravity_fixture_open(&f);char input[1024]="";
    for(size_t i=0;i<AG_WIRE_MAX_DEPTH+1;i++)strcat(input,"unknown {");
    for(size_t i=0;i<AG_WIRE_MAX_DEPTH+1;i++)strcat(input,"}");
    antigravity_fixture_annotation(&f,input);AntigravityStore s={0};antigravity_fixture_read(&f,&s);ASSERT_EQ(1,s.annotation_errors);ASSERT_FALSE(s.sessions[0]->archived);antigravity_store_destroy(&s);antigravity_fixture_close(&f);
}
TEST(antigravity_db_summary_title_only_and_absent_archive){
    AntigravityFixture f;antigravity_fixture_open(&f);
    antigravity_fixture_summary(&f,"CREATE TABLE conversation_summaries(conversation_id,title);INSERT INTO conversation_summaries VALUES('" AG_SYNTHETIC_ID "','Synthetic title-only')");
    AntigravityStore s={0};antigravity_fixture_read(&f,&s);ASSERT_FALSE(s.sessions[0]->archived);ASSERT_TRUE(str_equal(s.sessions[0]->title,STR_LIT("Synthetic title-only")));ASSERT_TRUE(s.sessions[0]->summary_valid);antigravity_store_destroy(&s);antigravity_fixture_close(&f);
}
TEST(antigravity_db_explicit_empty_annotation_title_falls_back_independently){
    AntigravityFixture f;antigravity_fixture_open(&f);antigravity_fixture_annotation(&f,"title: \"\" archived: true");
    antigravity_fixture_summary(&f,"CREATE TABLE conversation_summaries(conversation_id,title);INSERT INTO conversation_summaries VALUES('" AG_SYNTHETIC_ID "','Synthetic title fallback')");
    AntigravityStore s={0};antigravity_fixture_read(&f,&s);AntigravitySession *r=s.sessions[0];ASSERT_TRUE(r->annotation_title.p);ASSERT_EQ(0,r->annotation_title.n);ASSERT_TRUE(str_equal(r->title,STR_LIT("Synthetic title fallback")));ASSERT_TRUE(r->archived);antigravity_store_destroy(&s);antigravity_fixture_close(&f);
}
TEST(antigravity_db_malformed_summary_loses_only_its_record){
    AntigravityFixture f;antigravity_fixture_open(&f);
    antigravity_fixture_summary(&f,"CREATE TABLE conversation_summaries(conversation_id,title,raw_summary);INSERT INTO conversation_summaries VALUES('" AG_SYNTHETIC_ID "','Synthetic rejected summary',x'7a0180')");
    AntigravityStore s={0};antigravity_fixture_read(&f,&s);ASSERT_EQ(1,s.session_count);ASSERT_FALSE(s.sessions[0]->summary_valid);ASSERT_FALSE(s.sessions[0]->archived);ASSERT_EQ(0,s.sessions[0]->title.n);ASSERT_EQ(1,s.diagnostic_count);antigravity_store_destroy(&s);antigravity_fixture_close(&f);
}
TEST(antigravity_db_failed_snapshot_does_not_consume_identity){
    AntigravityFixture f;antigravity_fixture_open(&f);
    antigravity_fixture_sql(&f,"INSERT INTO gen_metadata VALUES(1,x'12020102')");
    AntigravityStore s={0};Args args={.antigravity_home=f.home};ASSERT_EQ(ERR_OK,antigravity_discover(&args,&s).code);
    ASSERT_EQ(0,setenv("COLOPHON_TEST_FAULT","antigravity.commit:1",1));
    ASSERT_EQ(ERR_OK,antigravity_store_read(&s,NULL).code);ASSERT_EQ(0,unsetenv("COLOPHON_TEST_FAULT"));
    ASSERT_EQ(AG_DB_UNREADABLE,s.databases[0].status);ASSERT_EQ(0,s.session_count);ASSERT_EQ(0,s.session_ids.size);ASSERT_EQ(0,s.databases[0].accepted_sessions);
    antigravity_store_destroy(&s);antigravity_fixture_read(&f,&s);ASSERT_EQ(1,s.session_count);ASSERT_EQ(1,s.sessions[0]->generator_count);antigravity_store_destroy(&s);antigravity_fixture_close(&f);
}
TEST(antigravity_db_rejects_numeric_coercion_and_preserves_null_presence){
    AntigravityFixture f;antigravity_fixture_open(&f);
    antigravity_fixture_sql(&f,"INSERT INTO trajectory_meta VALUES(NULL,NULL,NULL,NULL);INSERT INTO trajectory_meta VALUES('synthetic-bad',NULL,'1',2);INSERT INTO gen_metadata VALUES('7',x'');INSERT INTO gen_metadata VALUES(NULL,x'');INSERT INTO gen_metadata VALUES(9,x'');INSERT INTO steps VALUES(1,NULL,NULL,x'',x'',NULL);INSERT INTO steps VALUES(2,1.5,1,x'',x'',0)");
    AntigravityStore s={0};antigravity_fixture_read(&f,&s);ASSERT_EQ(1,s.session_count);AntigravitySession *r=s.sessions[0];
    ASSERT_EQ(1,r->meta_count);ASSERT_FALSE(r->meta[0].has_trajectory_type);ASSERT_FALSE(r->meta[0].has_source);
    ASSERT_EQ(1,r->generator_count);ASSERT_EQ(9,r->generators[0].idx);
    ASSERT_EQ(1,r->step_count);ASSERT_FALSE(r->steps[0].has_step_type);ASSERT_FALSE(r->steps[0].has_status);ASSERT_FALSE(r->steps[0].has_step_format);
    ASSERT_EQ(4,s.malformed_rows);antigravity_store_destroy(&s);antigravity_fixture_close(&f);
}
