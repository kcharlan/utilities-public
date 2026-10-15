#include "price/claude_cost.h"
#include "price/claude_model.h"
#include "util/json_read.h"
#include "runner.h"
#include <math.h>
#define CLOSE(a,b) ASSERT_TRUE(fabs((a)-(b))<1e-10)
static UsageUnit unit(Str model,__int128 input,int64_t timestamp) {
    return (UsageUnit){.model_raw=model,.model=model,.input=input,.output=7,
        .timestamp_ms={true,timestamp},.at_ms={true,timestamp}};
}
TEST(claude_cost_bundled_threshold_cutoff_and_unknown) {
    UsageUnit units[]={unit(STR_LIT("claude-opus-4-6"),200000,1773359999999),
        unit(STR_LIT("claude-opus-4-6"),200001,1773359999999),
        unit(STR_LIT("claude-opus-4-6"),200001,1773360000000),
        unit(STR_LIT("claude-sonnet-4-6"),200001,1773359999999),
        unit(STR_LIT("claude-sonnet-4-6"),200001,1773360000000),
        unit(STR_LIT("claude-sonnet-4-5"),200001,1773360000000),
        unit(STR_LIT("synthetic-unpriced-model"),19,0)};
    PricingReport report={0};ASSERT_EQ(ERR_OK,claude_price_usage_units(units,7,NULL,&report).code);
    CLOSE(1.000175,units[0].cost_usd);CLOSE(2.0002725,units[1].cost_usd);
    CLOSE(1.00018,units[2].cost_usd);CLOSE(1.2001635,units[3].cost_usd);
    CLOSE(.600108,units[4].cost_usd);CLOSE(1.2001635,units[5].cost_usd);
    ASSERT_FALSE(units[6].has_cost);ASSERT_EQ(1,report.unpriced.size);
    ASSERT_EQ(2,((PricingPeriods *)omap_get(&report.periods,STR_LIT("claude:bundled/claude-opus-4-6")))->count);
    pricing_report_destroy(&report);
}
TEST(claude_cost_components_clamp_and_whole_context) {
    PriceEntry rates={.standard={.input={.i=11},.cached_input={.i=7},.cache_write={.i=13},.output={.i=17}},
        .extended={.input={.i=23},.cached_input={.i=19},.cache_write={.i=29},.output={.i=31}},.has_extended=true,.threshold=41};
    UsageUnit u={.input=41,.cached=13,.cache_write=11,.cache_write_1h=5,.output=7};
    CLOSE((17.*11+13*7+6*13+5*22+7*17)/1e6,claude_cost_usd(&rates,&u));
    u.input++;CLOSE((18.*23+13*19+6*29+5*46+7*31)/1e6,claude_cost_usd(&rates,&u));
    u.cache_write_1h=99;CLOSE((18.*23+13*19+11*46+7*31)/1e6,claude_cost_usd(&rates,&u));
}
TEST(claude_model_normalization_and_fast_overrides) {
    Arena arena={0};Str normalized;
    ASSERT_EQ(ERR_OK,normalize_claude_model(&arena,STR_LIT(" anthropic.eu.claude-opus-4-6-20260205-v1:0 \n"),&normalized).code);
    ASSERT_TRUE(str_equal(normalized,STR_LIT("claude-opus-4-6")));
    ASSERT_EQ(ERR_OK,normalize_claude_model(&arena,STR_LIT("claude-synthetic-20990101"),&normalized).code);
    ASSERT_TRUE(str_equal(normalized,STR_LIT("claude-synthetic-20990101")));
    ASSERT_EQ(ERR_OK,normalize_claude_model(&arena,STR_LIT("claude-opus-4-6-²²²²²²²²"),&normalized).code);
    ASSERT_TRUE(str_equal(normalized,STR_LIT("claude-opus-4-6-²²²²²²²²")));
    ASSERT_EQ(ERR_OK,normalize_claude_model(&arena,STR_LIT("claude-opus-4-6-٢٠٩٩٠١٠١"),&normalized).code);
    ASSERT_TRUE(str_equal(normalized,STR_LIT("claude-opus-4-6")));
    ASSERT_EQ(ERR_OK,normalize_claude_model(&arena,STR_LIT("claude-opus-4-6-v²:¹"),&normalized).code);
    ASSERT_TRUE(str_equal(normalized,STR_LIT("claude-opus-4-6-v²:¹")));
    const char *models[]={"claude-opus-4-6","provider/claude-opus-4-7-20990101","anthropic.claude-opus-4-8@default","claude-opus-4-70","gpt-reserve","gpt-5.6-2099-01-01","gpt-6.1-sol","claude-sonnet-4-6","claude-opus-4-6-foo-claude-opus-4-60"};
    double expected[]={6,6,2,1,2,2,2,1,1};
    for(size_t i=0;i<9;i++){double multiplier;ASSERT_EQ(ERR_OK,claude_fast_multiplier((Str){models[i],(uint32_t)strlen(models[i])},&multiplier).code);CLOSE(expected[i],multiplier);}
    arena_destroy(&arena);
}
TEST(claude_catalog_lookup_ambiguity_route_and_fallback_rates) {
    const char *json="{\"anthropic\":{\"models\":{\"synthetic-shared\":{\"id\":\"synthetic-shared\",\"cost\":{\"input\":11,\"output\":17}},\"claude-synthetic\":{\"id\":\"claude-synthetic\",\"cost\":{\"input\":11,\"output\":17,\"context_over_200k\":{\"input\":23},\"tiers\":[{\"tier\":{\"type\":\"context\",\"size\":41},\"input\":23}]}}}},\"google\":{\"models\":{\"synthetic-shared\":{\"id\":\"synthetic-shared\",\"cost\":{\"input\":19,\"output\":31}}}},\"kimi-for-coding\":{\"models\":{\"k3\":{\"id\":\"k3\",\"cost\":{\"input\":37,\"output\":43}}}}}";
    yyjson_doc *doc=NULL;ASSERT_EQ(ERR_OK,catalog_decode((Str){json,(uint32_t)strlen(json)},&doc).code);ASSERT_TRUE(doc);
    ModelsDevIndex index={0};ASSERT_EQ(ERR_OK,models_dev_index(yyjson_doc_get_root(doc),&index).code);
    Arena arena={0};ClaudeLookup lookup;
    ASSERT_EQ(ERR_OK,claude_models_dev_lookup(&arena,&index,STR_LIT("synthetic-shared"),&lookup).code);ASSERT_FALSE(lookup.catalog.model);
    ASSERT_EQ(ERR_OK,claude_models_dev_lookup(&arena,&index,STR_LIT("google/synthetic-shared"),&lookup).code);ASSERT_TRUE(lookup.catalog.model);ASSERT_TRUE(str_equal(lookup.provider,STR_LIT("google")));
    ASSERT_EQ(ERR_OK,claude_models_dev_lookup(&arena,&index,STR_LIT("k3[1m]"),&lookup).code);ASSERT_TRUE(lookup.catalog.model);
    ASSERT_EQ(ERR_OK,claude_models_dev_lookup(&arena,&index,STR_LIT("unsupported/synthetic-shared"),&lookup).code);ASSERT_FALSE(lookup.catalog.model);
    UsageUnit u=unit(STR_LIT("claude-synthetic"),42,0);u.cached=13;u.cache_write=11;u.cache_write_1h=5;
    PricingReport report={0};ASSERT_EQ(ERR_OK,claude_price_usage_units(&u,1,&index,&report).code);ASSERT_TRUE(u.has_cost);
    /* Absent cache rates fall back to standard input, even in the long lane. */
    CLOSE((18.*23+13*11+6*11+5*46+7*17)/1e6,u.cost_usd);
    ASSERT_TRUE(str_equal(u.period.model,STR_LIT("claude:anthropic/claude-synthetic")));
    pricing_report_destroy(&report);arena_destroy(&arena);models_dev_destroy(&index);yyjson_doc_free(doc);
}
TEST(claude_temporal_preserves_prior_zero_and_falls_back_to_nanocost) {
    UsageUnit u[]={unit(STR_LIT("claude-opus-4-6"),19,0),unit(STR_LIT("synthetic-unlisted-model"),19,0)};
    for(size_t i=0;i<2;i++){u[i].claude_price_snapshot=true;u[i].claude_cost_priced=true;}
    u[1].claude_cost_nanos=1234567;
    PricingReport report={0};ASSERT_EQ(ERR_OK,claude_price_usage_units(u,2,NULL,&report).code);
    ASSERT_TRUE(u[0].has_cost);CLOSE(0,u[0].cost_usd);
    ASSERT_TRUE(u[1].has_cost);CLOSE(.001234567,u[1].cost_usd);
    ASSERT_EQ(0,report.unpriced.size);
    pricing_report_destroy(&report);
}
TEST(claude_snapshot_prices_every_complete_raw_row_before_dedupe) {
    ClaudeUsageRow rows[3]={0};for(size_t i=0;i<3;i++)rows[i].unit=unit(STR_LIT("claude-opus-4-6"),19,0);
    rows[2].incomplete=true;
    ClaudeRecord record={.usage_rows=rows,.usage_count=3};ClaudeScan scan={.records=&record,.count=1};
    ASSERT_EQ(ERR_OK,claude_capture_prices(&scan,NULL).code);
    for(size_t i=0;i<2;i++){ASSERT_TRUE(rows[i].unit.claude_price_snapshot);ASSERT_TRUE(rows[i].unit.claude_cost_priced);ASSERT_EQ(270000,rows[i].unit.claude_cost_nanos);ASSERT_FALSE(rows[i].unit.period.present);}
    ASSERT_FALSE(rows[2].unit.claude_price_snapshot);
}
TEST(claude_catalog_precedence_untimed_and_openai_boundary) {
    const char *json="{\"anthropic\":{\"models\":{\"claude-opus-4-6\":{\"id\":\"claude-opus-4-6\",\"cost\":{\"input\":11,\"output\":17}}}},\"openai\":{\"models\":{\"gpt-5.6-sol\":{\"id\":\"gpt-5.6-sol\",\"cost\":{\"input\":19,\"output\":31,\"context_over_200k\":{\"input\":37},\"tiers\":[{\"tier\":{\"type\":\"context\",\"size\":41},\"input\":37}]}}}}}";
    yyjson_doc *doc=NULL;ASSERT_EQ(ERR_OK,catalog_decode((Str){json,(uint32_t)strlen(json)},&doc).code);
    ModelsDevIndex index={0};ASSERT_EQ(ERR_OK,models_dev_index(yyjson_doc_get_root(doc),&index).code);
    UsageUnit units[]={unit(STR_LIT("claude-opus-4-6"),19,1773360000000),unit(STR_LIT("claude-opus-4-6"),19,0),unit(STR_LIT("openai/gpt-5.6-sol"),272000,0),unit(STR_LIT("openai/gpt-5.6-sol"),272001,0)};
    units[1].timestamp_ms.present=false;
    PricingReport report={0};ASSERT_EQ(ERR_OK,claude_price_usage_units(units,4,&index,&report).code);
    CLOSE(.000270,units[0].cost_usd);CLOSE((19.*11+7*17)/1e6,units[1].cost_usd);
    ASSERT_TRUE(str_equal(units[0].period.model,STR_LIT("claude:bundled/claude-opus-4-6")));
    ASSERT_TRUE(str_equal(units[1].period.model,STR_LIT("claude:anthropic/claude-opus-4-6")));
    CLOSE((272000.*19+7*31)/1e6,units[2].cost_usd);CLOSE((272001.*37+7*31)/1e6,units[3].cost_usd);
    pricing_report_destroy(&report);models_dev_destroy(&index);yyjson_doc_free(doc);
}
TEST(claude_bundled_families_and_nonnormalized_unknown_dates) {
    const char *models[]={"claude-fable-5","claude-haiku-4-5","claude-haiku-4-5-20251001","claude-opus-4-5","claude-opus-4-5-20251101","claude-opus-4-6-20260205","claude-opus-4-7","claude-opus-4-8","claude-opus-4-20250514","claude-opus-4-1","claude-sonnet-4-20250514","claude-sonnet-4-5-20250929"};
    double expected[]={.000540,.000054,.000054,.000270,.000270,.000270,.000270,.000270,.000810,.000810,.000162,.000162};
    UsageUnit units[12];for(size_t i=0;i<12;i++)units[i]=unit((Str){models[i],(uint32_t)strlen(models[i])},19,0);
    PricingReport report={0};ASSERT_EQ(ERR_OK,claude_price_usage_units(units,12,NULL,&report).code);
    for(size_t i=0;i<12;i++){ASSERT_TRUE(units[i].has_cost);CLOSE(expected[i],units[i].cost_usd);}
    pricing_report_destroy(&report);
}
TEST(claude_route_primary_precedes_alias_provider_and_preferred_vendor_stays_owned) {
    const char *json="{\"kimi-coding\":{\"models\":{\"synthetic-kite\":{\"id\":\"synthetic-kite\",\"cost\":{\"input\":11,\"output\":17}}}},\"kimi-for-coding\":{\"models\":{\"synthetic-kite\":{\"id\":\"synthetic-kite\",\"cost\":{\"input\":19,\"output\":31}}}},\"google\":{\"models\":{\"claude-synthetic\":{\"id\":\"claude-synthetic\",\"cost\":{\"input\":37,\"output\":43}}}}}";
    yyjson_doc *doc=NULL;ASSERT_EQ(ERR_OK,catalog_decode((Str){json,(uint32_t)strlen(json)},&doc).code);ModelsDevIndex index={0};ASSERT_EQ(ERR_OK,models_dev_index(yyjson_doc_get_root(doc),&index).code);
    Arena arena={0};ClaudeLookup lookup;
    ASSERT_EQ(ERR_OK,claude_models_dev_lookup(&arena,&index,STR_LIT("kimi-coding/synthetic-kite"),&lookup).code);ASSERT_TRUE(str_equal(lookup.provider,STR_LIT("kimi-coding")));
    ASSERT_EQ(ERR_OK,claude_models_dev_lookup(&arena,&index,STR_LIT("claude-synthetic"),&lookup).code);ASSERT_FALSE(lookup.catalog.model);
    ASSERT_EQ(ERR_OK,claude_models_dev_lookup(&arena,&index,STR_LIT("google/claude-synthetic"),&lookup).code);ASSERT_TRUE(lookup.catalog.model);
    arena_destroy(&arena);models_dev_destroy(&index);yyjson_doc_free(doc);
}
