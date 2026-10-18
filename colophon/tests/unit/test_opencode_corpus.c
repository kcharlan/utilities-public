#include "opencode/corpus.h"
#include "out/session_payload.h"
#include "runner.h"
#include <stdlib.h>

static OpencodeSession session(Str id, OpencodeMessage *messages, size_t count) {
    return (OpencodeSession){.id=id, .database=STR_LIT("/synthetic/opencode.db"),
        .title=STR_LIT("Synthetic session"), .messages=messages, .message_count=count,
        .created_ms={true,1000}, .updated_ms={true,4000}};
}
static OpencodeMessage user(Str id, int64_t time) {
    return (OpencodeMessage){.kind=OC_MSG_USER, .id=id,
        .text=STR_LIT("Synthetic request"), .row_created_ms={true,time},
        .created_ms={true,time}};
}
static OpencodeMessage assistant(int64_t time) {
    return (OpencodeMessage){.kind=OC_MSG_ASSISTANT,
        .text=STR_LIT("Synthetic answer"), .row_created_ms={true,time},
        .created_ms={true,time}, .completed_ms={true,time+100}, .finish=STR_LIT("stop")};
}
static SessionModel *project(OpencodeStore *store, Corpus *c, OpencodeSession **s, size_t n) {
    store->sessions=s; store->session_count=n;
    ASSERT_EQ(ERR_OK,opencode_corpus_add(store,5000,c).code);
    return omap_get(&c->sessions,s[0]->id);
}
static void cleanup(OpencodeStore *store, Corpus *c) {
    corpus_destroy(c); opencode_store_destroy(store);
}
TEST(opencode_corpus_turns_and_status) {
    const Str outcomes[]={STR_LIT("succeeded"),STR_LIT("failed"),STR_LIT("interrupted")};
    const Str expected[]={STR_LIT("completed"),STR_LIT("aborted"),STR_LIT("interrupted")};
    for(size_t k=0;k<6;k++) {
        OpencodeMessage m[]={user(STR_LIT("synthetic-row"),2000),assistant(3000),{0}};
        size_t count=2;
        if(k<3){m[2]=(OpencodeMessage){.kind=OC_MSG_IDLE,.outcome=outcomes[k],.created_ms={true,3500}};count=3;}
        else if(k<5)m[1].error=k==3?STR_LIT("aborted"):STR_LIT("synthetic-error");
        OpencodeSession s=session(STR_LIT("synthetic-status"),m,count), *rows[]={&s};
        Corpus c={0}; OpencodeStore store={0}; SessionModel *p=project(&store,&c,rows,1);
        ASSERT_TRUE(p); ASSERT_EQ(PROVIDER_OPENCODE,p->provider); ASSERT_EQ(1,p->turn_count);
        ASSERT_TRUE(str_equal(p->turns[0].status,k<3?expected[k]:k==3?expected[2]:k==4?expected[1]:expected[0]));
        ASSERT_TRUE(str_equal(s.turns[0]->turn_id,STR_LIT("synthetic-row")));
        ASSERT_TRUE(str_equal(m[1].turn,STR_LIT("opencode-turn-1")));
        ASSERT_TRUE(str_equal(p->turns[0].final_answer,m[1].text));
        ASSERT_EQ(2000,p->turns[0].start_ms.value.i);
        ASSERT_EQ(k<3?3500:3100,p->turns[0].end_ms.value.i);
        ASSERT_TRUE(str_equal(p->opencode_database,s.database));
        cleanup(&store,&c);
    }
}
TEST(opencode_corpus_open_turn_known_clocks) {
    OpencodeMessage m[]={user(STR_LIT("synthetic-row"),2000),assistant(3000)};
    m[1].finish=STR_LIT("tool-calls");
    OpencodeSession s=session(STR_LIT("synthetic-open"),m,2), *rows[]={&s};
    Corpus c={0}; OpencodeStore store={0}; SessionModel *p=project(&store,&c,rows,1);
    ASSERT_TRUE(p); ASSERT_TRUE(str_equal(p->turns[0].status,STR_LIT("running")));
    ASSERT_EQ(5000,p->turns[0].end_ms.value.i); ASSERT_EQ(3000,p->turns[0].duration_ms.value.i);
    ASSERT_TRUE(s.turns[0]->start_ms.present); ASSERT_EQ(2000,s.turns[0]->start_ms.value);
    ASSERT_FALSE(s.turns[0]->end_ms.present); ASSERT_EQ(3100,s.turns[0]->last_ms.value);
    cleanup(&store,&c);
}
TEST(opencode_corpus_tool_mapping) {
    OpencodeTool tools[]={ {.name=STR_LIT("shell"),.failed=true}, {.name=STR_LIT("bash")},
        {.name=STR_LIT("edit")},{.name=STR_LIT("patch")},{.name=STR_LIT("apply_patch")},
        {.name=STR_LIT("write")},{.name=STR_LIT("multiedit")},{.name=STR_LIT("webfetch")},
        {.name=STR_LIT("websearch")},{.name=STR_LIT("mcp__synthetic__lookup")},{.name=STR_LIT("synthetic-other")} };
    OpencodeMessage m[]={user(STR_LIT("synthetic-row"),2000),assistant(3000)};
    m[1].tools=tools;m[1].tool_count=sizeof tools/sizeof *tools;
    OpencodeSession s=session(STR_LIT("synthetic-tools"),m,2),*rows[]={&s};
    Corpus c={0}; OpencodeStore store={0}; SessionModel *p=project(&store,&c,rows,1);
    ASSERT_TRUE(p);ASSERT_EQ(2,p->tools.shell);ASSERT_EQ(1,p->tools.shell_failed);
    ASSERT_EQ(5,p->tools.file_edits);ASSERT_EQ(2,p->tools.web);
    ASSERT_EQ(1,*(__int128*)omap_get(&p->tools.mcp,STR_LIT("synthetic")));
    ASSERT_EQ(1,*(__int128*)omap_get(&p->turns[0].tools.other,STR_LIT("synthetic-other")));
    cleanup(&store,&c);
}
TEST(opencode_corpus_archive_precedence) {
    for(size_t k=0;k<4;k++){
        OpencodeSession s=session(STR_LIT("synthetic-archive"),NULL,0),*rows[]={&s};
        s.archived=k&1;s.project_archived=k&2;
        Corpus c={0};OpencodeStore store={0};SessionModel *p=project(&store,&c,rows,1);
        ASSERT_TRUE(p);ASSERT_EQ(k!=0,p->archived);
        ASSERT_TRUE(str_equal(p->archive_reason,k&1?STR_LIT("session"):k&2?STR_LIT("project"):(Str){0}));
        cleanup(&store,&c);
    }
}
TEST(opencode_corpus_parent_children_depth_and_spawn) {
    OpencodeTool tool={.name=STR_LIT("task"),.child_session_id=STR_LIT("synthetic-child")};
    OpencodeMessage m[]={user(STR_LIT("synthetic-parent-row"),2000),assistant(3000)};
    m[1].tools=&tool;m[1].tool_count=1;
    OpencodeSession child=session(STR_LIT("synthetic-child"),NULL,0),parent=session(STR_LIT("synthetic-parent"),m,2),
        grand=session(STR_LIT("synthetic-grandchild"),NULL,0);
    child.parent_id=parent.id;child.agent=STR_LIT("synthetic-agent");grand.parent_id=child.id;
    OpencodeSession *rows[]={&grand,&child,&parent}; Corpus c={0}; OpencodeStore store={0};
    project(&store,&c,rows,3);
    SessionModel *p=omap_get(&c.sessions,parent.id),*s=omap_get(&c.sessions,child.id),*g=omap_get(&c.sessions,grand.id);
    ASSERT_TRUE(p&&s&&g);
    ASSERT_EQ(1,p->children.count);ASSERT_TRUE(str_equal(p->children.items[0],s->id));
    ASSERT_TRUE(s->is_subagent&&s->has_link&&s->has_depth);ASSERT_EQ(1,s->depth);ASSERT_EQ(2,g->depth);
    ASSERT_TRUE(str_equal(s->spawn_turn,STR_LIT("opencode-turn-1")));
    ASSERT_TRUE(str_equal(s->link_method,STR_LIT("tool_use")));ASSERT_EQ(1,p->turns[0].spawned.count);
    ASSERT_TRUE(str_equal(s->agent_label,s->title_full));ASSERT_TRUE(str_equal(s->meta.agent_nickname.value.s,child.agent));
    PayloadIds ids={0};JsonWriter w={0};ASSERT_EQ(ERR_OK,payload_ids_init(&c,"/synthetic/codex",&ids).code);
    payload_sessions(&w,&c,&ids); ASSERT_EQ(ERR_OK,w.error.code);
    yyjson_doc *doc=yyjson_read(w.data,w.length,0);ASSERT_TRUE(doc);
    yyjson_val *root=yyjson_doc_get_root(doc);ASSERT_EQ(1,yyjson_arr_size(root));
    yyjson_val *row=yyjson_arr_get_first(root);
    ASSERT_STREQ("synthetic-parent",yyjson_get_str(yyjson_obj_get(row,"id")));
    ASSERT_STREQ("synthetic-child",yyjson_get_str(yyjson_arr_get_first(yyjson_obj_get(row,"children"))));
    yyjson_val *turn=yyjson_arr_get_first(yyjson_obj_get(row,"turns"));
    ASSERT_STREQ("synthetic-child",yyjson_get_str(yyjson_arr_get_first(yyjson_obj_get(turn,"spawned"))));
    yyjson_doc_free(doc);
    jsonw_free(&w);payload_subagents(&w,&c,&ids);ASSERT_EQ(ERR_OK,w.error.code);
    doc=yyjson_read(w.data,w.length,0);ASSERT_TRUE(doc);root=yyjson_doc_get_root(doc);
    ASSERT_EQ(2,yyjson_obj_size(root));row=yyjson_obj_get(root,"synthetic-child");
    ASSERT_STREQ("Synthetic session",yyjson_get_str(yyjson_obj_get(row,"label")));
    ASSERT_STREQ("synthetic-agent",yyjson_get_str(yyjson_obj_get(row,"nickname")));
    ASSERT_STREQ("synthetic-parent",yyjson_get_str(yyjson_obj_get(row,"parent_id")));
    ASSERT_STREQ("synthetic-grandchild",yyjson_get_str(yyjson_arr_get_first(yyjson_obj_get(row,"children"))));
    yyjson_doc_free(doc);
    jsonw_free(&w);payload_ids_destroy(&ids);cleanup(&store,&c);
}
TEST(opencode_corpus_missing_and_cyclic_parents) {
    OpencodeSession a=session(STR_LIT("synthetic-a"),NULL,0),b=session(STR_LIT("synthetic-b"),NULL,0),
        missing=session(STR_LIT("synthetic-missing"),NULL,0);
    a.parent_id=b.id;b.parent_id=a.id;missing.parent_id=STR_LIT("synthetic-absent");
    OpencodeSession *rows[]={&a,&b,&missing};Corpus c={0};OpencodeStore store={0};project(&store,&c,rows,3);
    ASSERT_EQ(3,store.orphaned_subagents.count);
    for(OmapEntry *q=c.sessions.first;q;q=q->next){SessionModel *s=q->value;
        ASSERT_TRUE(s->is_subagent&&s->has_link);ASSERT_TRUE(s->flags&F_ORPHAN);ASSERT_EQ(0,s->children.count);}
    cleanup(&store,&c);
}
TEST(opencode_corpus_public_id_collisions) {
    OpencodeSession a=session(STR_LIT("synthetic-public"),NULL,0),b=session(STR_LIT("synthetic-key"),NULL,0),*rows[]={&a,&b};
    SessionModel old={.id=a.id,.key=b.id,.provider=PROVIDER_CLAUDE};Corpus c={0};OpencodeStore store={0};
    ASSERT_EQ(ERR_OK,omap_put(&c.sessions,b.id,&old).code);project(&store,&c,rows,2);
    ASSERT_EQ(1,c.sessions.size);ASSERT_EQ(2,store.corpus_collisions.count);
    ASSERT_FALSE(a.corpus_accepted);ASSERT_FALSE(b.corpus_accepted);cleanup(&store,&c);
}
TEST(opencode_corpus_placeholder_titles) {
    const Str titles[]={STR_LIT("New session - synthetic"),STR_LIT("Child session - synthetic"),STR_LIT("   ")};
    for(size_t k=0;k<3;k++){
        OpencodeMessage m[]={user(STR_LIT("synthetic-row"),2000)};
        OpencodeSession s=session(STR_LIT("synthetic-title"),m,1),*rows[]={&s};s.title=titles[k];
        Corpus c={0};OpencodeStore store={0};SessionModel *p=project(&store,&c,rows,1);
        ASSERT_TRUE(p);ASSERT_TRUE(str_equal(p->title_full,m[0].text));cleanup(&store,&c);
    }
}
TEST(opencode_corpus_fork_row_identity_and_inheritance) {
    OpencodeMessage m[]={user(STR_LIT("synthetic-inherited-row"),500),assistant(600),user(STR_LIT("synthetic-own-row"),2000),assistant(3000)};
    m[0].created_ms.value=2500;m[1].created_ms.value=2600; /* copied payload clocks cannot prove ownership */
    OpencodeSession s=session(STR_LIT("synthetic-fork"),m,4),*rows[]={&s};s.fork_session_id=STR_LIT("synthetic-base");
    Corpus c={0};OpencodeStore store={0};SessionModel *p=project(&store,&c,rows,1);
    ASSERT_TRUE(p);ASSERT_TRUE(m[0].inherited&&m[1].inherited);ASSERT_FALSE(m[2].inherited);ASSERT_EQ(1,p->turn_count);
    ASSERT_TRUE(str_equal(s.turns[0]->turn_id,m[2].id));ASSERT_TRUE(p->flags&F_FORKED);ASSERT_FALSE(p->is_subagent);
    ASSERT_TRUE(str_equal(p->forked_from,s.fork_session_id));cleanup(&store,&c);
}
TEST(opencode_corpus_leading_usage) {
    OpencodeMessage m[]={assistant(1500),{.kind=OC_MSG_COMPACTION,.created_ms={true,1800}},user(STR_LIT("synthetic-row"),2000),assistant(3000)};
    OpencodeSession s=session(STR_LIT("synthetic-leading"),m,4),*rows[]={&s};Corpus c={0};OpencodeStore store={0};
    SessionModel *p=project(&store,&c,rows,1);ASSERT_TRUE(p);ASSERT_EQ(1,p->turn_count);
    ASSERT_EQ(0,m[0].turn.n);ASSERT_EQ(0,m[1].turn.n);ASSERT_TRUE(m[2].turn.n);cleanup(&store,&c);
}
TEST(opencode_corpus_unknown_clocks_and_relative_cwd) {
    OpencodeMessage m[]={user(STR_LIT("synthetic-row"),2000),assistant(3000)};
    for(size_t i=0;i<2;i++)m[i].row_created_ms=m[i].created_ms=m[i].completed_ms=(MaybeMs){0};
    OpencodeSession s=session(STR_LIT("synthetic-unknown"),m,2),*rows[]={&s};
    s.created_ms=s.updated_ms=(MaybeMs){0};s.directory=STR_LIT("synthetic/relative");s.fork_session_id=STR_LIT("synthetic-base");
    Corpus c={0};OpencodeStore store={0};SessionModel *p=project(&store,&c,rows,1);
    ASSERT_TRUE(p);
    ASSERT_FALSE(p->start_ms.present);ASSERT_FALSE(p->end_ms.present);ASSERT_FALSE(p->turns[0].start_ms.present);
    ASSERT_FALSE(m[0].inherited);ASSERT_EQ(JS_ABSENT,p->meta.cwd.kind);ASSERT_TRUE(store.unknown_clocks.count);
    cleanup(&store,&c);
}
TEST(opencode_corpus_ambiguous_spawn_evidence) {
    OpencodeTool tool={.name=STR_LIT("task"),.child_session_id=STR_LIT("synthetic-child")};
    OpencodeMessage m[]={user(STR_LIT("synthetic-row-1"),2000),assistant(2500),user(STR_LIT("synthetic-row-2"),3000),assistant(3500)};
    m[1].tools=m[3].tools=&tool;m[1].tool_count=m[3].tool_count=1;
    OpencodeSession parent=session(STR_LIT("synthetic-parent"),m,4),child=session(STR_LIT("synthetic-child"),NULL,0),*rows[]={&child,&parent};
    child.parent_id=parent.id;Corpus c={0};OpencodeStore store={0};SessionModel *s=project(&store,&c,rows,2);
    ASSERT_TRUE(s);
    ASSERT_EQ(0,s->spawn_turn.n);ASSERT_EQ(1,store.ambiguous_spawns.count);
    SessionModel *p=omap_get(&c.sessions,parent.id);ASSERT_EQ(0,p->turns[0].spawned.count);ASSERT_EQ(0,p->turns[1].spawned.count);
    cleanup(&store,&c);
}
TEST(opencode_corpus_cwd_requires_existing_absolute_directory) {
    const char embedded[]="/synthetic\0/hidden";
    const char *scratch=getenv("COLOPHON_HOME");ASSERT_TRUE(scratch);
    const Str paths[]={STR_LIT("synthetic/relative"),STR_LIT("/synthetic/not-a-real-directory"),
        {embedded,sizeof embedded-1},{scratch,(uint32_t)strlen(scratch)}};
    for(size_t i=0;i<4;i++) {
        OpencodeSession s=session(STR_LIT("synthetic-cwd"),NULL,0),*rows[]={&s};s.directory=paths[i];
        Corpus c={0};OpencodeStore store={0};SessionModel *p=project(&store,&c,rows,1);ASSERT_TRUE(p);
        ASSERT_EQ(i==3?JS_STRING:JS_ABSENT,p->meta.cwd.kind);
        if(i==3)ASSERT_TRUE(str_equal(p->meta.cwd.value.s,paths[i]));
        cleanup(&store,&c);
    }
}
TEST(opencode_corpus_missing_fork_timing_keeps_rows_and_title_id_fallback) {
    OpencodeMessage m[]={user(STR_LIT("synthetic-row"),500),assistant(600)};
    m[0].row_created_ms=(MaybeMs){0};
    OpencodeSession s=session(STR_LIT("synthetic-missing-fork-clock"),m,2),*rows[]={&s};
    s.fork_session_id=STR_LIT("synthetic-base");s.title=STR_LIT("Child session - synthetic");m[0].text=(Str){0};
    Corpus c={0};OpencodeStore store={0};SessionModel *p=project(&store,&c,rows,1);ASSERT_TRUE(p);
    ASSERT_FALSE(m[0].inherited);ASSERT_TRUE(m[1].inherited);ASSERT_EQ(1,p->turn_count);
    ASSERT_EQ(1,store.unknown_clocks.count);ASSERT_TRUE(str_equal(p->title_full,s.id));
    cleanup(&store,&c);
}
TEST(opencode_corpus_sorted_turn_models_keep_source_identity_and_requests) {
    OpencodeMessage m[]={user(STR_LIT("synthetic-later-row"),3000),assistant(3500),
        user(STR_LIT("synthetic-earlier-row"),2000),assistant(2500)};
    m[2].text=STR_LIT("Synthetic earlier request");m[3].text=STR_LIT("Synthetic earlier answer");
    OpencodeSession s=session(STR_LIT("synthetic-reordered"),m,4),*rows[]={&s};
    Corpus c={0};OpencodeStore store={0};SessionModel *p=project(&store,&c,rows,1);ASSERT_TRUE(p);
    ASSERT_EQ(2,p->turn_count);ASSERT_TRUE(str_equal(p->turns[0].id,STR_LIT("opencode-turn-2")));
    ASSERT_TRUE(str_equal(p->turns[0].requests[0]->text,m[2].text));
    ASSERT_TRUE(str_equal(p->turns[0].final_answer,m[3].text));
    ASSERT_TRUE(str_equal(s.turns[0]->turn_id,m[0].id));ASSERT_EQ(3600,p->end_ms.value);
    cleanup(&store,&c);
}
TEST(opencode_corpus_parent_resolution_excludes_other_providers) {
    OpencodeSession s=session(STR_LIT("synthetic-child"),NULL,0),*rows[]={&s};
    SessionModel parent={.provider=PROVIDER_CLAUDE,.id=STR_LIT("synthetic-parent")};s.parent_id=parent.id;
    Corpus c={0};OpencodeStore store={0};ASSERT_EQ(ERR_OK,omap_put(&c.sessions,parent.id,&parent).code);
    SessionModel *p=project(&store,&c,rows,1);ASSERT_TRUE(p);ASSERT_TRUE(p->flags&F_ORPHAN);
    ASSERT_EQ(0,parent.children.count);ASSERT_EQ(1,store.orphaned_subagents.count);cleanup(&store,&c);
}
