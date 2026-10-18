#include "opencode/compose.h"
#include "opencode/corpus.h"
#include "runner.h"
#include <float.h>
#include <math.h>

static OpencodeMessage msg(void) {
    return (OpencodeMessage){.kind=OC_MSG_ASSISTANT,.tokens_present=true,.tokens_valid=true,
        .tokens={11,7,3,5,2},.cost_present=true,.cost_valid=true,.cost=0.25,
        .provider_id=STR_LIT("synthetic-provider"),.model_id=STR_LIT("synthetic-model"),
        .created_ms={true,2000},.completed_ms={true,3000}};
}
static SessionModel *run(OpencodeStore *store,Corpus *c,OpencodeSession *s) {
    ASSERT_EQ(ERR_OK,opencode_corpus_add(store,5000,c).code);
    ASSERT_EQ(ERR_OK,opencode_compose(store,c).code);
    ASSERT_EQ(ERR_OK,compose_refresh_costs(c,false).code);
    return omap_get(&c->sessions,s->id);
}
#define SETUP(N) OpencodeMessage m[N]; for(size_t i=0;i<N;i++){m[i]=msg();m[i].seq=(int64_t)i;} \
    OpencodeSession s={.id=STR_LIT("synthetic-usage"),.database=STR_LIT("/synthetic/usage.db"), \
        .messages=m,.message_count=N,.created_ms={true,1000},.provenance_complete=true}; \
    OpencodeSession *rows[]={&s}; OpencodeStore store={.sessions=rows,.session_count=1};Corpus c={0}
#define DONE() corpus_destroy(&c);opencode_store_destroy(&store)
TEST(opencode_usage_component_mapping) {
    SETUP(1);SessionModel *p=run(&store,&c,&s);ASSERT_EQ(1,p->unit_count);
    UsageUnit *u=p->units;ASSERT_EQ(18,u->input);ASSERT_EQ(10,u->output);ASSERT_EQ(5,u->cached);
    ASSERT_EQ(2,u->cache_write);ASSERT_EQ(3,u->reasoning.value);ASSERT_TRUE(u->has_cost);
    ASSERT_EQ(3000,u->at_ms.value);ASSERT_EQ(1,store.usage->requests);
    ASSERT_TRUE(str_equal(u->model,STR_LIT("synthetic-provider/synthetic-model")));DONE();
}
TEST(opencode_usage_compaction) {
    SETUP(3);for(size_t i=0;i<3;i++)m[i].kind=OC_MSG_COMPACTION;
    m[0].status=STR_LIT("completed");m[1].status=STR_LIT("failed");m[2].status=STR_LIT("running");
    SessionModel *p=run(&store,&c,&s);ASSERT_EQ(2,p->unit_count);ASSERT_EQ(2,store.usage->requests);DONE();
}
TEST(opencode_usage_missing_and_explicit_zero_cost) {
    SETUP(3);m[0].tokens=(OpencodeTokens){0};m[0].cost=0;
    m[1].tokens_valid=false;m[1].cost_valid=false;m[2].cost=0;
    SessionModel *p=run(&store,&c,&s);ASSERT_EQ(1,p->unit_count);ASSERT_EQ(2,store.usage->missing_usage);
    ASSERT_TRUE(p->units[0].has_cost);ASSERT_EQ(0,p->own_usage->cost_usd);DONE();
}
TEST(opencode_usage_cost_without_tokens) {
    SETUP(1);m[0].tokens_valid=false;SessionModel *p=run(&store,&c,&s);
    ASSERT_EQ(1,p->unit_count);ASSERT_EQ(0,p->units[0].input);ASSERT_EQ(0.25,p->own_usage->cost_usd);
    ASSERT_EQ(1,store.usage->cost_only);DONE();
}
TEST(opencode_usage_missing_usage_by_provider) {
    SETUP(2);m[0].tokens_valid=m[1].tokens_valid=false;m[1].provider_id=(Str){0};
    run(&store,&c,&s);ASSERT_EQ(1,*(uint64_t*)omap_get(&store.usage->missing_by_provider,STR_LIT("synthetic-provider")));
    ASSERT_EQ(1,*(uint64_t*)omap_get(&store.usage->missing_by_provider,STR_LIT("opencode/unattributed")));DONE();
}
TEST(opencode_usage_residual_components_and_date) {
    SETUP(1);s.tokens_valid=true;s.tokens=(OpencodeTokens){20,9,4,8,3};s.cost_valid=true;s.cost=1;
    SessionModel *p=run(&store,&c,&s);ASSERT_EQ(2,p->unit_count);UsageUnit *u=&p->units[1];
    ASSERT_EQ(13,u->input);ASSERT_EQ(3,u->output);ASSERT_EQ(1000,u->at_ms.value);ASSERT_EQ(0,u->display_turn.n);
    ASSERT_EQ(0.75,u->cost_usd);ASSERT_EQ(1,store.usage->residual_count);ASSERT_EQ(31,p->own_usage->input);
    ASSERT_EQ(9,store.usage->residuals[0].tokens.input);DONE();
}
TEST(opencode_usage_residual_unknown_cost) {
    SETUP(1);s.tokens_valid=true;s.tokens.input=20; m[0].cost_valid=false;
    SessionModel *p=run(&store,&c,&s);ASSERT_FALSE(p->units[1].has_cost);ASSERT_FALSE(p->own_usage->has_cost);DONE();
}
TEST(opencode_usage_residual_known_zero_cost) {
    SETUP(1);s.tokens_valid=true;s.tokens=m[0].tokens;s.tokens.input++;s.cost_valid=true;s.cost=m[0].cost;
    SessionModel *p=run(&store,&c,&s);ASSERT_TRUE(p->units[1].has_cost);ASSERT_EQ(0,p->units[1].cost_usd);DONE();
}
TEST(opencode_usage_rounding_and_shortfalls) {
    SETUP(1);s.tokens_valid=true;s.tokens=(OpencodeTokens){9,9,1,6,1};s.cost_valid=true;s.cost=m[0].cost-1e-10;
    SessionModel *p=run(&store,&c,&s);ASSERT_EQ(2,p->unit_count);ASSERT_TRUE(store.usage->shortfall_count);
    ASSERT_EQ(1,p->units[1].cached);ASSERT_EQ(2,p->units[1].output);ASSERT_EQ(0,p->units[1].cost_usd);DONE();
}
TEST(opencode_usage_invalid_rollups_and_overflow) {
    SETUP(1);s.tokens_present=s.cost_present=true;s.cost=INFINITY;
    SessionModel *p=run(&store,&c,&s);ASSERT_EQ(1,p->unit_count);ASSERT_EQ(2,store.usage->invalid_count);DONE();
}
TEST(opencode_usage_finite_cost_aggregate_overflow) {
    SETUP(2);m[0].cost=m[1].cost=DBL_MAX;s.cost_valid=true;s.cost=DBL_MAX;
    SessionModel *p=run(&store,&c,&s);ASSERT_EQ(2,p->unit_count);ASSERT_FALSE(p->units[0].has_cost);
    ASSERT_FALSE(p->own_usage->has_cost);ASSERT_TRUE(isfinite(p->own_usage->cost_usd));ASSERT_TRUE(store.usage->invalid_count);
    /* Independently valid units must remain valid when a shared summary fails. */
    p->units[0].has_cost=p->units[1].has_cost=true;p->units[0].cost_usd=p->units[1].cost_usd=DBL_MAX;
    ASSERT_EQ(ERR_OK,compose_refresh_costs(&c,false).code);ASSERT_FALSE(p->own_usage->has_cost);
    ASSERT_FALSE(p->buckets[0].usage.has_cost);ASSERT_TRUE(isfinite(p->own_usage->cost_usd));DONE();
}
TEST(opencode_usage_fork_inheritance) {
    SETUP(2);s.fork_session_id=STR_LIT("synthetic-parent");m[0].row_created_ms=(MaybeMs){true,500};m[1].row_created_ms=(MaybeMs){true,2000};
    SessionModel *p=run(&store,&c,&s);ASSERT_EQ(1,p->unit_count);ASSERT_EQ(1,store.usage->inherited);ASSERT_EQ(1,store.usage->requests);DONE();
}
TEST(opencode_usage_codex_ledger_independence) {
    SETUP(1);SessionModel *p=run(&store,&c,&s);ASSERT_TRUE(p->own_usage->has_cost);ASSERT_EQ(0.25,p->own_usage->cost_usd);DONE();
}
TEST(opencode_usage_removed_messages_and_deleted_sessions_rebuild) {
    for(size_t k=0;k<3;k++) {
        SETUP(1);s.tokens_present=s.tokens_valid=true;s.tokens=m[0].tokens;s.cost_present=s.cost_valid=true;s.cost=m[0].cost;
        if(k==1)s.message_count=0;
        if(k==2)store.session_count=0;
        SessionModel *p=run(&store,&c,&s);
        if(k<2){ASSERT_TRUE(p);ASSERT_EQ(18,p->own_usage->input);ASSERT_EQ(0.25,p->own_usage->cost_usd);
            ASSERT_EQ(k,store.usage->residual_count);ASSERT_EQ(k==0?1:0,store.usage->requests);}
        else {ASSERT_FALSE(p);ASSERT_EQ(0,store.usage->residual_count);ASSERT_EQ(0,c.sessions.size);}
        DONE();
    }
}
TEST(opencode_usage_cost_only_residual_and_untimed) {
    SETUP(1);s.message_count=0;s.created_ms=(MaybeMs){0};s.cost_present=s.cost_valid=true;s.cost=0.5;
    SessionModel *p=run(&store,&c,&s);ASSERT_EQ(1,p->unit_count);ASSERT_TRUE(p->units[0].has_cost);
    ASSERT_FALSE(p->units[0].at_ms.present);ASSERT_EQ(0,p->units[0].input);ASSERT_EQ(0.5,p->units[0].cost_usd);
    ASSERT_FALSE(store.usage->residuals[0].date.present);DONE();
}
TEST(opencode_usage_residual_incomplete_attribution) {
    for(size_t k=0;k<4;k++) {
        SETUP(1);s.tokens_valid=true;s.tokens=m[0].tokens;s.tokens.input++;s.cost_valid=true;s.cost=m[0].cost;
        if(k==0)m[0].tokens_valid=false;
        if(k==1)s.malformed_messages=1;
        if(k==2)s.provenance_complete=false;
        if(k==3){m[0].cost_valid=false;s.cost=0;}
        SessionModel *p=run(&store,&c,&s);ASSERT_EQ(2,p->unit_count);ASSERT_FALSE(p->units[1].has_cost);
        ASSERT_FALSE(store.usage->residuals[0].has_cost);DONE();
    }
}
TEST(opencode_usage_sequence_and_creation_clock_fallback) {
    SETUP(3);m[0].seq=3;m[1].seq=1;m[2].seq=2;
    m[0].tokens.input=3;m[1].tokens.input=1;m[2].tokens.input=2;
    m[1].completed_ms=(MaybeMs){0};m[1].model_id=(Str){0};
    SessionModel *p=run(&store,&c,&s);ASSERT_EQ(8,p->units[0].input);ASSERT_EQ(9,p->units[1].input);ASSERT_EQ(10,p->units[2].input);
    ASSERT_EQ(2000,p->units[0].at_ms.value);ASSERT_TRUE(str_equal(p->units[0].model,STR_LIT("opencode/unattributed")));DONE();
}
TEST(opencode_usage_shared_overflow_isolates_turns_buckets_and_sessions) {
    SETUP(4);
    m[0]=(OpencodeMessage){.kind=OC_MSG_USER,.id=STR_LIT("synthetic-first"),.created_ms={true,1000}};
    m[2]=(OpencodeMessage){.kind=OC_MSG_USER,.id=STR_LIT("synthetic-second"),.created_ms={true,2000000}};
    m[1].cost=m[3].cost=DBL_MAX;m[3].completed_ms=(MaybeMs){true,2001000};
    SessionModel *p=run(&store,&c,&s);ASSERT_EQ(2,p->turn_count);
    /* Restore valid recorded costs, testing shared aggregation independently
     * from the provider's required whole-session overflow policy. */
    for(size_t i=0;i<2;i++){p->units[i].has_cost=true;p->units[i].cost_usd=DBL_MAX;}
    SessionModel other={.id=STR_LIT("synthetic-valid"),.provider=PROVIDER_CLAUDE};
    UsageUnit otherunit={.input=1,.has_cost=true,.cost_usd=0.5,.model=STR_LIT("synthetic-model")};
    other.units=&otherunit;other.unit_count=1;
    ASSERT_EQ(ERR_OK,omap_put(&c.sessions,other.id,&other).code);ASSERT_EQ(ERR_OK,compose_aggregate_session(&c,&other).code);
    ASSERT_EQ(ERR_OK,compose_refresh_costs(&c,false).code);ASSERT_FALSE(p->own_usage->has_cost);
    for(size_t i=0;i<2;i++){ASSERT_TRUE(p->turns[i].usage->has_cost);ASSERT_EQ(DBL_MAX,p->turns[i].usage->cost_usd);
        ASSERT_TRUE(p->buckets[i].usage.has_cost);ASSERT_EQ(DBL_MAX,p->buckets[i].usage.cost_usd);}
    ASSERT_TRUE(other.own_usage->has_cost);ASSERT_EQ(0.5,other.own_usage->cost_usd);DONE();
}
TEST(opencode_usage_turn_and_bucket_overflow_stays_unavailable) {
    SETUP(4);m[0]=(OpencodeMessage){.kind=OC_MSG_USER,.id=STR_LIT("synthetic-turn"),.created_ms={true,1000}};
    m[1].cost=m[2].cost=DBL_MAX;m[3].cost=0.5;
    SessionModel *p=run(&store,&c,&s);for(size_t i=0;i<3;i++){p->units[i].has_cost=true;p->units[i].cost_usd=m[i+1].cost;}
    ASSERT_EQ(ERR_OK,compose_refresh_costs(&c,false).code);ASSERT_FALSE(p->own_usage->has_cost);
    ASSERT_FALSE(p->turns[0].usage->has_cost);ASSERT_FALSE(p->buckets[0].usage.has_cost);
    ASSERT_TRUE(isfinite(p->turns[0].usage->cost_usd));ASSERT_TRUE(isfinite(p->buckets[0].usage.cost_usd));DONE();
}
TEST(opencode_usage_rejected_collision_does_not_attach) {
    SETUP(1);SessionModel other={.id=s.id,.provider=PROVIDER_CLAUDE};
    ASSERT_EQ(ERR_OK,omap_put(&c.sessions,other.id,&other).code);ASSERT_EQ(ERR_OK,compose_aggregate_session(&c,&other).code);run(&store,&c,&s);
    ASSERT_FALSE(s.corpus_accepted);ASSERT_EQ(0,other.unit_count);ASSERT_EQ(0,store.usage->requests);DONE();
}
TEST(opencode_usage_explicit_zero_tuple_preserves_known_zero_residual) {
    SETUP(1);m[0].tokens=(OpencodeTokens){0};m[0].cost=0;s.tokens_valid=true;s.tokens.input=13;
    s.cost_valid=true;s.cost=0;
    SessionModel *p=run(&store,&c,&s);ASSERT_EQ(1,p->unit_count);ASSERT_EQ(1,store.usage->missing_usage);
    ASSERT_TRUE(p->units[0].has_cost);ASSERT_EQ(0,p->units[0].cost_usd);ASSERT_EQ(13,p->units[0].input);DONE();
}
TEST(opencode_usage_wide_component_mapping_and_invalid_cost) {
    SETUP(1);m[0].tokens=(OpencodeTokens){INT64_MAX,INT64_MAX,INT64_MAX,INT64_MAX,INT64_MAX};
    m[0].cost_valid=false;s.tokens_valid=true;s.tokens=m[0].tokens;
    SessionModel *p=run(&store,&c,&s);ASSERT_EQ((__int128)INT64_MAX*3,p->units[0].input);
    ASSERT_EQ((__int128)INT64_MAX*2,p->units[0].output);ASSERT_FALSE(p->units[0].has_cost);
    ASSERT_EQ(0,store.usage->residual_count);ASSERT_EQ(0,store.usage->shortfall_count);DONE();
}
