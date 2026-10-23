#include "antigravity/corpus.h"
#include "antigravity/compose.h"
#include "runner.h"
#include "out/jsonw.h"
#include "antigravity/model.h"
#include "price/claude_cost.h"
#include "util/json_read.h"
#include "util/json_number.h"
#include <stdio.h>
#include <stdlib.h>
#include <stdalign.h>

static void vi(JsonWriter *w,uint64_t n) {do{char b=(char)((n&127)|(n>127?128:0));jsonw_bytes(w,&b,1);n>>=7;}while(n);}
static void num(JsonWriter *w,uint32_t k,uint64_t n) {vi(w,(uint64_t)k<<3);vi(w,n);}
static Str bytes(JsonWriter *w) {return (Str){w->data,(uint32_t)w->length};}
static void msg(JsonWriter *w,uint32_t k,Str s) {vi(w,((uint64_t)k<<3)|2);vi(w,s.n);jsonw_bytes(w,s.p,s.n);}
static Str own(Arena *a,JsonWriter *w) {Str out={0};ASSERT_EQ(ERR_OK,str_copy(a,bytes(w),&out).code);jsonw_free(w);return out;}
static Str usage(Arena *a,int64_t input,int64_t total,int64_t thinking,int64_t visible,Str response,Str provider,Str message) {
    JsonWriter w={0};num(&w,2,(uint64_t)input);num(&w,3,(uint64_t)total);
    if(thinking>=0)num(&w,9,(uint64_t)thinking);if(visible>=0)num(&w,10,(uint64_t)visible);
    if(response.p)msg(&w,11,response);if(provider.p)msg(&w,12,provider);if(message.p)msg(&w,7,message);
    return own(a,&w);
}
static Str generator(Arena *a,Str u,Str model) {JsonWriter chat={0},gen={0};msg(&chat,4,u);if(model.n)msg(&chat,19,model);msg(&gen,1,bytes(&chat));jsonw_free(&chat);return own(a,&gen);}
static SessionModel *compose(AntigravityStore *s,Corpus *c,AntigravitySession **rows,size_t n,PricingReport *p) {
    s->sessions=rows;s->session_count=n;ASSERT_EQ(ERR_OK,antigravity_corpus_add(s,123456,c).code);
    PriorityTurns priority={0};ASSERT_EQ(ERR_OK,compose_usage(c,&priority).code);ASSERT_EQ(ERR_OK,antigravity_compose(s,c,NULL,p).code);
    return omap_get(&c->sessions,rows[0]->id);
}
static void destroy(AntigravityStore *s,Corpus *c,PricingReport *p) {corpus_destroy(c);antigravity_store_destroy(s);pricing_report_destroy(p);}
/* Captured from independently executed native ccusage 20.0.42. Each alias
 * kind is namespaced, any shared alias joins, and bridge records join groups.
 * IDs absent/empty never collapse equal-token requests. */
TEST(antigravity_ccusage_usage_oracle) {
    struct {Str r1,p1,m1,r2,p2,m2;int input,output,count,second_input;} cases[]={
      {STR_LIT("synthetic-r"),STR_LIT("synthetic-p1"),STR_LIT("synthetic-m1"),STR_LIT("synthetic-r"),STR_LIT("synthetic-p2"),STR_LIT("synthetic-m2"),20,4,1,20},
      {STR_LIT("synthetic-r1"),STR_LIT("synthetic-p"),{0},STR_LIT("synthetic-r2"),STR_LIT("synthetic-p"),{0},20,4,1,20},
      {{0},STR_LIT("synthetic-p1"),STR_LIT("synthetic-m"),{0},STR_LIT("synthetic-p2"),STR_LIT("synthetic-m"),20,4,1,20},
      {STR_LIT("synthetic-same"),{0},{0},{0},{0},STR_LIT("synthetic-same"),30,8,2,20},
      {{0},{0},{0},{0},{0},{0},20,8,2,10},
      {STR_LIT(""),STR_LIT(""),STR_LIT(""),STR_LIT(""),STR_LIT(""),STR_LIT(""),20,8,2,10},
    };
    for(size_t i=0;i<sizeof cases/sizeof *cases;i++) {
        Arena a={0};AntigravityBlob gens[2]={{0}};
        gens[0].data=generator(&a,usage(&a,10,4,1,3,cases[i].r1,cases[i].p1,cases[i].m1),STR_LIT("synthetic-first"));
        gens[1].data=generator(&a,usage(&a,cases[i].second_input,4,1,3,cases[i].r2,cases[i].p2,cases[i].m2),STR_LIT("synthetic-second"));
        AntigravitySession raw={.id=STR_LIT("synthetic-oracle"),.generators=gens,.generator_count=2},*rows[]={&raw};
        Corpus c={0};AntigravityStore s={0};PricingReport p={0};SessionModel *m=compose(&s,&c,rows,1,&p);
        ASSERT_EQ((size_t)cases[i].count,m->unit_count);ASSERT_EQ(cases[i].input,m->own_usage->input);ASSERT_EQ(cases[i].output,m->own_usage->output);
        ASSERT_TRUE(str_equal(STR_LIT("synthetic-first"),m->units[0].model_raw));
        destroy(&s,&c,&p);arena_destroy(&a);
    }
}
TEST(antigravity_ccusage_output_oracle) {
    const int values[][5]={{8,-1,-1,8,0},{8,3,-1,8,3},{0,3,5,8,3},{5,7,3,10,7},{8,0,0,8,0},{8,3,9,12,3},
      {30,3,5,30,3},{10,2,1,10,2},{30,-1,5,30,0},{30,3,0,30,3}};
    for(size_t i=0;i<sizeof values/sizeof *values;i++) {
        Arena a={0};AntigravityBlob gen={.data=generator(&a,usage(&a,10,values[i][0],values[i][1],values[i][2],(Str){0},(Str){0},(Str){0}),STR_LIT("synthetic-output"))};
        AntigravitySession raw={.id=STR_LIT("synthetic-output"),.generators=&gen,.generator_count=1},*rows[]={&raw};
        Corpus c={0};AntigravityStore s={0};PricingReport p={0};SessionModel *m=compose(&s,&c,rows,1,&p);
        ASSERT_EQ(1,m->unit_count);ASSERT_EQ(values[i][3],m->units[0].output);ASSERT_EQ(values[i][4],m->units[0].reasoning.value);
        ASSERT_EQ(values[i][1]>=0,m->units[0].reasoning.present);
        destroy(&s,&c,&p);arena_destroy(&a);
    }
}
TEST(antigravity_usage_transitive_cross_session_and_recomposition) {
    Arena a={0};Str r=STR_LIT("synthetic-r"),p=STR_LIT("synthetic-p"),m=STR_LIT("synthetic-m");
    AntigravityBlob gens[3]={
      {.data=generator(&a,usage(&a,10,4,1,3,r,(Str){0},(Str){0}),STR_LIT("synthetic-first"))},
      {.data=generator(&a,usage(&a,20,4,1,3,(Str){0},p,m),STR_LIT("synthetic-second"))},
      {.data=generator(&a,usage(&a,30,4,1,3,r,p,(Str){0}),STR_LIT("synthetic-third"))}};
    AntigravitySession raw[2]={{.id=STR_LIT("synthetic-owner"),.generators=gens,.generator_count=1},
      {.id=STR_LIT("synthetic-copy"),.generators=gens+1,.generator_count=2}},*rows[]={raw,raw+1};
    Corpus c={0};AntigravityStore s={0};PricingReport prices={0};SessionModel *first=compose(&s,&c,rows,2,&prices);
    SessionModel *second=omap_get(&c.sessions,raw[1].id);
    ASSERT_EQ(1,first->unit_count);ASSERT_EQ(30,first->units[0].input);ASSERT_EQ(0,second->unit_count);ASSERT_EQ(2,s.cross_session_duplicates);
    ASSERT_EQ(34,first->outside_usage->input+first->outside_usage->output);
    PriorityTurns priority={0};ASSERT_EQ(ERR_OK,compose_usage(&c,&priority).code);pricing_report_destroy(&prices);
    ASSERT_EQ(ERR_OK,antigravity_compose(&s,&c,NULL,&prices).code);ASSERT_EQ(1,first->unit_count);ASSERT_EQ(30,first->own_usage->input);ASSERT_EQ(2,s.cross_session_duplicates);
    destroy(&s,&c,&prices);arena_destroy(&a);
}
TEST(antigravity_usage_all_locations_partial_merge_and_invalid_isolation) {
    Arena a={0};JsonWriter chat={0},retry={0},gen={0},metadata={0};Str id=STR_LIT("synthetic-shared");
    Str direct=usage(&a,10,4,1,3,id,(Str){0},(Str){0}),later=usage(&a,40,4,1,3,id,(Str){0},(Str){0});
    msg(&chat,4,direct);msg(&retry,2,direct);msg(&chat,17,bytes(&retry));msg(&gen,1,bytes(&chat));
    msg(&metadata,9,direct);jsonw_free(&retry);msg(&retry,2,later);msg(&metadata,28,bytes(&retry));
    AntigravityBlob gens[4]={{.data=own(&a,&gen)},
      {.data=generator(&a,usage(&a,-1,1,-1,-1,(Str){0},(Str){0},(Str){0}),STR_LIT("synthetic-bad"))},
      {.data=generator(&a,usage(&a,INT64_MAX,1,-1,-1,(Str){0},(Str){0},(Str){0}),STR_LIT("synthetic-overflow"))},
      {.data=generator(&a,usage(&a,0,0,-1,-1,(Str){0},(Str){0},(Str){0}),STR_LIT("synthetic-empty"))}};
    AntigravityStep step={.idx=5,.metadata=own(&a,&metadata),.step_type_state=AG_SQL_INTEGER,.step_type=23}; /* checkpoint, cleared payload */
    AntigravitySession raw={.id=STR_LIT("synthetic-locations"),.generators=gens,.generator_count=4,.steps=&step,.step_count=1},*rows[]={&raw};
    Corpus c={0};AntigravityStore s={0};PricingReport prices={0};SessionModel *first=compose(&s,&c,rows,1,&prices);
    ASSERT_EQ(1,first->unit_count);ASSERT_EQ(40,first->units[0].input);ASSERT_EQ(2,s.invalid_numbers);ASSERT_EQ(3,s.requests_without_usage);
    ASSERT_TRUE(str_equal(STR_LIT("antigravity/unattributed"),first->units[0].model_raw));
    destroy(&s,&c,&prices);arena_destroy(&a);jsonw_free(&chat);jsonw_free(&retry);
}
TEST(antigravity_model_info_fallback) {
    Arena a={0};JsonWriter info={0},metadata={0},u={0};Str raw,normalized;
    msg(&info,8,STR_LIT("synthetic-model-name"));msg(&info,12,STR_LIT("synthetic-chat-model-name"));msg(&metadata,24,bytes(&info));
    ASSERT_EQ(ERR_OK,antigravity_model(&a,(Str){0},(Str){0},bytes(&metadata),(Str){0},&raw,&normalized).code);
    ASSERT_TRUE(str_equal(STR_LIT("synthetic-chat-model-name"),raw));
    num(&u,1,235);ASSERT_EQ(ERR_OK,antigravity_model(&a,(Str){0},bytes(&u),bytes(&metadata),STR_LIT("synthetic-previous"),&raw,&normalized).code);
    ASSERT_TRUE(str_equal(STR_LIT("synthetic-chat-model-name"),raw));
    jsonw_free(&u);num(&u,1,246);ASSERT_EQ(ERR_OK,antigravity_model(&a,(Str){0},bytes(&u),bytes(&metadata),(Str){0},&raw,&normalized).code);
    ASSERT_TRUE(str_equal(STR_LIT("gemini-2.5-pro"),raw));
    ASSERT_EQ(ERR_OK,antigravity_model(&a,STR_LIT("synthetic-response"),bytes(&u),bytes(&metadata),(Str){0},&raw,&normalized).code);
    ASSERT_TRUE(str_equal(STR_LIT("synthetic-response"),raw));
    jsonw_free(&info);jsonw_free(&metadata);msg(&info,8,STR_LIT("synthetic-model-only"));msg(&metadata,24,bytes(&info));
    ASSERT_EQ(ERR_OK,antigravity_model(&a,(Str){0},(Str){0},bytes(&metadata),(Str){0},&raw,&normalized).code);ASSERT_TRUE(str_equal(STR_LIT("synthetic-model-only"),raw));
    jsonw_free(&info);jsonw_free(&metadata);msg(&info,20,STR_LIT("synthetic-display"));msg(&info,23,STR_LIT("synthetic-vertex"));msg(&info,25,STR_LIT("synthetic-url"));msg(&metadata,24,bytes(&info));
    ASSERT_EQ(ERR_OK,antigravity_model(&a,(Str){0},(Str){0},bytes(&metadata),STR_LIT("synthetic-previous"),&raw,&normalized).code);ASSERT_TRUE(str_equal(STR_LIT("synthetic-previous"),raw));
    ASSERT_EQ(ERR_OK,antigravity_model(&a,(Str){0},(Str){0},bytes(&metadata),(Str){0},&raw,&normalized).code);ASSERT_TRUE(str_equal(STR_LIT("antigravity/unattributed"),raw));
    jsonw_free(&info);jsonw_free(&metadata);jsonw_free(&u);arena_destroy(&a);
}
TEST(antigravity_models_all_enum_oracle_expectations_and_normalization) {
    FILE *file=fopen("tests/fixtures/antigravity/model-oracle.json","rb");ASSERT_TRUE(file);ASSERT_EQ(0,fseek(file,0,SEEK_END));long length=ftell(file);ASSERT_TRUE(length>0);rewind(file);
    char *input=malloc((size_t)length);ASSERT_TRUE(input);ASSERT_EQ((size_t)length,fread(input,1,(size_t)length,file));fclose(file);
    JsonRead r=json_read((Str){input,(uint32_t)length},STRICT,JSON_CONSTANTS_REJECT,"synthetic.model_oracle");ASSERT_EQ(JSON_OK,r.status);
    yyjson_val *rows=yyjson_obj_get(yyjson_doc_get_root(r.doc),"rows"),*row;size_t i,n;ASSERT_EQ(1691,yyjson_arr_size(rows));
    yyjson_arr_foreach(rows,i,n,row){PyNum number={0};ASSERT_TRUE(json_number(yyjson_obj_get(row,"number"),"synthetic.enum",&number));Str got=antigravity_model_enum(number.i);yyjson_val *want=yyjson_obj_get(row,"slug");ASSERT_TRUE(str_equal((Str){yyjson_get_str(want),(uint32_t)yyjson_get_len(want)},got));}
    const char *cases[][2]={{" gemini-pro-default ","gemini-3.1-pro-preview"},{"gemini-pro-agent-thinking","gemini-3.1-pro-preview"},{"gemini-3.1-pro-high","gemini-3.1-pro-preview"},{"gemini-3.7-flash-safety-le","gemini-3.7-flash"},{"synthetic-tiered","synthetic"},{"synthetic-low","synthetic"},{"synthetic-thinking","synthetic"},{"synthetic-medium","synthetic"},{"synthetic-high","synthetic"},{"synthetic-trial","synthetic"},{"gpt-oss-120b-medium","gpt-oss-120b"}};
    Arena a={0};for(size_t j=0;j<sizeof cases/sizeof *cases;j++){Str out;ASSERT_EQ(ERR_OK,antigravity_normalize_model(&a,(Str){cases[j][0],(uint32_t)strlen(cases[j][0])},&out).code);ASSERT_TRUE(str_equal((Str){cases[j][1],(uint32_t)strlen(cases[j][1])},out));}
    arena_destroy(&a);json_read_free(&r);free(input);
}
TEST(antigravity_usage_step_matching_clocks_ttft_and_outside_ownership) {
    for(size_t cross=0;cross<2;cross++) {
        Arena a={0};JsonWriter meta={0},stamp={0},chat={0},gen={0},input={0};
        Str id=STR_LIT("synthetic-clock-copy"),u=usage(&a,10,4,0,4,id,(Str){0},(Str){0});
        num(&stamp,1,100);msg(&meta,1,bytes(&stamp));jsonw_free(&stamp);num(&stamp,1,200);msg(&meta,7,bytes(&stamp));jsonw_free(&stamp);num(&stamp,1,300);msg(&meta,8,bytes(&stamp));
        msg(&meta,12,STR_LIT("synthetic-execution"));msg(&meta,9,u);
        AntigravityStep steps[2]={{.idx=1,.step_type_state=AG_SQL_INTEGER,.step_type=14},{.idx=2,.metadata=own(&a,&meta)}};
        /* First unmatched generator owns outside-turn usage; a duplicate step
         * later improves its clock without adopting a same/foreign turn. */
        AntigravityBlob gens[3]={{.data=generator(&a,u,STR_LIT("synthetic-clock-model"))}};
        msg(&chat,4,usage(&a,11,5,-1,-1,STR_LIT("synthetic-other"),(Str){0},(Str){0}));
        jsonw_free(&stamp);num(&stamp,1,2);num(&stamp,2,500000000);msg(&chat,11,bytes(&stamp));msg(&gen,1,bytes(&chat));
        msg(&gen,4,STR_LIT("synthetic-execution"));num(&gen,2,1);gens[1].data=own(&a,&gen);
        jsonw_free(&chat);msg(&chat,4,usage(&a,12,6,-1,-1,STR_LIT("synthetic-third"),(Str){0},(Str){0}));msg(&gen,1,bytes(&chat));num(&gen,2,2);gens[2].data=own(&a,&gen);
        AntigravitySession raws[2]={{.id=STR_LIT("synthetic-clock-owner"),.generators=gens,.generator_count=cross?1:3,.steps=cross?NULL:steps,.step_count=cross?0:2},
          {.id=STR_LIT("synthetic-clock-sibling"),.generators=gens+1,.generator_count=2,.steps=steps,.step_count=2}},*rows[]={raws,raws+1};
        Corpus c={0};AntigravityStore s={0};PricingReport p={0};SessionModel *first=compose(&s,&c,rows,cross?2:1,&p);
        SessionModel *matched=cross?omap_get(&c.sessions,raws[1].id):first;
        ASSERT_EQ(300000,first->units[0].at_ms.value);ASSERT_FALSE(first->units[0].display_turn.n);
        ASSERT_EQ(14,first->outside_usage->input+first->outside_usage->output);
        ASSERT_EQ(2500,matched->turns[0].ttft_ms.value.i);ASSERT_TRUE(matched->turns[0].ttft_ms.present);
        ASSERT_EQ(2,matched->turns[0].usage->count);ASSERT_EQ(300000,matched->units[cross?0:1].at_ms.value);
        ASSERT_TRUE(str_equal(steps[1].turn,matched->units[cross?0:1].display_turn));
        destroy(&s,&c,&p);arena_destroy(&a);jsonw_free(&stamp);jsonw_free(&chat);jsonw_free(&input);
    }
}
TEST(antigravity_usage_split_messages_cache_conversion_and_unknown_clock) {
    Arena a={0};JsonWriter usage1={0},usage2={0},chat={0},gen={0};
    num(&usage1,2,13);num(&usage1,5,17);num(&usage2,4,19);num(&usage2,3,23);num(&usage2,9,0);
    msg(&chat,4,bytes(&usage1));msg(&chat,4,bytes(&usage2));msg(&gen,1,bytes(&chat));
    AntigravityBlob generator_row={.data=own(&a,&gen)};
    AntigravitySession raw={.id=STR_LIT("synthetic-split"),.generators=&generator_row,.generator_count=1},*rows[]={&raw};
    Corpus c={0};AntigravityStore s={0};PricingReport p={0};SessionModel *first=compose(&s,&c,rows,1,&p);
    ASSERT_EQ(1,first->unit_count);ASSERT_EQ(49,first->units[0].input);ASSERT_EQ(17,first->units[0].cached);ASSERT_EQ(19,first->units[0].cache_write);
    ASSERT_EQ(23,first->units[0].output);ASSERT_TRUE(first->units[0].reasoning.present);ASSERT_EQ(0,first->units[0].reasoning.value);ASSERT_EQ(1,s.unknown_clocks);ASSERT_FALSE(first->units[0].at_ms.present);
    destroy(&s,&c,&p);arena_destroy(&a);jsonw_free(&usage1);jsonw_free(&usage2);jsonw_free(&chat);
}
TEST(antigravity_catalog_provider_memo_and_unpriced_identity) {
    PricingReport p={0};UsageUnit claude={.model_raw=STR_LIT("claude-opus-4-6"),.input=19,.output=7};
    UsageUnit antigravity=claude;antigravity.model=STR_LIT("claude-opus-4-6");
    ASSERT_EQ(ERR_OK,claude_price_usage_units(&claude,1,NULL,&p).code);
    ASSERT_EQ(ERR_OK,catalog_price_usage_units(&antigravity,1,NULL,&p,STR_LIT("antigravity:"),true).code);
    ASSERT_TRUE(claude.has_cost&&antigravity.has_cost);ASSERT_EQ(claude.cost_usd,antigravity.cost_usd);
    ASSERT_TRUE(str_equal(STR_LIT("claude:bundled/claude-opus-4-6"),claude.period.model));
    ASSERT_TRUE(str_equal(STR_LIT("antigravity:bundled/claude-opus-4-6"),antigravity.period.model));
    UsageUnit unknown={.model_raw=STR_LIT("synthetic-raw-high"),.model=STR_LIT("synthetic-unknown"),.input=5,.output=3};
    ASSERT_EQ(ERR_OK,catalog_price_usage_units(&unknown,1,NULL,&p,STR_LIT("antigravity:"),true).code);ASSERT_FALSE(unknown.has_cost);
    ASSERT_TRUE(omap_get(&p.unpriced,STR_LIT("antigravity:bundled/synthetic-unknown")));
    pricing_report_destroy(&p);
}
TEST(antigravity_usage_clock_fallback_ladder) {
    const int64_t expected[]={300000,200000,100000,400000,500000};
    for(size_t which=0;which<5;which++) {
        Arena a={0};JsonWriter meta={0},stamp={0},chat={0},start={0},gen={0},trajectory={0};
        const uint32_t fields[]={8,7,1};const int seconds[]={300,200,100};
        for(size_t i=which;i<3;i++){num(&stamp,1,seconds[i]);msg(&meta,fields[i],bytes(&stamp));jsonw_free(&stamp);}
        if(which<4){num(&stamp,1,400);msg(&start,4,bytes(&stamp));msg(&chat,9,bytes(&start));jsonw_free(&stamp);}
        num(&stamp,1,500);msg(&trajectory,2,bytes(&stamp));
        msg(&chat,4,usage(&a,5,3,-1,-1,(Str){0},(Str){0},(Str){0}));msg(&gen,1,bytes(&chat));num(&gen,2,7);
        AntigravityStep step={.idx=7,.metadata=own(&a,&meta)};
        AntigravityBlob generator_row={.data=own(&a,&gen)},trajectory_row={.data=own(&a,&trajectory)};
        AntigravitySession raw={.id=STR_LIT("synthetic-fallback"),.steps=&step,.step_count=1,.generators=&generator_row,.generator_count=1,.metadata=&trajectory_row,.metadata_count=1},*rows[]={&raw};
        Corpus c={0};AntigravityStore s={0};PricingReport p={0};SessionModel *first=compose(&s,&c,rows,1,&p);
        ASSERT_EQ(1,first->unit_count);ASSERT_TRUE(first->units[0].at_ms.present);ASSERT_EQ(expected[which],first->units[0].at_ms.value);ASSERT_EQ(which==4,s.unknown_clocks);
        destroy(&s,&c,&p);arena_destroy(&a);jsonw_free(&stamp);jsonw_free(&chat);jsonw_free(&start);
    }
}
TEST(antigravity_usage_component_max_sum_overflow_retains_independent_events) {
    Arena a={0};AntigravityBlob gens[4]={0};const uint32_t components[]={2,5,4};
    for(size_t i=0;i<3;i++){JsonWriter u={0};num(&u,components[i],INT64_MAX-1);num(&u,3,1);msg(&u,11,STR_LIT("synthetic-overflow-merge"));gens[i].data=generator(&a,own(&a,&u),STR_LIT("synthetic-model"));}
    gens[3].data=generator(&a,usage(&a,5,3,-1,-1,STR_LIT("synthetic-independent"),(Str){0},(Str){0}),STR_LIT("synthetic-model"));
    AntigravitySession raw={.id=STR_LIT("synthetic-overflow-owner"),.generators=gens,.generator_count=4},*rows[]={&raw};
    Corpus c={0};AntigravityStore s={0};PricingReport p={0};SessionModel *first=compose(&s,&c,rows,1,&p);
    ASSERT_EQ(1,s.invalid_numbers);ASSERT_EQ(1,first->unit_count);ASSERT_EQ(5,first->units[0].input);ASSERT_EQ(3,first->units[0].output);
    destroy(&s,&c,&p);arena_destroy(&a);
}
TEST(antigravity_usage_each_direct_and_retry_location_is_independent) {
    Arena a={0};JsonWriter chat={0},retry={0},gen={0},meta={0};
    Str u[4];for(size_t i=0;i<4;i++)u[i]=usage(&a,(int64_t)(10*(i+1)),4,1,3,(Str){0},(Str){0},(Str){0});
    msg(&chat,4,u[0]);msg(&retry,2,u[1]);msg(&chat,17,bytes(&retry));msg(&gen,1,bytes(&chat));
    msg(&meta,9,u[2]);jsonw_free(&retry);msg(&retry,2,u[3]);msg(&meta,28,bytes(&retry));
    AntigravityStep step={.idx=3,.step_type_state=AG_SQL_INTEGER,.step_type=23,.metadata=own(&a,&meta)};
    AntigravityBlob generator_row={.data=own(&a,&gen)};
    AntigravitySession raw={.id=STR_LIT("synthetic-independent-locations"),.steps=&step,.step_count=1,.generators=&generator_row,.generator_count=1},*rows[]={&raw};
    Corpus c={0};AntigravityStore s={0};PricingReport p={0};SessionModel *first=compose(&s,&c,rows,1,&p);
    ASSERT_EQ(4,first->unit_count);ASSERT_EQ(100,first->own_usage->input);ASSERT_EQ(16,first->own_usage->output);ASSERT_EQ(4,first->own_usage->reasoning);ASSERT_EQ(0,s.requests_without_usage);
    destroy(&s,&c,&p);arena_destroy(&a);jsonw_free(&chat);jsonw_free(&retry);
}
TEST(antigravity_usage_partial_output_reconciles_before_component_merge) {
    /* Fresh isolated native oracle: tuples are total/thinking/visible;
     * -1 denotes absent. Output expectations include reasoning. */
    const int cases[][8]={{10,8,-1,10,2,-1,16,8},{10,-1,-1,0,8,2,18,8},
      {5,7,3,20,2,18,25,7},{0,8,-1,10,2,-1,16,8}};
    for(size_t i=0;i<sizeof cases/sizeof *cases;i++) {
        Arena a={0};AntigravityBlob gens[2]={0};
        for(size_t j=0;j<2;j++)gens[j].data=generator(&a,usage(&a,10,cases[i][j*3],cases[i][j*3+1],cases[i][j*3+2],STR_LIT("synthetic-partial"),(Str){0},(Str){0}),STR_LIT("synthetic-model"));
        AntigravitySession raw={.id=STR_LIT("synthetic-partial-owner"),.generators=gens,.generator_count=2},*rows[]={&raw};
        Corpus c={0};AntigravityStore s={0};PricingReport p={0};SessionModel *first=compose(&s,&c,rows,1,&p);
        ASSERT_EQ(1,first->unit_count);ASSERT_EQ(10,first->units[0].input);ASSERT_EQ(cases[i][6],first->units[0].output);ASSERT_EQ(cases[i][7],first->units[0].reasoning.value);
        destroy(&s,&c,&p);arena_destroy(&a);
    }
}
TEST(antigravity_pinned_effort_aliases_after_routing_suffix) {
    const char *models[]={"gemini-3.1-pro-high-thinking","gemini-3.1-pro-low-thinking",
      "gemini-3.1-pro-high-tiered","gemini-3.1-pro-low-tiered",
      "gemini-3.1-pro-high-low","gemini-3.1-pro-low-low"};
    Arena a={0};for(size_t i=0;i<sizeof models/sizeof *models;i++){
        Str out={0};ASSERT_EQ(ERR_OK,antigravity_normalize_model(&a,(Str){models[i],(uint32_t)strlen(models[i])},&out).code);
        ASSERT_TRUE(str_equal(STR_LIT("gemini-3.1-pro-preview"),out));
    }
    arena_destroy(&a);
}
TEST(antigravity_clock_invalid_wire_never_creates_epoch) {
    const Str bad[]={STR_LIT("\42\1\200"),STR_LIT("\42\3\12\1x"),STR_LIT("\42\3\22\1x"),
      STR_LIT("\40\0"),STR_LIT("\42\0\200"),STR_LIT("\42\5\12\1x\10\0")};
    Arena a={0};for(size_t i=0;i<sizeof bad/sizeof *bad;i++){
        MaybeMs at={0};ASSERT_EQ(ERR_OK,antigravity_clock(&a,bad[i],4,&at).code);ASSERT_FALSE(at.present);
        at=(MaybeMs){true,77};ASSERT_EQ(ERR_OK,antigravity_clock(&a,bad[i],4,&at).code);ASSERT_TRUE(at.present);ASSERT_EQ(77,at.value);
    }
    arena_destroy(&a);
}
TEST(antigravity_clock_empty_defaults_and_split_singular_timestamp) {
    Arena a={0};MaybeMs at={0};
    ASSERT_EQ(ERR_OK,antigravity_clock(&a,STR_LIT("\42\0"),4,&at).code);ASSERT_TRUE(at.present);ASSERT_EQ(0,at.value);
    at=(MaybeMs){0};ASSERT_EQ(ERR_OK,antigravity_clock(&a,STR_LIT("\42\4\10\0\20\0"),4,&at).code);ASSERT_TRUE(at.present);ASSERT_EQ(0,at.value);
    JsonWriter parent={0},part={0};num(&part,1,1);msg(&parent,4,bytes(&part));jsonw_free(&part);num(&part,2,500000000);msg(&parent,4,bytes(&part));jsonw_free(&part);num(&part,1,2);msg(&parent,4,bytes(&part));
    at=(MaybeMs){0};ASSERT_EQ(ERR_OK,antigravity_clock(&a,bytes(&parent),4,&at).code);ASSERT_TRUE(at.present);ASSERT_EQ(2500,at.value);
    jsonw_free(&parent);jsonw_free(&part);arena_destroy(&a);
}
