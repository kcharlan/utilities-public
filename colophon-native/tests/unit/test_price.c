#include "runner.h"
#include "price/cost.h"
#include "util/json_read.h"
#include "price/catalog.h"
#include "price/ledger.h"
#include <pthread.h>
#include <stdlib.h>
#include <stdio.h>
#include <unistd.h>
#include <math.h>
#include "cli/summary.h"
#include "util/json_number.h"
#include "gen/assets.h"

TEST(shared_normalization_memo_preserves_raw_key_identity_and_durable_values) {
    Arena arena={0};Omap memo={0};Str first,repeat,alias;
    ASSERT_EQ(ERR_OK,normalize_codex_model_memo(&arena,&memo,STR_LIT("gpt-5.6"),&first).code);
    ASSERT_EQ(ERR_OK,normalize_codex_model_memo(&arena,&memo,STR_LIT("gpt-5.6"),&repeat).code);
    ASSERT_TRUE(first.p==repeat.p);ASSERT_EQ(1,memo.size);
    ASSERT_EQ(ERR_OK,normalize_codex_model_memo(&arena,&memo,STR_LIT("gpt-daybreak-blue-latest"),&alias).code);
    ASSERT_EQ(2,memo.size);ASSERT_TRUE(str_equal(first,alias));
    omap_destroy(&memo);ASSERT_TRUE(str_equal(first,STR_LIT("gpt-5.6-sol")));
    ASSERT_TRUE(str_equal(alias,STR_LIT("gpt-5.6-sol")));arena_destroy(&arena);
}
TEST(empty_optional_usage_summary_keeps_source_zero_cost) {
    JsonWriter writer={0};compose_summary_json(&writer,NULL);
    ASSERT_EQ(ERR_OK,writer.error.code);
    JsonRead read=json_read((Str){writer.data,(uint32_t)writer.length},STR,JSON_CONSTANTS_REJECT,"test.price.empty_summary");
    ASSERT_EQ(JSON_OK,read.status);
    yyjson_val *cost=obj_get_last(yyjson_doc_get_root(read.doc),STR_LIT("cost_usd"));
    PyNum number;ASSERT_TRUE(json_number(cost,"test.price.empty_summary.cost",&number));
    ASSERT_TRUE(number.is_float);ASSERT_EQ(0.0,number.f);
    json_read_free(&read);jsonw_free(&writer);
    writer=(JsonWriter){0};UsageSummary unavailable={0};compose_summary_json(&writer,&unavailable);
    read=json_read((Str){writer.data,(uint32_t)writer.length},STR,JSON_CONSTANTS_REJECT,"test.price.unavailable_summary");
    ASSERT_EQ(JSON_OK,read.status);
    ASSERT_TRUE(yyjson_is_null(obj_get_last(yyjson_doc_get_root(read.doc),STR_LIT("cost_usd"))));
    json_read_free(&read);jsonw_free(&writer);
}
TEST(price_unicode_date_and_alias_rate_paths_survive_sanitized_owners) {
    Str inputs[]={STR_LIT("gpt-5.4-٢٠٢٦-٠١-٠٢"),STR_LIT("gpt-5.4-2026-01-02́"),STR_LIT("gpt-5.5-2026-04-23")};
    for(size_t i=0;i<3;i++) {
        Arena arena={0};ModelCandidates candidates={0};PricingTargets targets={0};PriceEntry rates;bool found=false;
        Err e=models_dev_candidates(&arena,inputs[i],&candidates);ASSERT_EQ(ERR_OK,e.code);
        e=codex_models_dev_pricing_targets(&arena,inputs[i],&targets);ASSERT_EQ(ERR_OK,e.code);
        e=resolve_rates(inputs[i],NULL,&rates,&found);ASSERT_EQ(ERR_OK,e.code);ASSERT_TRUE(found);
        ASSERT_TRUE(isfinite(rates.standard.input.f));ASSERT_TRUE(isfinite(rates.standard.output.f));
        ASSERT_TRUE(isfinite(rates.standard.cached_input.f));ASSERT_TRUE(isfinite(rates.standard.cache_write.f));
        if(rates.has_extended){ASSERT_TRUE(isfinite(rates.extended.input.f));ASSERT_TRUE(isfinite(rates.extended.output.f));ASSERT_TRUE(isfinite(rates.extended.cached_input.f));ASSERT_TRUE(isfinite(rates.extended.cache_write.f));}
        ModelsDevIndex index={0};CatalogLookup lookup={0};
        e=models_dev_pricing(&index,STR_LIT("openai"),inputs[i],&lookup);ASSERT_EQ(ERR_OK,e.code);
        ASSERT_TRUE(isfinite(rates.standard.input.f));ASSERT_TRUE(isfinite(rates.standard.output.f));
        JsonWriter writer={0};jsonw_string(&writer,normalize_codex_model(inputs[i]));ASSERT_EQ(ERR_OK,writer.error.code);
        for(size_t j=0;j<candidates.count;j++){jsonw_string(&writer,candidates.items[j]);ASSERT_EQ(ERR_OK,writer.error.code);}
        for(size_t j=0;j<targets.count;j++){jsonw_string(&writer,targets.model[j]);ASSERT_EQ(ERR_OK,writer.error.code);}
        catalog_lookup_json(&writer,&lookup);ASSERT_EQ(ERR_OK,writer.error.code);
        price_entry_json(&writer,&rates);ASSERT_EQ(ERR_OK,writer.error.code);
        double multiplier=codex_api_fast_multiplier(inputs[i]);if(multiplier)jsonw_double(&writer,multiplier);ASSERT_EQ(ERR_OK,writer.error.code);
        models_dev_destroy(&index);
        jsonw_free(&writer);arena_destroy(&arena);
    }
}
TEST(summary_nonfinite_result_keeps_source_sum_format) {
    Corpus corpus={0};SessionModel session={.kind=STR_LIT("session")};
    UsageUnit units[2]={{.has_cost=true},{.has_cost=true,.cost_usd=1}};
    PriceEntry rates={.standard={.input={.is_float=true,.f=1e308}}};
    units[0].cost_usd=cost_usd(&rates,INT64_MAX,0,0);ASSERT_TRUE(isinf(units[0].cost_usd));
    session.units=units;session.unit_count=2;ASSERT_EQ(ERR_OK,omap_put(&corpus.sessions,STR_LIT("synthetic-overflow"),&session).code);
    RuntimeLedger ledger={.available=true};PricingReport pricing={0};CatalogResult catalog={0};CodexMetadata metadata={0};ScanResult scan={0};CorpusStrings errors={0};
    PayloadInputs in={.corpus=&corpus,.ledger=&ledger,.pricing=&pricing,.catalog=&catalog,.metadata=&metadata,.scan=&scan,.workspace_errors=&errors};
    FILE *capture=tmpfile();ASSERT_TRUE(capture!=NULL);fflush(stdout);int saved=dup(STDOUT_FILENO);ASSERT_TRUE(saved>=0);ASSERT_TRUE(dup2(fileno(capture),STDOUT_FILENO)>=0);
    Err result=summary_run("synthetic-output",0,&in);fflush(stdout);ASSERT_TRUE(dup2(saved,STDOUT_FILENO)>=0);close(saved);
    rewind(capture);char text[512];size_t n=fread(text,1,sizeof text-1,capture);text[n]=0;fclose(capture);omap_destroy(&corpus.sessions);
    ASSERT_EQ(ERR_OK,result.code);ASSERT_TRUE(strstr(text,"$inf est.")!=NULL);
}
static void *catalog_deep_owned(void *unused) {
    (void)unused;
    const char *prefix="{\"openai\":{\"models\":{\"synthetic-owner\":{\"id\":\"synthetic-owner\",\"cost\":{\"input\":2,\"output\":7}}}},\"ignored\":";
    size_t depth=9998,length=strlen(prefix)+depth*2+2;
    char *raw=malloc(length);ASSERT_TRUE(raw!=NULL);memcpy(raw,prefix,strlen(prefix));
    memset(raw+strlen(prefix),'[',depth);raw[strlen(prefix)+depth]='0';
    memset(raw+strlen(prefix)+depth+1,']',depth);raw[length-1]='}';
    yyjson_doc *catalog=NULL;ASSERT_EQ(ERR_OK,catalog_decode((Str){raw,(uint32_t)length},&catalog).code);ASSERT_TRUE(catalog!=NULL);free(raw);
    ModelsDevIndex index={0};ASSERT_EQ(ERR_OK,models_dev_index(yyjson_doc_get_root(catalog),&index).code);
    yyjson_doc_free(catalog);CatalogLookup lookup={0};ASSERT_EQ(ERR_OK,models_dev_pricing(&index,STR_LIT("openai"),STR_LIT("synthetic-owner"),&lookup).code);
    ASSERT_TRUE(lookup.model!=NULL);ASSERT_EQ(2.0,lookup.model->rates[0]);
    models_dev_destroy(&index);return NULL;
}
TEST(catalog_decoder_deep_thread_and_independent_index_owner) {
    pthread_attr_t attr;ASSERT_EQ(0,pthread_attr_init(&attr));ASSERT_EQ(0,pthread_attr_setstacksize(&attr,512*1024));
    pthread_t thread;ASSERT_EQ(0,pthread_create(&thread,&attr,catalog_deep_owned,NULL));ASSERT_EQ(0,pthread_join(thread,NULL));pthread_attr_destroy(&attr);
}
TEST(catalog_lookup_memo_interns_repeated_candidate_and_retains_raw_provider_rules) {
    JsonRead read=json_read(STR_LIT("{\"openai\":{\"models\":{\"synthetic-cache\":{\"id\":\"synthetic-id\",\"cost\":{\"input\":2,\"output\":7}}}}}"),BYTES,JSON_CONSTANTS_REJECT,"test.price.memo");
    ModelsDevIndex index={0};ASSERT_EQ(ERR_OK,models_dev_index(yyjson_doc_get_root(read.doc),&index).code);json_read_free(&read);
    CatalogLookup first={0},second={0},miss={0};
    ASSERT_EQ(ERR_OK,models_dev_pricing(&index,STR_LIT("openai"),STR_LIT("synthetic-cache"),&first).code);
    ASSERT_EQ(ERR_OK,models_dev_pricing(&index,STR_LIT("openai"),STR_LIT("synthetic-cache"),&second).code);
    ASSERT_TRUE(first.model!=NULL&&first.model==second.model&&first.identity.p==second.identity.p);
    ASSERT_EQ(ERR_OK,models_dev_pricing(&index,STR_LIT("OPENAI"),STR_LIT("synthetic-id"),&second).code);ASSERT_TRUE(second.model==first.model);
    ASSERT_EQ(ERR_OK,models_dev_pricing(&index,STR_LIT("synthetic-provider"),STR_LIT("synthetic-cache"),&miss).code);ASSERT_TRUE(miss.model==NULL);
    ASSERT_EQ(ERR_OK,models_dev_pricing(&index,STR_LIT("openai"),STR_LIT("synthetic-absent"),&miss).code);ASSERT_TRUE(miss.model==NULL);
    ASSERT_EQ(ERR_OK,models_dev_pricing(&index,STR_LIT("openai"),STR_LIT("synthetic-absent"),&miss).code);ASSERT_TRUE(miss.model==NULL);
    ASSERT_STREQ("synthetic-cache",index.models.first->key.p);models_dev_destroy(&index);
}
TEST(catalog_normalization_memo_owns_raw_keys_and_results) {
    ModelsDevIndex index={0};Str first,second;
    char raw[]="synthetic-normalization";
    ASSERT_EQ(ERR_OK,models_dev_normalize(&index,(Str){raw,sizeof raw-1},&first).code);
    ASSERT_EQ(ERR_OK,models_dev_normalize(&index,STR_LIT("synthetic-normalization"),&second).code);
    ASSERT_TRUE(first.p==second.p);raw[0]='X';ASSERT_STREQ("synthetic-normalization",first.p);
    ASSERT_EQ(1,index.normalizations.size);
    ASSERT_EQ(ERR_OK,models_dev_normalize(&index,STR_LIT("gpt-5.6"),&second).code);
    ASSERT_TRUE(str_equal(normalize_codex_model(STR_LIT("gpt-5.6")),second));ASSERT_EQ(2,index.normalizations.size);
    models_dev_destroy(&index);
}
TEST(price_wide_composed_token_count_retains_positive_cost) {
    PriceEntry entry={.standard={.input={.i=1}}};
    __int128 input=(__int128)INT64_MAX+1;
    ASSERT_TRUE(cost_usd(&entry,input,0,0)==0x1p63/1000000.0);
    PricePriority priority={.present=true,.capped=true,.cap=INT64_MAX,.multiplier={.i=2}};
    double cost;
    ASSERT_FALSE(priority_cost_usd(&entry,&priority,input,0,0,&cost));
}
TEST(price_repeated_units_do_not_grow_index_scratch_arena) {
    JsonRead read=json_read(STR_LIT("{\"openai\":{\"models\":{\"gpt-5.6-sol\":{\"id\":\"gpt-5.6-sol\",\"cost\":{\"input\":2,\"output\":7}}}}}"),BYTES,JSON_CONSTANTS_REJECT,"test.price.memo");
    ModelsDevIndex index={0};ASSERT_EQ(ERR_OK,models_dev_index(yyjson_doc_get_root(read.doc),&index).code);json_read_free(&read);
    PriceHistory history={0};PricingReport report={0};PriorityEntry trace={.model=STR_LIT("openai/gpt-5.6-sol")};
    UsageUnit unit={.model=STR_LIT("gpt-5.6-sol"),.model_raw=STR_LIT("openai/gpt-5.6-sol"),.input=1,.priority=&trace,.priority_fields=PRIORITY_MODEL};
    ASSERT_EQ(ERR_OK,price_usage_units(&unit,1,&history,&index,true,&report).code);
    ArenaChunk *head=index.arena.head;
    for(size_t i=0;i<10000;i++)ASSERT_EQ(ERR_OK,price_usage_units(&unit,1,&history,&index,true,&report).code);
    ASSERT_TRUE(head==index.arena.head);pricing_report_destroy(&report);models_dev_destroy(&index);
}
TEST(price_runtime_rejects_first_constant_without_losing_kind) {
    JsonRead read=json_read(STR_LIT("{\"a\":Infinity,\"b\":[NaN,-Infinity]}"),STRICT,JSON_CONSTANTS_REJECT,"test.price.constants");
    ASSERT_EQ(JSON_INVALID,read.status);ASSERT_EQ(2,read.stats.first_constant);json_read_free(&read);
}
TEST(price_wide_non_power_totals_keep_source_halfway_rounding) {
    PriceEntry entry={.standard={.input={.i=1},.cached_input={.i=3},.output={.i=7}}};
    /* Pinned source cost_usd oracle, integer subtraction precedes conversion. */
    int64_t offsets[]={1042,1043,1044,3090,3091,3092};
    double expected[]={0x1.0c6f7a0b5ed8dp+43,0x1.0c6f7a0b5ed8dp+43,
        0x1.0c6f7a0b5ed8ep+43,0x1.0c6f7a0b5ed8ep+43,
        0x1.0c6f7a0b5ed8fp+43,0x1.0c6f7a0b5ed8fp+43};
    for(size_t i=0;i<6;i++)ASSERT_EQ(expected[i],cost_usd(&entry,((__int128)1<<63)+offsets[i],19,37));
    ASSERT_EQ(0x1.0c6f7a0b5ed8fp+45,cost_usd(&entry,((__int128)1<<65)+12345,19,37));
}

static PriceEntry resolve_with_catalog(const char *catalog, const char *model, bool *found) {
    JsonRead read=json_read((Str){catalog,(uint32_t)strlen(catalog)},BYTES,JSON_CONSTANTS_REJECT,"test.price.tier");
    ASSERT_TRUE(read.status==JSON_OK);
    ModelsDevIndex index={0};ASSERT_EQ(ERR_OK,models_dev_index(yyjson_doc_get_root(read.doc),&index).code);
    PriceEntry rates;ASSERT_EQ(ERR_OK,resolve_rates((Str){model,(uint32_t)strlen(model)},&index,&rates,found).code);
    models_dev_destroy(&index);json_read_free(&read);return rates;
}
#define SYNTHETIC_LONG "\"context_over_200k\":{\"input\":4,\"output\":15,\"cache_read\":0.2,\"cache_write\":5}"
#define SYNTHETIC_COST "\"input\":2,\"output\":10,\"cache_read\":0.1,\"cache_write\":2.5"
TEST(catalog_context_tier_sets_threshold_when_not_bundled) {
    bool found=false;
    PriceEntry rates=resolve_with_catalog("{\"openai\":{\"models\":{\"gpt-synthetic-tier\":{\"id\":\"gpt-synthetic-tier\",\"cost\":{" SYNTHETIC_COST "," SYNTHETIC_LONG
        ",\"tiers\":[{\"input\":4,\"output\":15,\"cache_read\":0.2,\"cache_write\":5,\"tier\":{\"type\":\"context\",\"size\":272000}}]}}}}}","gpt-synthetic-tier",&found);
    ASSERT_TRUE(found);ASSERT_TRUE(rates.has_extended);ASSERT_EQ(272000,rates.threshold);
}
TEST(catalog_tier_rate_mismatch_uses_bundled_then_200000) {
    bool found=false;
    const char *mismatch="{\"openai\":{\"models\":{\"%s\":{\"id\":\"%s\",\"cost\":{" SYNTHETIC_COST "," SYNTHETIC_LONG
        ",\"tiers\":[{\"input\":5,\"output\":15,\"cache_read\":0.2,\"cache_write\":5,\"tier\":{\"type\":\"context\",\"size\":300000}}]}}}}}";
    char catalog[1024];
    snprintf(catalog,sizeof catalog,mismatch,"gpt-synthetic-tier","gpt-synthetic-tier");
    ASSERT_EQ(200000,resolve_with_catalog(catalog,"gpt-synthetic-tier",&found).threshold);ASSERT_TRUE(found);
    snprintf(catalog,sizeof catalog,mismatch,"gpt-6.1-sol","gpt-6.1-sol");
    ASSERT_EQ(272000,resolve_with_catalog(catalog,"gpt-6.1-sol",&found).threshold);ASSERT_TRUE(found);
}
TEST(catalog_matching_tier_precedes_bundled_threshold) {
    bool found=false;
    PriceEntry rates=resolve_with_catalog("{\"openai\":{\"models\":{\"gpt-5.4\":{\"id\":\"gpt-5.4\",\"cost\":{\"input\":2.5,\"output\":15,\"cache_read\":0.25,"
        "\"context_over_200k\":{\"input\":5,\"output\":22.5,\"cache_read\":0.5},"
        "\"tiers\":[{\"input\":5,\"output\":22.5,\"cache_read\":0.5,\"tier\":{\"type\":\"context\",\"size\":300000}}]}}}}}","gpt-5.4",&found);
    ASSERT_TRUE(found);ASSERT_EQ(300000,rates.threshold);
}
TEST(catalog_malformed_tiers_reject_model) {
    const char *bad[]={
        "{\"openai\":{\"models\":{\"gpt-synthetic-tier\":{\"id\":\"gpt-synthetic-tier\",\"cost\":{" SYNTHETIC_COST ",\"tiers\":\"synthetic\"}}}}}",
        "{\"openai\":{\"models\":{\"gpt-synthetic-tier\":{\"id\":\"gpt-synthetic-tier\",\"cost\":{" SYNTHETIC_COST ",\"tiers\":[{\"tier\":{\"type\":\"context\",\"size\":\"272000\"}}]}}}}}",
        "{\"openai\":{\"models\":{\"gpt-synthetic-tier\":{\"id\":\"gpt-synthetic-tier\",\"cost\":{" SYNTHETIC_COST ",\"tiers\":[{\"tier\":{\"size\":272000}}]}}}}}",
        "{\"openai\":{\"models\":{\"gpt-synthetic-tier\":{\"id\":\"gpt-synthetic-tier\",\"cost\":{" SYNTHETIC_COST ",\"tiers\":[{\"input\":\"4\"}]}}}}}"};
    for(size_t i=0;i<sizeof bad/sizeof *bad;i++) {
        JsonRead read=json_read((Str){bad[i],(uint32_t)strlen(bad[i])},BYTES,JSON_CONSTANTS_REJECT,"test.price.bad_tier");
        ModelsDevIndex index={0};ASSERT_EQ(ERR_OK,models_dev_index(yyjson_doc_get_root(read.doc),&index).code);
        CatalogLookup lookup={0};ASSERT_EQ(ERR_OK,models_dev_pricing(&index,STR_LIT("openai"),STR_LIT("gpt-synthetic-tier"),&lookup).code);
        ASSERT_TRUE(lookup.model==NULL);models_dev_destroy(&index);json_read_free(&read);
    }
}
TEST(curated_seed_has_no_200000_long_context_threshold) {
    JsonRead read=json_read((Str){(const char *)cp_asset_curated_price_history,(uint32_t)cp_asset_curated_price_history_len},STR,JSON_CONSTANTS_REJECT,"test.price.seed");
    ASSERT_TRUE(read.status==JSON_OK);
    yyjson_val *entries=yyjson_obj_get(yyjson_doc_get_root(read.doc),"entries");size_t idx,max;yyjson_val *entry;
    yyjson_arr_foreach(entries,idx,max,entry) {
        yyjson_val *lc=yyjson_obj_get(entry,"long_context");PyNum threshold;
        /* json_read keeps numbers raw (YYJSON_READ_NUMBER_AS_RAW); decode through json_number. */
        if(yyjson_is_obj(lc)){ASSERT_TRUE(json_number(yyjson_obj_get(lc,"threshold"),"test.price.seed",&threshold));
            ASSERT_FALSE(threshold.is_float);ASSERT_EQ(272000,threshold.i);}
    }
    json_read_free(&read);
}
TEST(bundled_new_models_resolve_offline_with_272000_threshold) {
    const char *models[]={"gpt-6.1-sol","gpt-6-sol","gpt-6-luna","gpt-5.4-pro","gpt-5.5-pro"};
    for(size_t i=0;i<sizeof models/sizeof *models;i++){PriceEntry rates;bool found=false;
        ASSERT_EQ(ERR_OK,resolve_rates((Str){models[i],(uint32_t)strlen(models[i])},NULL,&rates,&found).code);
        ASSERT_TRUE(found);ASSERT_TRUE(rates.has_extended);ASSERT_EQ(272000,rates.threshold);}
}

/* Real raw decoder coverage: dropping tier validation would admit corrupt models. */
static void assert_raw_tier_rejected(const char *cost) {
    char raw[2048];snprintf(raw,sizeof raw,"{\"openai\":{\"models\":{\"gpt-synthetic-tier\":{\"id\":\"gpt-synthetic-tier\",\"cost\":{\"input\":2,\"output\":10,%s}}}}}",cost);
    yyjson_doc *catalog=NULL;ASSERT_EQ(ERR_OK,catalog_decode((Str){raw,(uint32_t)strlen(raw)},&catalog).code);
    ASSERT_TRUE(catalog!=NULL);ModelsDevIndex index={0};ASSERT_EQ(ERR_OK,models_dev_index(yyjson_doc_get_root(catalog),&index).code);
    yyjson_doc_free(catalog);CatalogLookup lookup={0};ASSERT_EQ(ERR_OK,models_dev_pricing(&index,STR_LIT("openai"),STR_LIT("gpt-synthetic-tier"),&lookup).code);
    ASSERT_TRUE(lookup.model==NULL);models_dev_destroy(&index);
}
TEST(catalog_raw_tier_rate_keys_reject_invalid_unicode) {
    assert_raw_tier_rejected("\"tiers\":[{\"\\ud800\":0}]");
}
TEST(catalog_raw_context_tier_keys_reject_invalid_unicode) {
    assert_raw_tier_rejected("\"tiers\":[{\"tier\":{\"type\":\"context\",\"size\":272000,\"\\ud800\":0}}]");
}
TEST(catalog_raw_context_tier_type_rejects_invalid_unicode) {
    assert_raw_tier_rejected("\"tiers\":[{\"tier\":{\"type\":\"\\ud800\",\"size\":272000}}]");
}
TEST(catalog_raw_tier_rates_reject_nonzero_underflow) {
    assert_raw_tier_rejected("\"tiers\":[{\"input\":1e-999}]");
}
TEST(catalog_raw_extended_tier_keys_reject_invalid_unicode) {
    assert_raw_tier_rejected("\"context_over_200k\":{\"tier\":{\"type\":\"context\",\"size\":272000,\"\\ud800\":0}}");
}
TEST(catalog_raw_extended_tier_type_rejects_invalid_unicode) {
    assert_raw_tier_rejected("\"context_over_200k\":{\"tier\":{\"type\":\"\\ud800\",\"size\":272000}}");
}
TEST(catalog_tiers_validate_every_element_after_first_match) {
    assert_raw_tier_rejected(SYNTHETIC_LONG ",\"tiers\":[{\"input\":4,\"output\":15,\"cache_read\":0.2,\"cache_write\":5,\"tier\":{\"type\":\"context\",\"size\":272000}},null]");
}
TEST(catalog_context_tier_first_match_presence_and_extended_tier_rules) {
    const char *tiers="\"tiers\":[{\"input\":4,\"output\":15,\"cache_read\":0.2,\"tier\":{\"type\":\"context\",\"size\":300000}},"
        "{\"input\":4,\"output\":15,\"cache_read\":0.2,\"cache_write\":5,\"tier\":{\"type\":\"context\",\"size\":272000}},"
        "{\"input\":4,\"output\":15,\"cache_read\":0.2,\"cache_write\":5,\"tier\":{\"type\":\"context\",\"size\":400000}}]";
    char raw[2048];bool found=false;
    snprintf(raw,sizeof raw,"{\"openai\":{\"models\":{\"gpt-synthetic-tier\":{\"id\":\"gpt-synthetic-tier\",\"cost\":{" SYNTHETIC_COST "," SYNTHETIC_LONG ",%s}}}}}",tiers);
    ASSERT_EQ(272000,resolve_with_catalog(raw,"gpt-synthetic-tier",&found).threshold);ASSERT_TRUE(found);
    snprintf(raw,sizeof raw,"{\"openai\":{\"models\":{\"gpt-synthetic-tier\":{\"id\":\"gpt-synthetic-tier\",\"cost\":{" SYNTHETIC_COST ",\"context_over_200k\":{\"input\":4,\"output\":15,\"cache_read\":0.2,\"cache_write\":5,\"tier\":{\"type\":\"context\",\"size\":272000}},%s}}}}}",tiers);
    ASSERT_EQ(200000,resolve_with_catalog(raw,"gpt-synthetic-tier",&found).threshold);ASSERT_TRUE(found);
}
