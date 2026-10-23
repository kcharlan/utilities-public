#include "antigravity/corpus.h"
#include "runner.h"
#include "out/jsonw.h"
#include "antigravity/compose.h"
#include "corpus/workspaces.h"
#include <stdlib.h>

static SessionModel *project(AntigravityStore *store,Corpus *c,AntigravitySession **rows,size_t n,int64_t snapshot) {
    store->sessions=rows;store->session_count=n;
    ASSERT_EQ(ERR_OK,antigravity_corpus_add(store,snapshot,c).code);
    return omap_get(&c->sessions,rows[0]->id);
}
static AntigravityStep user(void) {
    return (AntigravityStep){.idx=0,.step_type=14,.step_type_state=AG_SQL_INTEGER,
        .metadata=STR_LIT("\12\2\10\2"),.payload=STR_LIT("\232\1\13\22\11Synthetic")};
}
static void cleanup(AntigravityStore *s,Corpus *c) {corpus_destroy(c);antigravity_store_destroy(s);}
static void varint(JsonWriter *w,uint64_t n) {do{char c=(char)((n&127)|(n>127?128:0));jsonw_bytes(w,&c,1);n>>=7;}while(n);}
static void field(JsonWriter *w,uint32_t n,Str bytes) {varint(w,((uint64_t)n<<3)|2);varint(w,bytes.n);jsonw_bytes(w,bytes.p,bytes.n);}
static Str bytes(JsonWriter *w) {return (Str){w->data,(uint32_t)w->length};}
TEST(antigravity_corpus_tools_and_malformed_mcp) {
    const Str names[]={STR_LIT("run_command"),STR_LIT("write_to_file"),STR_LIT("write_file"),STR_LIT("replace_file_content"),STR_LIT("multi_replace_file_content"),STR_LIT("call_mcp_tool"),STR_LIT("call_mcp_tool"),STR_LIT("synthetic_other")};
    JsonWriter planner={0};
    for(size_t i=0;i<8;i++) {JsonWriter call={0};field(&call,1,STR_LIT("synthetic-call"));field(&call,2,names[i]);
        if(i==5)field(&call,3,STR_LIT("{\"ServerName\":\"synthetic\",\"ToolName\":\"lookup\"}"));
        if(i==6)field(&call,3,STR_LIT("{broken"));
        if(i==7)field(&call,3,STR_LIT("{also-broken"));
        field(&planner,7,bytes(&call));jsonw_free(&call);
    }
    JsonWriter unmatched={0};field(&unmatched,1,STR_LIT("synthetic-unmatched"));field(&unmatched,2,STR_LIT("run_command"));field(&planner,7,bytes(&unmatched));jsonw_free(&unmatched);
    JsonWriter payload={0},call={0},meta={0};field(&payload,20,bytes(&planner));
    field(&call,1,STR_LIT("synthetic-call"));field(&meta,4,bytes(&call));
    AntigravityStep steps[]={user(),{.idx=1,.payload=bytes(&payload)},
        {.idx=2,.metadata=bytes(&meta),.status_state=AG_SQL_INTEGER,.status=7}};
    AntigravitySession raw={.id=STR_LIT("synthetic-tools"),.steps=steps,.step_count=3},*rows[]={&raw};
    Corpus c={0};AntigravityStore s={0};SessionModel *p=project(&s,&c,rows,1,5000);
    ASSERT_EQ(2,p->tools.shell);ASSERT_EQ(1,p->tools.shell_failed);ASSERT_EQ(4,p->tools.file_edits);
    ASSERT_EQ(1,*(__int128*)omap_get(&p->tools.mcp,STR_LIT("synthetic")));
    ASSERT_EQ(1,*(__int128*)omap_get(&p->tools.other,STR_LIT("synthetic_other")));
    ASSERT_EQ(2,s.diagnostic_count);
    cleanup(&s,&c);jsonw_free(&planner);jsonw_free(&payload);jsonw_free(&call);jsonw_free(&meta);
}
TEST(antigravity_corpus_parentless_source_orphans_and_provider_collisions) {
    AntigravityMeta source={.source_state=AG_SQL_INTEGER,.source=16};
    AntigravityBlob metadata={.data=STR_LIT("\52\20synthetic-parent")};
    AntigravitySession parent={.id=STR_LIT("synthetic-parent")},child={.id=STR_LIT("synthetic-child"),.metadata=&metadata,.metadata_count=1},
        parentless={.id=STR_LIT("synthetic-parentless"),.meta=&source,.meta_count=1},
        collision={.id=STR_LIT("synthetic-collision")};
    SessionModel other={.provider=PROVIDER_CLAUDE,.id=collision.id};
    AntigravitySession *rows[]={&child,&parentless,&parent,&collision};Corpus c={0};AntigravityStore s={0};
    ASSERT_EQ(ERR_OK,omap_put(&c.sessions,other.id,&other).code);
    SessionModel *p=project(&s,&c,rows,4,5000),*orphan=omap_get(&c.sessions,parentless.id),*root=omap_get(&c.sessions,parent.id);
    ASSERT_TRUE(p->is_subagent&&p->has_link);ASSERT_EQ(1,p->depth);ASSERT_EQ(0,p->spawn_turn.n);
    ASSERT_EQ(1,root->children.count);ASSERT_TRUE(orphan->is_subagent);ASSERT_TRUE(orphan->flags&F_ORPHAN);
    ASSERT_TRUE(omap_get(&c.sessions,other.id)==&other);ASSERT_EQ(4,c.sessions.size);cleanup(&s,&c);
}
TEST(antigravity_corpus_split_nested_prompt_and_workspace) {
    JsonWriter u={0},payload={0},workspace={0},meta={0};
    field(&u,2,STR_LIT("Synthetic split prompt"));field(&payload,19,bytes(&u));jsonw_free(&u);
    field(&u,5,(Str){0});field(&payload,19,bytes(&u));
    field(&workspace,1,STR_LIT("file:///synthetic/root/work%20space"));field(&workspace,2,STR_LIT("file:///synthetic/root"));field(&workspace,4,STR_LIT("synthetic-branch"));field(&meta,1,bytes(&workspace));
    AntigravityBlob metadata={.data=bytes(&meta)};AntigravityStep step=user();step.payload=bytes(&payload);
    AntigravitySession raw={.id=STR_LIT("synthetic-split"),.steps=&step,.step_count=1,.metadata=&metadata,.metadata_count=1},*rows[]={&raw};
    Corpus c={0};AntigravityStore s={0};SessionModel *p=project(&s,&c,rows,1,5000);
    ASSERT_TRUE(str_equal(p->requests[0].text,STR_LIT("Synthetic split prompt")));ASSERT_EQ(1,p->requests[0].images);
    ASSERT_EQ(JS_STRING,p->meta.cwd.kind);ASSERT_TRUE(str_equal(p->meta.cwd.value.s,STR_LIT("/synthetic/root/work space")));
    ASSERT_TRUE(str_equal(p->meta.branch.value.s,STR_LIT("synthetic-branch")));
    WorkspaceAliases aliases={0};ASSERT_EQ(ERR_OK,corpus_resolve_workspaces(&c,&aliases).code);
    ASSERT_TRUE(str_equal(p->subfolder,STR_LIT("work space")));
    cleanup(&s,&c);jsonw_free(&u);jsonw_free(&payload);jsonw_free(&workspace);jsonw_free(&meta);
}
TEST(antigravity_corpus_empty_usage_reinitialized_after_compose_destroy) {
    AntigravityStep step=user();AntigravitySession raw={.id=STR_LIT("synthetic-empty-usage"),.steps=&step,.step_count=1},*rows[]={&raw};
    Corpus c={0};AntigravityStore s={0};SessionModel *p=project(&s,&c,rows,1,5000);PriorityTurns priority={0};
    for(size_t i=0;i<3;i++) {
        ASSERT_EQ(ERR_OK,compose_usage(&c,&priority).code);
        ASSERT_EQ(ERR_OK,antigravity_compose(&s,&c,NULL,NULL).code);
        ASSERT_EQ(ERR_OK,compose_refresh_costs(&c,false).code);
        ASSERT_TRUE(p->own_usage&&p->outside_usage&&p->turns[0].usage);
        ASSERT_EQ(0,p->own_usage->input);ASSERT_EQ(0,p->bucket_count);
        compose_destroy(&c);
    }
    cleanup(&s,&c);
}
TEST(antigravity_corpus_joined_items_images_answer_and_invalid_workspace) {
    JsonWriter usermsg={0},item={0},media={0},payload={0},workspace={0},metadata={0};
    field(&item,1,STR_LIT("Synthetic first"));field(&usermsg,3,bytes(&item));jsonw_free(&item);
    field(&item,1,STR_LIT("Synthetic second"));field(&usermsg,3,bytes(&item));field(&usermsg,5,(Str){0});
    field(&media,1,STR_LIT("image/png"));field(&usermsg,9,bytes(&media));jsonw_free(&media);
    field(&media,1,STR_LIT("audio/wav"));field(&usermsg,9,bytes(&media));field(&payload,19,bytes(&usermsg));
    field(&workspace,1,STR_LIT("file:///synthetic/%GG"));field(&metadata,1,bytes(&workspace));
    AntigravityBlob meta={.data=bytes(&metadata)};
    AntigravityStep steps[]={user(),{.idx=1,.payload=STR_LIT("\242\1\12\102\10Modified")}};steps[0].payload=bytes(&payload);
    AntigravitySession raw={.id=STR_LIT("synthetic-items"),.steps=steps,.step_count=2,.metadata=&meta,.metadata_count=1},*rows[]={&raw};
    Corpus c={0};AntigravityStore s={0};SessionModel *p=project(&s,&c,rows,1,5000);
    ASSERT_TRUE(str_equal(p->requests[0].text,STR_LIT("Synthetic first\nSynthetic second")));ASSERT_EQ(2,p->requests[0].images);
    ASSERT_TRUE(str_equal(p->turns[0].final_answer,STR_LIT("Modified")));ASSERT_EQ(JS_ABSENT,p->meta.cwd.kind);ASSERT_EQ(1,s.diagnostic_count);
    cleanup(&s,&c);jsonw_free(&usermsg);jsonw_free(&item);jsonw_free(&media);jsonw_free(&payload);jsonw_free(&workspace);jsonw_free(&metadata);
}
TEST(antigravity_corpus_open_quiet_boundary_uses_latest_completion) {
    AntigravityStep steps[]={user(),{.idx=1,.status=1,.status_state=AG_SQL_INTEGER,.metadata=STR_LIT("\12\2\10\3\102\2\10\4")}};
    for(size_t i=0;i<2;i++) {
        AntigravitySession raw={.id=STR_LIT("synthetic-quiet-completion"),.steps=steps,.step_count=2},*rows[]={&raw};
        Corpus c={0};AntigravityStore s={0};SessionModel *p=project(&s,&c,rows,1,7204000+(int64_t)i);
        ASSERT_TRUE(str_equal(p->turns[0].status,i?STR_LIT("abandoned"):STR_LIT("running")));
        ASSERT_EQ(i?4000:7204000,p->turns[0].end_ms.value.i);cleanup(&s,&c);
    }
}
TEST(antigravity_corpus_explicit_payload_enum_fallback_and_sql_conflict) {
    for(size_t i=0;i<5;i++) {
        AntigravityStep step=user();step.payload=STR_LIT("\10\16\40\7\232\1\13\22\11Synthetic");
        step.step_type_state=i==0?AG_SQL_ABSENT:i==1?AG_SQL_INVALID:AG_SQL_INTEGER;
        step.status_state=i==0?AG_SQL_ABSENT:i==1?AG_SQL_INVALID:AG_SQL_INTEGER;step.status=3;
        if(i==2)step.step_type=15; /* SQL explicit planner beats payload user. */
        if(i==3){step.step_type_state=AG_SQL_ABSENT;step.payload=STR_LIT("\232\1\13\22\11Synthetic");}
        if(i==4){step.status=1;step.status_state=AG_SQL_INTEGER;}
        AntigravitySession raw={.id=STR_LIT("synthetic-fallback"),.steps=&step,.step_count=1},*rows[]={&raw};
        Corpus c={0};AntigravityStore s={0};SessionModel *p=project(&s,&c,rows,1,5000);
        ASSERT_EQ(i==2||i==3?0:1,p->turn_count);
        if(i<2)ASSERT_TRUE(str_equal(p->turns[0].status,STR_LIT("aborted")));
        if(i==4)ASSERT_TRUE(str_equal(p->turns[0].status,STR_LIT("running")));
        if(i==2||i==4)ASSERT_TRUE(s.diagnostic_count>0);
        cleanup(&s,&c);
    }
}
/* Losing error/cancel precedence, treating cleared as active, or letting an
 * earlier active turn remain open must fail these literal reducer cases. */
TEST(antigravity_turn_status_reducer) {
    const int64_t statuses[]={0,1,2,3,4,5,6,7,8,9,11,12,999,INT64_MAX};
    const char *wanted[]={"completed","running","running","completed","completed","completed","interrupted","aborted","running","running","running","interrupted","completed","completed"};
    for(size_t i=0;i<sizeof statuses/sizeof *statuses;i++)for(size_t earlier=0;earlier<2;earlier++)for(size_t quiet=0;quiet<2;quiet++) {
        AntigravityStep steps[]={user(),{.idx=1,.status_state=AG_SQL_INTEGER,.status=statuses[i],.metadata=STR_LIT("\12\2\10\3")},user()};
        steps[2].idx=2;steps[2].metadata=STR_LIT("\12\2\10\4");
        AntigravitySession raw={.id=STR_LIT("synthetic-status"),.steps=steps,.step_count=earlier?3:2},*rows[]={&raw};
        Corpus c={0};AntigravityStore s={0};SessionModel *p=project(&s,&c,rows,1,quiet?7203001:5000);
        ASSERT_TRUE(p);ASSERT_EQ(earlier?2:1,p->turn_count);
        const char *want=wanted[i];
        if(!strcmp(want,"running"))want=earlier?"completed":quiet?"abandoned":"running";
        ASSERT_TRUE(str_equal(p->turns[0].status,(Str){want,(uint32_t)strlen(want)}));
        ASSERT_EQ(2000,p->turns[0].start_ms.value.i);
        if(strcmp(want,"running"))ASSERT_FALSE(p->turns[0].end_ms.present);
        cleanup(&s,&c);
    }
    const int64_t mixed[][2]={{6,7},{7,12},{1,6},{12,1},{5,3}};
    const char *mixed_want[]={"aborted","aborted","interrupted","interrupted","completed"};
    for(size_t i=0;i<5;i++) {
        AntigravityStep steps[]={user(),{.idx=1,.status_state=AG_SQL_INTEGER,.status=mixed[i][0]},
            {.idx=2,.status_state=AG_SQL_INTEGER,.status=mixed[i][1]}};
        AntigravitySession raw={.id=STR_LIT("synthetic-mixed"),.steps=steps,.step_count=3},*rows[]={&raw};
        Corpus c={0};AntigravityStore s={0};SessionModel *p=project(&s,&c,rows,1,5000);
        ASSERT_TRUE(str_equal(p->turns[0].status,(Str){mixed_want[i],(uint32_t)strlen(mixed_want[i])}));cleanup(&s,&c);
    }
}
TEST(antigravity_corpus_prompts_answers_clocks_and_leading_steps) {
    AntigravityStep steps[]={ {.idx=0,.metadata=STR_LIT("\12\2\10\1")},user(),
        {.idx=2,.metadata=STR_LIT("\12\2\10\3\102\2\10\4"),
         .payload=STR_LIT("\242\1\12\12\10Response\242\1\7\32\5NEVER")}};
    steps[1].idx=1;
    AntigravitySession raw={.id=STR_LIT("synthetic-projection"),.surface=STR_LIT("cli"),.steps=steps,.step_count=3},*rows[]={&raw};
    Corpus c={0};AntigravityStore s={0};SessionModel *p=project(&s,&c,rows,1,5000);
    ASSERT_EQ(1,p->turn_count);ASSERT_EQ(1000,p->start_ms.value);ASSERT_EQ(4000,p->end_ms.value);
    ASSERT_EQ(2000,p->turns[0].start_ms.value.i);ASSERT_EQ(4000,p->turns[0].end_ms.value.i);
    ASSERT_TRUE(str_equal(p->requests[0].text,STR_LIT("Synthetic")));
    ASSERT_TRUE(str_equal(p->turns[0].final_answer,STR_LIT("Response")));
    ASSERT_TRUE(str_equal(p->title_source,STR_LIT("first_request")));
    ASSERT_TRUE(str_equal(p->antigravity_surface,STR_LIT("cli")));
    ASSERT_EQ(0,steps[0].turn.n);ASSERT_TRUE(steps[1].turn.n);
    cleanup(&s,&c);
}
TEST(antigravity_corpus_titles_and_split_timestamp) {
    const Str titles[]={STR_LIT("Synthetic annotation"),STR_LIT("Synthetic summary"),(Str){0},(Str){0}};
    const char *sources[]={"antigravity_title","antigravity_title","first_request","session_id"};
    for(size_t i=0;i<4;i++) {
        AntigravityStep step=user();step.metadata=STR_LIT("\12\2\10\3\12\4\20\300\204\75");
        if(i==3)step.payload=(Str){0};
        AntigravitySession raw={.id=STR_LIT("synthetic-title-id"),.steps=&step,.step_count=1,.title=titles[i]},*rows[]={&raw};
        Corpus c={0};AntigravityStore s={0};SessionModel *p=project(&s,&c,rows,1,5000);
        ASSERT_TRUE(str_equal(p->title_source,(Str){sources[i],(uint32_t)strlen(sources[i])}));
        ASSERT_TRUE(str_equal(p->title_full,i<2?titles[i]:i==2?STR_LIT("Synthetic"):raw.id));
        ASSERT_EQ(3001,p->start_ms.value);ASSERT_EQ(3001,p->turns[0].start_ms.value.i);
        cleanup(&s,&c);
    }
}
TEST(antigravity_corpus_zero_turns_trajectory_clock_and_foreign_parent) {
    AntigravityStep leading={.idx=1,.metadata=STR_LIT("\12\2\10\2\102\2\10\3")};
    AntigravityBlob metadata={.data=STR_LIT("\22\2\10\1\52\21synthetic-foreign")};
    for(size_t i=0;i<2;i++) {
        AntigravitySession raw={.id=STR_LIT("synthetic-leading-only"),.surface=STR_LIT("app"),.steps=i?&leading:NULL,.step_count=i,
            .metadata=i?&metadata:NULL,.metadata_count=i},*rows[]={&raw};
        SessionModel foreign={.id=STR_LIT("synthetic-foreign"),.provider=PROVIDER_CLAUDE};
        Corpus c={0};AntigravityStore s={0};ASSERT_EQ(ERR_OK,omap_put(&c.sessions,foreign.id,&foreign).code);
        SessionModel *p=project(&s,&c,rows,1,5000);ASSERT_EQ(0,p->turn_count);ASSERT_EQ(0,p->request_count);
        ASSERT_EQ(i!=0,p->start_ms.present);ASSERT_EQ(i!=0,p->end_ms.present);
        if(i){ASSERT_EQ(1000,p->start_ms.value);ASSERT_EQ(3000,p->end_ms.value);ASSERT_TRUE(p->flags&F_ORPHAN);ASSERT_EQ(1,s.orphaned_subagents.count);}
        ASSERT_EQ(0,foreign.children.count);ASSERT_EQ(0,leading.turn.n);cleanup(&s,&c);
    }
}
