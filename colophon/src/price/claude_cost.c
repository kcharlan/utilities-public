#include "claude_cost.h"
#include "claude_model.h"
#include "gen/assets.h"
#include "util/json_read.h"
#include "util/json_number.h"
#include <string.h>
#include <math.h>
#define TRY(x) do {Err e_=(x);if(e_.code)return e_;}while(0)
static yyjson_val *get(yyjson_val *v,const char *k){return obj_get_last(v,(Str){k,(uint32_t)strlen(k)});}
static double number(PyNum n){return n.is_float?n.f:(double)n.i;}
static double leaf_number(yyjson_val *v){PyNum n={0};return json_number(v,"claude.seed",&n)?number(n):0;}
static __int128 positive(__int128 n){return n>0?n:0;}
double claude_cost_usd(const PriceEntry *rates,const UsageUnit *u) {
    __int128 input=positive(u->input-u->cached-u->cache_write),read=positive(u->cached),write=positive(u->cache_write),one=positive(u->cache_write_1h);
    if(one>write)one=write;
    const PriceRates *r=rates->has_extended&&input+read+write>rates->threshold?&rates->extended:&rates->standard;
    return ((double)input*number(r->input)+(double)read*number(r->cached_input)+(double)(write-one)*number(r->cache_write)+(double)one*number(r->input)*2+(double)positive(u->output)*number(r->output))/1000000;
}
static PriceRates array_rates(yyjson_val *row,size_t offset) {
    PriceRates r={0};PyNum *values[]={&r.input,&r.cached_input,&r.cache_write,&r.output};
    for(size_t i=0;i<4;i++)*values[i]=(PyNum){.is_float=true,.f=leaf_number(yyjson_arr_get(row,offset+i))*1000000};return r;
}
static PriceEntry bundled(yyjson_val *row) {
    PriceEntry r={.standard=array_rates(row,0)};
    if(yyjson_arr_size(row)>4){r.has_extended=true;r.threshold=(int64_t)leaf_number(yyjson_arr_get(row,4));r.extended=array_rates(row,5);}return r;
}
static Err catalog_rates(const ClaudeLookup *lookup,PriceEntry *out) {
    const CatalogModel *m=lookup->catalog.model;PriceEntry rates={0};
    double values[4];memcpy(values,m->rates,sizeof values);for(size_t i=1;i<3;i++)if(!(m->present&(1u<<i)))values[i]=values[0];
    PyNum *standard[]={&rates.standard.input,&rates.standard.cached_input,&rates.standard.cache_write,&rates.standard.output};
    PyNum *extended[]={&rates.extended.input,&rates.extended.cached_input,&rates.extended.cache_write,&rates.extended.output};
    for(size_t i=0;i<4;i++){*standard[i]=(PyNum){.is_float=true,.f=values[i]};*extended[i]=(PyNum){.is_float=true,.f=(m->extended_present&(1u<<i))?m->extended[i]:values[i]};}
    if(m->has_extended){rates.has_extended=true;rates.threshold=m->has_context_tier?m->context_tier_size:200000;}
    /* OpenAI's bundled context boundary applies even without a catalog lane. */
    if(str_equal(lookup->provider,STR_LIT("openai"))){PriceEntry codex;bool found;TRY(resolve_rates(m->model_id,NULL,&codex,&found));if(found&&codex.has_extended){rates.has_extended=true;rates.threshold=codex.threshold;}}
    *out=rates;return ERR_SUCCESS;
}
typedef struct {Str identity;PriceEntry rates;double fast;bool found;} ClaudeResolution;
static Err resolved(ModelsDevIndex *index,PricingReport *report,const UsageUnit *u,Str identity_prefix,bool key_by_model,ClaudeResolution **out) {
    yyjson_val *root=yyjson_doc_get_root(report->claude_seed),*models=get(root,"claude"),*historical=get(root,"historical");
    Str lookup_model=key_by_model?u->model:u->model_raw;
    JsonWriter query={0};jsonw_raw(&query,"[");jsonw_string(&query,identity_prefix);jsonw_raw(&query,",");jsonw_i64(&query,key_by_model);jsonw_raw(&query,",");jsonw_string(&query,lookup_model);jsonw_raw(&query,",");jsonw_i64(&query,!u->timestamp_ms.present?0:u->timestamp_ms.value<(int64_t)leaf_number(get(root,"cutoff_ms"))?1:2);jsonw_raw(&query,"]");
    Err e=query.error;if(e.code){jsonw_free(&query);return e;}
    Str query_key={query.data,(uint32_t)query.length};ClaudeResolution *result=omap_get(&report->claude_resolutions,query_key);
    if(result){jsonw_free(&query);*out=result;return ERR_SUCCESS;}
    e=arena_alloc(&report->arena,sizeof *result,_Alignof(ClaudeResolution),(void **)&result);if(e.code){jsonw_free(&query);return e;}*result=(ClaudeResolution){0};
    Str normalized;e=normalize_claude_model(&report->arena,lookup_model,&normalized);if(e.code){jsonw_free(&query);return e;}
        yyjson_val *row=obj_get_last(models,normalized),*old=obj_get_last(historical,normalized);PriceEntry rates={0};ClaudeLookup lookup={0};
        bool temporal=old&&row&&u->timestamp_ms.present;
        if(temporal)rates=bundled(u->timestamp_ms.value<(int64_t)leaf_number(get(root,"cutoff_ms"))?old:row);
        else {e=claude_models_dev_lookup(&report->arena,index,lookup_model,&lookup);if(!e.code&&lookup.catalog.model)e=catalog_rates(&lookup,&rates);else if(!e.code&&row)rates=bundled(row);if(e.code){jsonw_free(&query);return e;}}
        JsonWriter key={0};jsonw_bytes(&key,identity_prefix.p,identity_prefix.n);
        if(lookup.catalog.model){jsonw_bytes(&key,lookup.provider.p,lookup.provider.n);jsonw_raw(&key,"/");jsonw_bytes(&key,lookup.catalog.model->model_id.p,lookup.catalog.model->model_id.n);}else {jsonw_raw(&key,"bundled/");jsonw_bytes(&key,normalized.p,normalized.n);}
    e=key.error;if(!e.code)e=str_copy(&report->arena,(Str){key.data,(uint32_t)key.length},&result->identity);jsonw_free(&key);
    if(!e.code)e=claude_fast_multiplier(lookup.catalog.model?lookup.catalog.model->model_id:normalized,&result->fast);
    result->rates=rates;result->found=lookup.catalog.model||row;
    if(!e.code)e=omap_put(&report->claude_resolutions,query_key,result);
    jsonw_free(&query);if(!e.code)*out=result;return e;
}
Err catalog_price_usage_units(UsageUnit *units,size_t count,ModelsDevIndex *index,PricingReport *report,Str identity_prefix,bool key_by_model) {
    if(!report->claude_seed){JsonRead seed=json_read((Str){(const char *)cp_asset_curated_bundled_claude,(uint32_t)cp_asset_curated_bundled_claude_len},STR,JSON_CONSTANTS_REJECT,"claude.bundled");
        if(seed.status!=JSON_OK){json_read_free(&seed);return err_make(ERR_INVALID,"invalid Claude bundled prices");}report->claude_seed=seed.doc;}
    Err e=ERR_SUCCESS;
    for(size_t i=0;i<count;i++){
        UsageUnit *u=&units[i];u->has_cost=false;u->cost_usd=0;u->period=u->fast_period=(PricePeriod){0};
        ClaudeResolution *resolution;e=resolved(index,report,u,identity_prefix,key_by_model,&resolution);if(e.code)break;
        Str identity=resolution->identity;
        if(!resolution->found){
            if(u->claude_price_snapshot&&u->claude_cost_priced){u->has_cost=true;u->cost_usd=(double)u->claude_cost_nanos/1e9;continue;}
            u->claude_price_snapshot=true;
            e=pricing_note_unpriced(report,identity,u->input+u->output);if(e.code)break;continue;}
        e=pricing_claude_period(report,identity,&resolution->rates,resolution->fast,&u->period);if(e.code)break;
        u->has_cost=true;u->cost_usd=claude_cost_usd(&resolution->rates,u);if(u->fast){u->cost_usd*=resolution->fast;u->fast_period=u->period;}
        if(!u->claude_price_snapshot){
            double nanos=round(u->cost_usd*1e9);u->claude_price_snapshot=true;
            if(isfinite(nanos)&&nanos>=-0x1p63&&nanos<0x1p63){u->claude_cost_priced=true;u->claude_cost_nanos=(int64_t)nanos;}
        }
        if(u->claude_cost_priced&&u->claude_cost_nanos==0)u->cost_usd=0;
    }
    return e;
}
Err claude_price_usage_units(UsageUnit *units,size_t count,ModelsDevIndex *index,PricingReport *report) {
    return catalog_price_usage_units(units,count,index,report,STR_LIT("claude:"),false);
}
Err claude_price_units(Corpus *corpus,ModelsDevIndex *index,PricingReport *report) {
    for(OmapEntry *p=corpus->sessions.first;p;p=p->next){SessionModel *s=p->value;if(s->provider==PROVIDER_CLAUDE)TRY(claude_price_usage_units(s->units,s->unit_count,index,report));}pricing_report_note_sums(report);return ERR_SUCCESS;
}
Err claude_capture_prices(ClaudeScan *scan,ModelsDevIndex *index) {
    PricingReport scratch={0};Err e=ERR_SUCCESS;
    for(size_t i=0;i<scan->count&&!e.code;i++)for(size_t j=0;j<scan->records[i].usage_count;j++){
        ClaudeUsageRow *row=&scan->records[i].usage_rows[j];if(row->incomplete||row->unit.claude_price_snapshot)continue;
        e=claude_price_usage_units(&row->unit,1,index,&scratch);
        row->unit.period=row->unit.fast_period=(PricePeriod){0};
        if(e.code)break;
    }
    pricing_report_destroy(&scratch);return e;
}
