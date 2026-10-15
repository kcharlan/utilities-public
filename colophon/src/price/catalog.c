#define _DARWIN_C_SOURCE
#include "catalog.h"
#include "parse/tokenstream.h"
#include "util/json_number.h"
#include "util/json_read.h"
#include "util/events.h"
#include "util/fileio.h"
#include "util/atomic.h"
#include "testing/hooks.h"
#include <curl/curl.h>
#include <pthread.h>
#include <limits.h>
#include <time.h>
#include <errno.h>
#include <sys/stat.h>
#include "gen/assets.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static yyjson_val *get(yyjson_val *v,const char *key) {return obj_get_last(v,(Str){key,(uint32_t)strlen(key)});}
static Str string(yyjson_val *v) {return yyjson_is_str(v)?(Str){yyjson_get_str(v),(uint32_t)yyjson_get_len(v)}:(Str){0};}
static bool nullable_string(yyjson_val *v) {return !v||yyjson_is_null(v)||yyjson_is_str(v);}
static bool provider_valid(yyjson_val *v) {
    return yyjson_is_obj(v)&&yyjson_is_obj(get(v,"models"))&&nullable_string(get(v,"id"))&&nullable_string(get(v,"name"));
}
static bool decode_rates(yyjson_val *v,double *rates,uint8_t *present,const char *prefix) {
    const char *keys[]={"input","cached_read","cache_write","output"};
    keys[1]="cache_read";
    *present=0;
    for(size_t i=0;i<4;i++) {
        yyjson_val *leaf=get(v,keys[i]);
        if(!leaf||yyjson_is_null(leaf))continue;
        PyNum number;
        char site[256];snprintf(site,sizeof site,"%s.%s",prefix,keys[i]);
        if(!json_number(leaf,site,&number))return false;
        rates[i]=number.is_float?number.f:(double)number.i;
        if(!isfinite(rates[i]))return false;
        *present|=(uint8_t)(1u<<i);
    }
    return true;
}
/* v0.74.1 ModelsDevContextOver200KCost.tier: absent/null, else {type:String,size:Int}. */
static bool decode_tier(yyjson_val *v,const char *prefix,bool *present,Str *type,int64_t *size) {
    *present=false;
    if(!v||yyjson_is_null(v))return true;
    char site[256];snprintf(site,sizeof site,"%s.tier.size",prefix);
    yyjson_val *kind=get(v,"type");PyNum number;
    if(!yyjson_is_obj(v)||!yyjson_is_str(kind)||!json_number(get(v,"size"),site,&number)||!pynum_context_int(number))return false;
    *present=true;*type=string(kind);*size=number.is_float?(int64_t)number.f:number.i;return true;
}
static bool same_rates(const double *a,uint8_t ap,const double *b,uint8_t bp) {
    if(ap!=bp)return false;
    for(size_t i=0;i<4;i++)if((ap&(1u<<i))&&a[i]!=b[i])return false;
    return true;
}
static bool decode_model(yyjson_val *v,CatalogModel *out,const char *prefix) {
    *out=(CatalogModel){0};
    if(!yyjson_is_obj(v)||!yyjson_is_str(get(v,"id"))||!nullable_string(get(v,"name")))return false;
    yyjson_val *limit=get(v,"limit");
    if(limit&&!yyjson_is_null(limit)) {
        if(!yyjson_is_obj(limit))return false;
        yyjson_val *context=get(limit,"context");
        if(context&&!yyjson_is_null(context)) {
            PyNum number;
            char site[256];snprintf(site,sizeof site,"%s.limit.context",prefix);
            if(!json_number(context,site,&number)||!pynum_context_int(number))return false;
        }
    }
    yyjson_val *cost=get(v,"cost");
    char site[256];snprintf(site,sizeof site,"%s.cost",prefix);
    if(!yyjson_is_obj(cost)||!decode_rates(cost,out->rates,&out->present,site)||!(out->present&1)||!(out->present&8))return false;
    yyjson_val *extended=get(cost,"context_over_200k");
    if(extended&&!yyjson_is_null(extended)) {
        snprintf(site,sizeof site,"%s.cost.context_over_200k",prefix);
        if(!yyjson_is_obj(extended)||!decode_rates(extended,out->extended,&out->extended_present,site))return false;
        out->has_extended=true;
    }
    bool extended_tier=false;
    if(out->has_extended) {
        Str ignored;int64_t unused;
        if(!decode_tier(get(extended,"tier"),site,&extended_tier,&ignored,&unused))return false;
    }
    yyjson_val *tiers=get(cost,"tiers");
    if(tiers&&!yyjson_is_null(tiers)) {
        if(!yyjson_is_arr(tiers))return false;
        size_t i,max;yyjson_val *tier;
        yyjson_arr_foreach(tiers,i,max,tier) {
            char tier_site[256];snprintf(tier_site,sizeof tier_site,"%s.cost.tiers[%zu]",prefix,i);
            double rates[4]={0};uint8_t present=0;bool has_tier;Str type;int64_t size;
            if(!yyjson_is_obj(tier)||!decode_rates(tier,rates,&present,tier_site)||
               !decode_tier(get(tier,"tier"),tier_site,&has_tier,&type,&size))return false;
            if(!out->has_context_tier&&out->has_extended&&!extended_tier&&has_tier&&size>0&&
               str_equal(type,STR_LIT("context"))&&same_rates(rates,present,out->extended,out->extended_present)) {
                out->has_context_tier=true;out->context_tier_size=size;
            }
        }
    }
    out->model_id=string(get(v,"id"));return true;
}
static Err openai(Arena *arena,Str raw,bool *out) {
    Str lower;Err e=str_lower(arena,token_model_trim(raw),&lower);
    *out=!e.code&&str_equal(lower,STR_LIT("openai"));return e;
}
static bool claude_provider(Str id) {
    const char *ids[]={"anthropic","openai","google","moonshot","kimi-for-coding","minimax","deepseek","kimi-coding","opencode","opencode-free"};
    for(size_t i=0;i<sizeof ids/sizeof *ids;i++)if(str_equal(id,(Str){ids[i],(uint32_t)strlen(ids[i])}))return true;
    return false;
}
static Err index_provider_models(ModelsDevIndex *out,yyjson_val *provider,bool wrapper,size_t provider_position) {
    omap_destroy(&out->models);omap_destroy(&out->normalized);
    Omap models={0};Err error=json_object_dict(get(provider,"models"),&models);
    size_t model_position=0;
    for(OmapEntry *m=models.first;!error.code&&m;m=m->next,model_position++) {
        CatalogModel decoded;
        char site[192];snprintf(site,sizeof site,"catalog:%s{value[%zu]}.models{value[%zu]}",wrapper?"providers":"",provider_position,model_position);
        if(!decode_model(m->value,&decoded,site))continue;
        Str key;error=str_nfc(&out->arena,m->key,"price.catalog.key",&key);if(error.code)break;
        CatalogModel *copy;error=arena_alloc(&out->arena,sizeof *copy,_Alignof(CatalogModel),(void **)&copy);if(error.code)break;
        *copy=decoded;error=str_copy(&out->arena,decoded.model_id,&copy->model_id);if(error.code)break;
        error=omap_put(&out->models,key,copy);
    }
    omap_destroy(&models);return error;
}
static Err index_normalized(ModelsDevIndex *out) {
    for(OmapEntry *m=out->models.first;m;m=m->next) {
        CatalogModel *model=m->value;
        Str identity;Err error=str_nfc(&out->arena,token_model_trim(model->model_id),"price.catalog.model_id",&identity);
        if(error.code)return error;
        if(!omap_get(&out->normalized,identity)) {
            CatalogLookup *lookup;error=arena_alloc(&out->arena,sizeof *lookup,_Alignof(CatalogLookup),(void **)&lookup);if(error.code)return error;
            Str spelling;error=str_copy(&out->arena,token_model_trim(model->model_id),&spelling);if(error.code)return error;
            *lookup=(CatalogLookup){model,spelling};error=omap_put(&out->normalized,identity,lookup);if(error.code)return error;
        }
    }
    return ERR_SUCCESS;
}
static Err claude_index_provider(ModelsDevIndex *out,Str id,yyjson_val *provider,bool wrapper,size_t position) {
    ModelsDevIndex *child=omap_get(&out->claude_providers,id);Err e;
    if(!child){e=arena_alloc(&out->arena,sizeof *child,_Alignof(ModelsDevIndex),(void **)&child);if(e.code)return e;*child=(ModelsDevIndex){0};e=omap_put(&out->claude_providers,id,child);if(e.code)return e;}
    e=index_provider_models(child,provider,wrapper,position);return e.code?e:index_normalized(child);
}
Err models_dev_index(yyjson_val *catalog,ModelsDevIndex *out) {
    if(!yyjson_is_obj(catalog))return ERR_SUCCESS;
    yyjson_val *providers=get(catalog,"providers");
    bool wrapper=yyjson_is_obj(providers);
    if(wrapper) {
        yyjson_obj_iter it=yyjson_obj_iter_with(providers);yyjson_val *key;
        while((key=yyjson_obj_iter_next(&it)))if(!provider_valid(yyjson_obj_iter_get_val(key))){wrapper=false;break;}
    }
    if(!wrapper)providers=catalog;
    Omap dictionaries={0};Err error=json_object_dict(providers,&dictionaries);
    if(error.code)return error;
    size_t provider_position=0;
    for(OmapEntry *entry=dictionaries.first;entry;entry=entry->next,provider_position++) {
        yyjson_val *provider=entry->value;
        if(!provider_valid(provider))continue;
        yyjson_val *id=get(provider,"id");bool accepted;
        Str provider_id;error=str_lower(&out->arena,token_model_trim(yyjson_is_str(id)?string(id):entry->key),&provider_id);if(error.code)break;
        if(claude_provider(provider_id)&&!str_equal(provider_id,STR_LIT("openai"))){error=claude_index_provider(out,provider_id,provider,wrapper,provider_position);if(error.code)break;}
        error=openai(&out->arena,yyjson_is_str(id)?string(id):entry->key,&accepted);
        if(error.code)break;
        if(!accepted)continue;
        error=index_provider_models(out,provider,wrapper,provider_position);if(error.code)break;
    }
    omap_destroy(&dictionaries);
    if(error.code)return error;
    error=index_normalized(out);if(error.code)return error;
    /* Decode OpenAI once: Claude has separate query caches and map nodes, but
     * borrows the immutable catalog rows. This preserves Codex event counts. */
    ModelsDevIndex *shared;error=arena_alloc(&out->arena,sizeof *shared,_Alignof(ModelsDevIndex),(void **)&shared);if(error.code)return error;
    *shared=(ModelsDevIndex){0};error=omap_put(&out->claude_providers,STR_LIT("openai"),shared);if(error.code)return error;
    for(OmapEntry *m=out->models.first;m;m=m->next){error=omap_put(&shared->models,m->key,m->value);if(error.code)return error;}
    for(OmapEntry *m=out->normalized.first;m;m=m->next){error=omap_put(&shared->normalized,m->key,m->value);if(error.code)return error;}
    return ERR_SUCCESS;
}
typedef struct { bool accepted; Omap queries; } ProviderMemo;
Err models_dev_normalize(ModelsDevIndex *index,Str raw,Str *out) {
    return normalize_codex_model_memo(&index->arena,&index->normalizations,raw,out);
}
static Err lookup_uncached(ModelsDevIndex *index,bool accepted,Str raw,CatalogLookup *out) {
    *out=(CatalogLookup){0};
    if(!accepted)return ERR_SUCCESS;
    ModelCandidates candidates={0};Err e=models_dev_candidates(&index->arena,raw,&candidates);
    if(e.code)return e;
    for(size_t i=0;i<candidates.count;i++) {
        Str identity;e=str_nfc(&index->arena,candidates.items[i],"price.catalog.lookup",&identity);
        if(e.code)return e;
        CatalogModel *direct=omap_get(&index->models,identity);
        if(direct){*out=(CatalogLookup){direct,candidates.items[i]};return ERR_SUCCESS;}
        CatalogLookup *normalized=omap_get(&index->normalized,identity);
        if(normalized){*out=*normalized;return ERR_SUCCESS;}
    }
    return ERR_SUCCESS;
}
Err models_dev_pricing(ModelsDevIndex *index,Str provider,Str raw,CatalogLookup *out) {
    *out=(CatalogLookup){0};ProviderMemo *memo=omap_get(&index->lookups,provider);Err e;
    if(!memo){
        e=arena_alloc(&index->arena,sizeof *memo,_Alignof(ProviderMemo),(void **)&memo);if(e.code)return e;
        *memo=(ProviderMemo){0};e=openai(&index->arena,provider,&memo->accepted);if(e.code)return e;
        e=omap_put(&index->lookups,provider,memo);if(e.code)return e;
    }
    CatalogLookup *cached=omap_get(&memo->queries,raw);
    if(cached){*out=*cached;return ERR_SUCCESS;}
    e=arena_alloc(&index->arena,sizeof *cached,_Alignof(CatalogLookup),(void **)&cached);if(e.code)return e;
    e=lookup_uncached(index,memo->accepted,raw,cached);if(e.code)return e;
    e=omap_put(&memo->queries,raw,cached);if(!e.code)*out=*cached;return e;
}
Err claude_catalog_pricing(ModelsDevIndex *index,Str provider,Str raw,CatalogLookup *out) {
    *out=(CatalogLookup){0};if(!index)return ERR_SUCCESS;
    ModelsDevIndex *child=omap_get(&index->claude_providers,provider);
    return child?models_dev_pricing(child,STR_LIT("openai"),raw,out):ERR_SUCCESS;
}
void models_dev_destroy(ModelsDevIndex *index) {
    for(OmapEntry *p=index->claude_providers.first;p;p=p->next)models_dev_destroy(p->value);
    omap_destroy(&index->claude_providers);
    for(OmapEntry *p=index->lookups.first;p;p=p->next)omap_destroy(&((ProviderMemo *)p->value)->queries);
    omap_destroy(&index->lookups);omap_destroy(&index->normalizations);
    omap_destroy(&index->models);omap_destroy(&index->normalized);arena_destroy(&index->arena);*index=(ModelsDevIndex){0};
}
static void rates_json(JsonWriter *w,const double *rates,uint8_t present,bool extended) {
    const char *keys[]={"input","cached_input","cache_write","output"};
    jsonw_raw(w,"{");if(extended)jsonw_raw(w,"\"threshold\":200000,");
    /* Source decoded model dictionary puts output second. */
    const size_t order[]={0,3,1,2};
    for(size_t j=0;j<4;j++) {size_t i=order[j];if(j)jsonw_raw(w,",");jsonw_string(w,(Str){keys[i],(uint32_t)strlen(keys[i])});jsonw_raw(w,":");if(present&(1u<<i))jsonw_double(w,rates[i]);else jsonw_raw(w,"null");}
    jsonw_raw(w,"}");
}
void catalog_lookup_json(JsonWriter *w,const CatalogLookup *lookup) {
    if(!lookup->model){jsonw_raw(w,"null");return;}
    const CatalogModel *m=lookup->model;
    jsonw_raw(w,"{\"provider_id\":\"openai\",\"model_id\":");jsonw_string(w,m->model_id);
    jsonw_raw(w,",\"normalized_model_id\":");jsonw_string(w,lookup->identity);
    jsonw_raw(w,",\"per_million\":");rates_json(w,m->rates,m->present,false);
    jsonw_raw(w,",\"long_context\":");if(m->has_extended)rates_json(w,m->extended,m->extended_present,true);else jsonw_raw(w,"null");jsonw_raw(w,"}");
}
Err codex_models_dev_pricing_targets(Arena *arena,Str raw,PricingTargets *out) {
    *out=(PricingTargets){0};Str trimmed=token_model_trim(raw);
    if(!trimmed.n)return ERR_SUCCESS;
    size_t slash=price_literal_parts(trimmed,STR_LIT("/"),STR_LIT(""),false);
    Str model=trimmed;
    if(slash!=SIZE_MAX) {
        bool accepted;Err e=openai(arena,(Str){trimmed.p,(uint32_t)slash},&accepted);
        if(e.code||!accepted)return e;
        model=(Str){trimmed.p+slash+1,trimmed.n-(uint32_t)slash-1};if(!model.n)return ERR_SUCCESS;
        size_t first=price_literal_parts(model,STR_LIT("/"),STR_LIT(""),false),last=price_literal_parts(model,STR_LIT("/"),STR_LIT(""),true);
        if(first!=0&&last!=model.n-1)out->model[out->count++]=model;
    } else out->model[out->count++]=model;
    Str normalized=normalize_codex_model(model);
    if(!str_equal(normalized,model))out->model[out->count++]=normalized;
    return ERR_SUCCESS;
}
static double scale_token(double value) {
    PyDecimal decimal;
    if(!pynum_decimal(value,&decimal))return NAN;
    char spelling[64];
    int length=snprintf(spelling,sizeof spelling,"%s%.*se%d",decimal.negative?"-":"",decimal.length,decimal.digits,decimal.exponent+6);
    return length>0&&(size_t)length<sizeof spelling?strtod(spelling,NULL):NAN;
}
Err resolve_rates(Str raw,ModelsDevIndex *index,PriceEntry *out,bool *found) {
    *found=false;*out=(PriceEntry){0};
    Str key;Err normalization_error=index?models_dev_normalize(index,raw,&key):ERR_SUCCESS;
    if(!index)key=normalize_codex_model(raw);
    if(normalization_error.code)return normalization_error;
    if(str_equal(key,STR_LIT("unknown")))return ERR_SUCCESS;
    Arena arena={0};PricingTargets targets;Err error=codex_models_dev_pricing_targets(&arena,raw,&targets);
    JsonRead bundled={0};
    if(error.code)goto done;
    Str trimmed=token_model_trim(raw);
    if(memchr(trimmed.p,'/',trimmed.n)&&!targets.count)goto done;
    bundled=json_read((Str){(const char *)cp_asset_curated_bundled,(uint32_t)cp_asset_curated_bundled_len},STR,JSON_CONSTANTS_REJECT,"price.bundled");
    if(bundled.status!=JSON_OK){error=err_make(ERR_INVALID,"invalid bundled prices");goto done;}
    yyjson_val *row=obj_get_last(yyjson_doc_get_root(bundled.doc),key);
    double standard[4]={0},extended[4]={0};uint8_t sp=0,ep=0;bool threshold=false;
    const char *fields[]={"inputCostPerToken","cacheReadInputCostPerToken","cacheWriteInputCostPerToken","outputCostPerToken"};
    if(row) {
        for(size_t i=0;i<4;i++) for(size_t j=0;j<2;j++) {
            char field[80];snprintf(field,sizeof field,"%s%s",fields[i],j?"AboveThreshold":"");
            yyjson_val *leaf=get(row,field);PyNum number;
            if(leaf&&!yyjson_is_null(leaf)&&json_number(leaf,"price.bundled.rate",&number)) {
                double scaled=scale_token(number.is_float?number.f:(double)number.i);
                if(j){extended[i]=scaled;ep|=(uint8_t)(1u<<i);}else{standard[i]=scaled;sp|=(uint8_t)(1u<<i);}
            }
        }
        PyNum limit;if(json_number(get(row,"thresholdTokens"),"price.bundled.threshold",&limit)&&!limit.is_float){threshold=true;out->threshold=limit.i;}
    }
    CatalogLookup lookup={0};
    if(index)for(size_t i=0;i<targets.count;i++) {
        error=models_dev_pricing(index,STR_LIT("openai"),targets.model[i],&lookup);
        if(error.code)goto done;
        if(lookup.model)break;
    }
    if(!lookup.model&&!row)goto done;
    if(lookup.model) {
        const CatalogModel *m=lookup.model;
        if(m->has_extended) {
            memcpy(extended,m->extended,sizeof extended);ep=m->extended_present;
            /* Catalog context tier precedes the documented bundled threshold. */
            if(m->has_context_tier)out->threshold=m->context_tier_size;
            else if(!threshold)out->threshold=200000;
            threshold=true;
            for(size_t i=1;i<3;i++)if(!(ep&(1u<<i))) {
                extended[i]=(m->present&(1u<<i))?m->rates[i]:(ep&1)?extended[0]:m->rates[0];
                ep|=(uint8_t)(1u<<i);
            }
        }
        standard[0]=m->rates[0];standard[3]=m->rates[3];sp|=9;
        for(size_t i=1;i<3;i++)if(m->present&(1u<<i)){standard[i]=m->rates[i];sp|=(uint8_t)(1u<<i);}
    }
    if(threshold) {
        if(!(ep&1))extended[0]=standard[0];
        if(!(ep&8))extended[3]=standard[3];
        for(size_t i=1;i<3;i++)if(!(ep&(1u<<i)))extended[i]=(sp&(1u<<i))?standard[i]:extended[0];
        out->has_extended=true;
    }
    for(size_t i=1;i<3;i++)if(!(sp&(1u<<i)))standard[i]=standard[0];
    PyNum *normal[]={&out->standard.input,&out->standard.cached_input,&out->standard.cache_write,&out->standard.output};
    PyNum *longs[]={&out->extended.input,&out->extended.cached_input,&out->extended.cache_write,&out->extended.output};
    for(size_t i=0;i<4;i++){*normal[i]=(PyNum){.is_float=true,.f=standard[i]};*longs[i]=(PyNum){.is_float=true,.f=extended[i]};}
    *found=true;
done:
    json_read_free(&bundled);arena_destroy(&arena);return error;
}
static void resolved_block(JsonWriter *w,const PriceRates *rates,bool extended,int64_t threshold) {
    jsonw_raw(w,"{");if(extended){jsonw_raw(w,"\"threshold\":");jsonw_i64(w,threshold);jsonw_raw(w,",");}
    const char *keys[]={"input","output","cached_input","cache_write"};
    PyNum numbers[]={rates->input,rates->output,rates->cached_input,rates->cache_write};
    for(size_t i=0;i<4;i++){if(i)jsonw_raw(w,",");jsonw_string(w,(Str){keys[i],(uint32_t)strlen(keys[i])});jsonw_raw(w,":");if(numbers[i].is_float)jsonw_double(w,numbers[i].f);else jsonw_i64(w,numbers[i].i);}
    jsonw_raw(w,"}");
}
void price_entry_fields_json(JsonWriter *w,const PriceEntry *entry) {
    jsonw_raw(w,"\"per_million\":");resolved_block(w,&entry->standard,false,0);
    jsonw_raw(w,",\"long_context\":");if(entry->has_extended)resolved_block(w,&entry->extended,true,entry->threshold);else jsonw_raw(w,"null");
}
void price_entry_json(JsonWriter *w,const PriceEntry *entry) {
    jsonw_raw(w,"{");price_entry_fields_json(w,entry);jsonw_raw(w,"}");
}
typedef struct {yyjson_val *source;yyjson_mut_val *parent;Str key;bool object;} CatalogCopy;
static Err first_nfc_copy(yyjson_doc *source,yyjson_mut_doc **out) {
    yyjson_mut_doc *doc=yyjson_mut_doc_new(NULL);Arena arena={0};
    size_t count=1,capacity=32;CatalogCopy *stack=malloc(capacity*sizeof *stack);
    Err error=ERR_SUCCESS;
    if(!doc||!stack){error=err_make(ERR_NOMEM,"catalog copy allocation");goto done;}
    stack[0]=(CatalogCopy){.source=yyjson_doc_get_root(source)};
    while(count) {
        CatalogCopy node=stack[--count];yyjson_val *v=node.source;
        yyjson_mut_val *copy;
        if(yyjson_is_obj(v))copy=yyjson_mut_obj(doc);
        else if(yyjson_is_arr(v))copy=yyjson_mut_arr(doc);
        else copy=yyjson_val_mut_copy(doc,v);
        if(!copy){error=err_make(ERR_NOMEM,"catalog copy allocation");break;}
        bool attached=true;
        if(!node.parent)yyjson_mut_doc_set_root(doc,copy);
        else if(node.object) {
            yyjson_mut_val *key=yyjson_mut_strncpy(doc,node.key.p,node.key.n);
            attached=key&&yyjson_mut_obj_add(node.parent,key,copy);
        } else attached=yyjson_mut_arr_append(node.parent,copy);
        if(!attached){error=err_make(ERR_NOMEM,"catalog copy allocation");break;}
        if(!yyjson_is_ctn(v))continue;
        size_t needed=yyjson_get_len(v);
        if(needed>SIZE_MAX-count){error=err_make(ERR_NOMEM,"catalog copy overflow");break;}
        if(count+needed>capacity) {
            size_t next=count+needed;
            if(next>SIZE_MAX/sizeof *stack){error=err_make(ERR_NOMEM,"catalog copy overflow");break;}
            CatalogCopy *grown=realloc(stack,next*sizeof *stack);
            if(!grown){error=err_make(ERR_NOMEM,"catalog copy allocation");break;}stack=grown;capacity=next;
        }
        size_t begin=count;
        if(yyjson_is_obj(v)) {
            Omap seen={0};yyjson_obj_iter it=yyjson_obj_iter_with(v);yyjson_val *key;
            while((key=yyjson_obj_iter_next(&it))) {
                Str identity;error=str_nfc(&arena,string(key),"catalog.key",&identity);
                if(error.code)break;
                if(omap_get(&seen,identity))continue;
                error=omap_put(&seen,identity,key);if(error.code)break;
                stack[count++]=(CatalogCopy){yyjson_obj_iter_get_val(key),copy,string(key),true};
            }
            omap_destroy(&seen);if(error.code)break;
        } else {
            yyjson_arr_iter it=yyjson_arr_iter_with(v);yyjson_val *child;
            while((child=yyjson_arr_iter_next(&it)))stack[count++]=(CatalogCopy){child,copy,{0},false};
        }
        for(size_t a=begin,b=count;a<b&&a<--b;a++){CatalogCopy swap=stack[a];stack[a]=stack[b];stack[b]=swap;}
    }
done:
    free(stack);arena_destroy(&arena);
    if(error.code)yyjson_mut_doc_free(doc);else *out=doc;return error;
}
static bool keys_valid(yyjson_val *v) {
    if(!yyjson_is_obj(v))return true;
    yyjson_obj_iter it=yyjson_obj_iter_with(v);yyjson_val *key;
    while((key=yyjson_obj_iter_next(&it)))if(!str_utf8_scalar_valid(string(key)))return false;
    return true;
}
/* Reject raw nonzero rate lexemes that binary conversion would erase. */
static bool raw_rates_valid(yyjson_val *block) {
    if(!keys_valid(block))return false;
    const char *rates[]={"input","output","cache_read","cache_write"};
    for(size_t i=0;i<4;i++) {
        yyjson_val *leaf=get(block,rates[i]);
        if(!yyjson_is_raw(leaf))continue;
        Str lexeme={yyjson_get_raw(leaf),(uint32_t)yyjson_get_len(leaf)};
        if(json_number_is_integer(lexeme)||strtod(lexeme.p,NULL)!=0)continue;
        for(size_t j=0;j<lexeme.n&&lexeme.p[j]!='e'&&lexeme.p[j]!='E';j++)if(lexeme.p[j]>='1'&&lexeme.p[j]<='9')return false;
    }
    return true;
}
static bool raw_tier_valid(yyjson_val *block) {
    yyjson_val *tier=get(block,"tier"),*type=get(tier,"type");
    return keys_valid(tier)&&(!yyjson_is_str(type)||str_utf8_scalar_valid(string(type)));
}
static bool raw_model_valid(yyjson_val *model) {
    if(!yyjson_is_obj(model)||!keys_valid(model))return false;
    const char *fields[]={"id","name"};
    for(size_t i=0;i<2;i++){yyjson_val *leaf=get(model,fields[i]);if(yyjson_is_str(leaf)&&!str_utf8_scalar_valid(string(leaf)))return false;}
    if(!keys_valid(get(model,"limit")))return false;
    yyjson_val *cost=get(model,"cost"),*extended=get(cost,"context_over_200k");
    if(!raw_rates_valid(cost)||!raw_rates_valid(extended)||!raw_tier_valid(extended))return false;
    yyjson_val *tiers=get(cost,"tiers");size_t i,max;yyjson_val *tier;
    yyjson_arr_foreach(tiers,i,max,tier)if(!raw_rates_valid(tier)||!raw_tier_valid(tier))return false;
    return true;
}
static yyjson_mut_val *mut_get(yyjson_mut_val *v,const char *key) {return yyjson_mut_obj_get(v,key);}
typedef struct {yyjson_mut_val *value;yyjson_val *original;Str site;} SanitizeNode;
static Err sanitize_numbers(yyjson_mut_val *root,yyjson_val *original) {
    size_t count=1,capacity=32;SanitizeNode *stack=malloc(capacity*sizeof *stack);Arena arena={0};
    if(!stack)return err_make(ERR_NOMEM,"catalog sanitize allocation");stack[0]=(SanitizeNode){root,original,STR_LIT("catalog:")};
    Err error=ERR_SUCCESS;
    while(count) {
        SanitizeNode node=stack[--count];yyjson_mut_val *v=node.value;
        if(yyjson_mut_is_raw(v)) {
            yyjson_val leaf={v->tag,v->uni};PyNum number;
            if(!json_number(&leaf,node.site.p,&number)|| (number.is_float&&!isfinite(number.f)))yyjson_mut_set_null(v);
            else if(number.is_float)yyjson_mut_set_real(v,number.f);else yyjson_mut_set_sint(v,number.i);
        }
        if(!yyjson_mut_is_ctn(v))continue;
        size_t needed=yyjson_get_len(node.original),begin=count;
        if(needed>SIZE_MAX-count||count+needed>SIZE_MAX/sizeof *stack){error=err_make(ERR_NOMEM,"catalog sanitize overflow");break;}
        if(count+needed>capacity) {
            capacity=count+needed;SanitizeNode *grown=realloc(stack,capacity*sizeof *stack);
            if(!grown){error=err_make(ERR_NOMEM,"catalog sanitize allocation");break;}stack=grown;
        }
        yyjson_obj_iter it=yyjson_obj_iter_with(node.original);
        for(size_t i=0;i<needed;i++) {
            yyjson_val *source;yyjson_mut_val *child;char position[48];
            if(yyjson_mut_is_obj(v)) {
                yyjson_val *key=yyjson_obj_iter_next(&it);source=yyjson_obj_iter_get_val(key);
                child=yyjson_mut_obj_getn(v,yyjson_get_str(key),yyjson_get_len(key));
                snprintf(position,sizeof position,"{value[%zu]}",i);
            } else {source=yyjson_arr_get(node.original,i);child=yyjson_mut_arr_get(v,i);snprintf(position,sizeof position,"[%zu]",i);}
            if(!child)continue;
            JsonWriter path={0};jsonw_bytes(&path,node.site.p,node.site.n);jsonw_raw(&path,position);Str site;
            error=path.error;if(!error.code)error=str_copy(&arena,(Str){path.data,(uint32_t)path.length},&site);jsonw_free(&path);
            if(error.code)break;stack[count++]=(SanitizeNode){child,source,site};
        }
        if(error.code)break;
        for(size_t a=begin,b=count;a<b&&a<--b;a++){SanitizeNode swap=stack[a];stack[a]=stack[b];stack[b]=swap;}
    }
    free(stack);arena_destroy(&arena);return error;
}
static Err catalog_sanitize(yyjson_val *root,yyjson_doc **out,bool fetched) {
    *out=NULL;yyjson_mut_doc *plain=NULL;Err error=ERR_SUCCESS;
    if(!yyjson_is_obj(root))goto done;
    if(!keys_valid(root))goto done;
    plain=yyjson_mut_doc_new(NULL);if(!plain){error=err_make(ERR_NOMEM,"catalog allocation");goto done;}
    yyjson_mut_doc_set_root(plain,yyjson_val_mut_copy(plain,root));
    if(!plain->root){error=err_make(ERR_NOMEM,"catalog allocation");goto done;}
    if(fetched) {
        yyjson_obj_iter keys=yyjson_obj_iter_with(root);yyjson_val *key;
        while((key=yyjson_obj_iter_next(&keys)))if(!claude_provider(string(key)))
            yyjson_mut_obj_remove_keyn(plain->root,yyjson_get_str(key),yyjson_get_len(key));
    }
    yyjson_val *providers[]={root,get(root,"providers")};
    yyjson_mut_val *destinations[]={plain->root,mut_get(plain->root,"providers")};
    for(size_t p=0;p<2;p++) {
        if(fetched&&p)continue;
        if(!yyjson_is_obj(providers[p]))continue;
        yyjson_obj_iter it=yyjson_obj_iter_with(providers[p]);yyjson_val *key;
        size_t provider_position=0;
        while((key=yyjson_obj_iter_next(&it))) {
            size_t current_provider=provider_position++;
            yyjson_val *provider=yyjson_obj_iter_get_val(key);Str spelling=string(key);
            if(fetched&&!claude_provider(spelling))continue;
            yyjson_mut_val *destination=yyjson_mut_obj_getn(destinations[p],spelling.p,spelling.n);
            bool valid=provider_valid(provider)&&keys_valid(provider)&&keys_valid(get(provider,"models"));
            const char *texts[]={"id","name"};
            for(size_t j=0;j<2;j++){yyjson_val *leaf=get(provider,texts[j]);if(yyjson_is_str(leaf)&&!str_utf8_scalar_valid(string(leaf)))valid=false;}
            if(!valid){yyjson_mut_set_null(destination);continue;}
            yyjson_val *models=get(provider,"models");yyjson_mut_val *mutable_models=mut_get(destination,"models");
            yyjson_obj_iter mi=yyjson_obj_iter_with(models);yyjson_val *mk;
            size_t model_position=0;
            while((mk=yyjson_obj_iter_next(&mi))) {
                size_t current_model=model_position++;char site[192];
                snprintf(site,sizeof site,"catalog:%s{value[%zu]}.models{value[%zu]}",p?"providers":"",current_provider,current_model);
                yyjson_val *model=yyjson_obj_iter_get_val(mk);Str mkey=string(mk);
                yyjson_mut_val *mutable_model=yyjson_mut_obj_getn(mutable_models,mkey.p,mkey.n);
                bool accepted=raw_model_valid(model);
                yyjson_val *context=get(get(model,"limit"),"context");
                if(accepted&&yyjson_is_raw(context)) {
                    Str lexeme={yyjson_get_raw(context),(uint32_t)yyjson_get_len(context)};
                    if(!json_number_is_integer(lexeme)) {
                        int64_t integer;double binary=strtod(lexeme.p,NULL);
                        char context_site[256];snprintf(context_site,sizeof context_site,"%s.limit.context",site);
                        if(fabs(binary)>=0x1p53)event_note("catalog_context_decimal",context_site,1);
                        accepted=pynum_catalog_context(lexeme.p,binary,&integer);
                        if(accepted){yyjson_set_sint(context,integer);yyjson_mut_set_sint(mut_get(mut_get(mutable_model,"limit"),"context"),integer);}
                    }
                }
                CatalogModel decoded;
                accepted=accepted&&decode_model(model,&decoded,site);
                if(!accepted)yyjson_mut_obj_remove_keyn(mutable_models,mkey.p,mkey.n);
            }
        }
    }
    error=sanitize_numbers(plain->root,root);if(!error.code)error=json_freeze(plain,out);
done:
    yyjson_mut_doc_free(plain);return error;
}
static Err catalog_raw_read(Str raw,const char *site,yyjson_doc **out,const char **diagnostic) {
    *out=NULL;JsonRead parsed=json_read(raw,BYTES,JSON_CONSTANTS_REJECT,site);
    yyjson_mut_doc *first=NULL;Err error=ERR_SUCCESS;
    if(parsed.status==JSON_NOMEM){error=err_make(ERR_NOMEM,"catalog read allocation");goto done;}
    if(parsed.status!=JSON_OK) {
        if(diagnostic) {
            const char *constants[]={"invalid JSON","invalid JSON number NaN","invalid JSON number Infinity","invalid JSON number -Infinity"};
            *diagnostic=constants[parsed.stats.first_constant];
        }
        goto done;
    }
    error=first_nfc_copy(parsed.doc,&first);if(error.code)goto done;
    error=json_freeze(first,out);
    if(!error.code&&!keys_valid(yyjson_doc_get_root(*out))){yyjson_doc_free(*out);*out=NULL;if(diagnostic)*diagnostic="invalid Unicode in catalog object key";}
done:
    json_read_free(&parsed);yyjson_mut_doc_free(first);return error;
}
Err catalog_decode(Str raw,yyjson_doc **out) {
    yyjson_doc *document=NULL;*out=NULL;Err error=catalog_raw_read(raw,"catalog",&document,NULL);
    if(!error.code&&document)error=catalog_sanitize(yyjson_doc_get_root(document),out,false);
    yyjson_doc_free(document);return error;
}
static Err catalog_message(CatalogResult *out,Str text) {
    CatalogMessage *message;Err e=arena_alloc(&out->arena,sizeof *message,_Alignof(CatalogMessage),(void **)&message);if(e.code)return e;
    *message=(CatalogMessage){0};e=str_copy(&out->arena,text,&message->text);if(e.code)return e;
    if(out->last_message)out->last_message->next=message;else out->messages=message;out->last_message=message;return ERR_SUCCESS;
}
Err catalog_load_offline(const char *path,Str configured_url,CatalogResult *out) {
    out->status="unavailable";struct stat stat;
    if(lstat(path,&stat)&&errno==ENOENT)return ERR_SUCCESS;
    char *bytes=NULL;size_t length=0;Err error=file_read_all(path,&bytes,&length);
    if(error.code) {
        if(error.code==ERR_NOMEM)return error;
        JsonWriter diagnostic={0};jsonw_raw(&diagnostic,"pricing-cache.json: unavailable: ");jsonw_raw(&diagnostic,error.message);
        error=diagnostic.error;if(!error.code)error=catalog_message(out,(Str){diagnostic.data,(uint32_t)diagnostic.length});jsonw_free(&diagnostic);return error;
    }
    if(length>UINT32_MAX){free(bytes);return catalog_message(out,STR_LIT("pricing-cache.json: unavailable: invalid JSON"));}
    error=catalog_raw_read((Str){bytes,(uint32_t)length},"pricing-cache.json",&out->artifact,NULL);free(bytes);if(error.code)return error;
    if(!out->artifact)return catalog_message(out,STR_LIT("pricing-cache.json: unavailable: invalid JSON"));
    yyjson_val *root=yyjson_doc_get_root(out->artifact),*etag=get(root,"etag"),*catalog=get(root,"catalog");PyNum schema,fetched;
    if(!json_number(get(root,"schema"),"pricing-cache.json:schema",&schema)||schema.is_float||schema.i!=1||!yyjson_is_str(get(root,"url"))||
       !json_number(get(root,"fetched_at_ms"),"pricing-cache.json:fetched_at_ms",&fetched)||fetched.is_float||!nullable_string(etag)||
       !yyjson_is_obj(catalog)||!get(catalog,"openai"))return catalog_message(out,STR_LIT("pricing-cache.json: unavailable: invalid cache fields or schema"));
    error=catalog_sanitize(catalog,&out->catalog,false);if(error.code)return error;
    if(!out->catalog)return catalog_message(out,STR_LIT("pricing-cache.json: unavailable: invalid Unicode in catalog object key"));
    out->url=string(get(root,"url"));out->etag=string(etag);out->has_etag=yyjson_is_str(etag);
    out->has_fetched_at=true;out->fetched_at_ms=fetched.i;out->status="offline";
    if(!str_equal(out->url,configured_url)) {
        JsonWriter message={0};jsonw_raw(&message,"catalog cache URL ");jsonw_bytes(&message,out->url.p,out->url.n);jsonw_raw(&message," differs from configured URL ");jsonw_bytes(&message,configured_url.p,configured_url.n);
        error=message.error;if(!error.code)error=catalog_message(out,(Str){message.data,(uint32_t)message.length});jsonw_free(&message);
    }
    return error;
}
void catalog_result_json(JsonWriter *w,const CatalogResult *result) {
    jsonw_raw(w,"{\"status\":");jsonw_string(w,(Str){result->status,(uint32_t)strlen(result->status)});
    jsonw_raw(w,",\"catalog\":");if(result->catalog)jsonw_value(w,yyjson_doc_get_root(result->catalog));else jsonw_raw(w,"null");
    jsonw_raw(w,",\"fetched_at_ms\":");if(result->has_fetched_at)jsonw_i64(w,result->fetched_at_ms);else jsonw_raw(w,"null");
    jsonw_raw(w,",\"checked_at_ms\":");if(result->has_checked_at)jsonw_i64(w,result->checked_at_ms);else jsonw_raw(w,"null");
    jsonw_raw(w,",\"messages\":[");for(CatalogMessage *message=result->messages;message;message=message->next){if(message!=result->messages)jsonw_raw(w,",");jsonw_string(w,message->text);}jsonw_raw(w,"]}");
}
void catalog_result_destroy(CatalogResult *result) {yyjson_doc_free(result->catalog);yyjson_doc_free(result->artifact);arena_destroy(&result->arena);*result=(CatalogResult){0};}

struct CatalogFetch {
    pthread_t thread;
    pthread_mutex_t mutex;
    pthread_cond_t finished;
    bool cancel,done,offline,refresh;
#ifdef COLOPHON_TESTING
    bool pending_input,pending_started;
#endif
    char *path,*url;
    int64_t now,connect_ms,body_ms,join_ms;
    CatalogResult result;
    Err error;
};
typedef struct {
    CatalogFetch *fetch;
    JsonWriter body,etag;
    bool headers,etag_seen,etag_line;
    int64_t start,body_start,last_byte;
    long status;
} Transfer;
static pthread_once_t curl_once=PTHREAD_ONCE_INIT;
static CURLcode curl_init_status;
static void initialize_curl(void){curl_init_status=curl_global_init(CURL_GLOBAL_DEFAULT);}
static int64_t monotonic_ms(void) {
    struct timespec time;if(clock_gettime(CLOCK_MONOTONIC,&time))return -1;
    return (int64_t)time.tv_sec*1000+time.tv_nsec/1000000;
}
static bool fetch_cancelled(CatalogFetch *fetch) {
    pthread_mutex_lock(&fetch->mutex);bool cancelled=fetch->cancel;pthread_mutex_unlock(&fetch->mutex);return cancelled;
}
static size_t fetch_body(char *bytes,size_t size,size_t count,void *context) {
    Transfer *transfer=context;if(size&&count>SIZE_MAX/size)return 0;size_t length=size*count;
    transfer->last_byte=monotonic_ms();
    if(length>UINT32_MAX-transfer->body.length)return 0;
    jsonw_bytes(&transfer->body,bytes,length);return transfer->body.error.code?0:length;
}
static void header_latin1(JsonWriter *writer,const char *bytes,size_t length) {
    for(size_t i=0;i<length;i++){char encoded[4];size_t n=str_encode_codepoint((unsigned char)bytes[i],encoded);jsonw_bytes(writer,encoded,n);}
}
static size_t fetch_header(char *bytes,size_t size,size_t count,void *context) {
    Transfer *transfer=context;if(size&&count>SIZE_MAX/size)return 0;size_t length=size*count;
    if(transfer->headers)return length; /* trailers and later interim blocks */
    transfer->last_byte=monotonic_ms();
    if(length>=5&&!memcmp(bytes,"HTTP/",5)) {
        transfer->status=0;const char *space=memchr(bytes,' ',length);
        if(space&&bytes+length-space>=4&&space[1]>='0'&&space[1]<='9'&&space[2]>='0'&&space[2]<='9'&&space[3]>='0'&&space[3]<='9')
            transfer->status=(space[1]-'0')*100+(space[2]-'0')*10+space[3]-'0';
        jsonw_free(&transfer->etag);transfer->etag_seen=false;transfer->etag_line=false;
    } else if(length==2&&!memcmp(bytes,"\r\n",2)) {
        /* http.client skips only 100; 101/103 are returned as error statuses.
         * Once this boundary is reached, trailers cannot restart the phase. */
        if(transfer->status>=100&&transfer->status!=100){transfer->headers=true;transfer->body_start=transfer->last_byte;}
    } else if(length>=5&&!strncasecmp(bytes,"ETag:",5)) {
        size_t begin=5,end=length;while(begin<end&&(bytes[begin]==' '||bytes[begin]=='\t'))begin++;
        while(end>begin&&(bytes[end-1]=='\r'||bytes[end-1]=='\n'))end--;
        if(transfer->etag_seen)jsonw_raw(&transfer->etag,", ");
        header_latin1(&transfer->etag,bytes+begin,end-begin);transfer->etag_seen=true;transfer->etag_line=true;
    } else if(length&&(bytes[0]==' '||bytes[0]=='\t')&&transfer->etag_line) {
        size_t end=length;while(end&&(bytes[end-1]=='\r'||bytes[end-1]=='\n'))end--;
        jsonw_raw(&transfer->etag,"\r\n");header_latin1(&transfer->etag,bytes,end);
    } else transfer->etag_line=false;
    return transfer->etag.error.code?0:length;
}
static Err fetch_diagnostic(CatalogResult *out,const char *message) {
    JsonWriter diagnostic={0};jsonw_raw(&diagnostic,"catalog fetch failed: ");jsonw_raw(&diagnostic,message);
    Err error=diagnostic.error;if(!error.code)error=catalog_message(out,(Str){diagnostic.data,(uint32_t)diagnostic.length});jsonw_free(&diagnostic);return error;
}
static Err validate_fetch_url(const char *url,CURLU **parsed,JsonWriter *reason,const char **diagnostic) {
    /* urlsplit strips leading C0/space and removes TAB/CR/LF. Validate the
     * authored scheme/authority before curl can repair http:///host into a host. */
    JsonWriter cleaned={0};while(*url&&(unsigned char)*url<=32)url++;
    for(const char *p=url;*p;p++)if(*p!='\t'&&*p!='\r'&&*p!='\n')jsonw_bytes(&cleaned,p,1);
    if(cleaned.error.code){Err error=cleaned.error;jsonw_free(&cleaned);return error;}
    const char *text=cleaned.data?cleaned.data:"",*colon=strchr(text,':');size_t scheme=colon?(size_t)(colon-text):0;
    bool scheme_valid=scheme&&((text[0]>='A'&&text[0]<='Z')||(text[0]>='a'&&text[0]<='z'));
    for(size_t i=1;i<scheme;i++)if(!((text[i]>='A'&&text[i]<='Z')||(text[i]>='a'&&text[i]<='z')||(text[i]>='0'&&text[i]<='9')||text[i]=='+'||text[i]=='-'||text[i]=='.'))scheme_valid=false;
    if(!scheme_valid)scheme=0;
    if(!((scheme==4&&!strncasecmp(text,"http",4))||(scheme==5&&!strncasecmp(text,"https",5)))) {
        jsonw_raw(reason,"unsupported catalog URL scheme: ");
        for(size_t i=0;i<scheme;i++){char lower=text[i]>='A'&&text[i]<='Z'?text[i]+('a'-'A'):text[i];jsonw_bytes(reason,&lower,1);}
        *diagnostic=reason->data;jsonw_free(&cleaned);return reason->error;
    }
    const char *authority=colon+1;
    if(strncmp(authority,"//",2)||!authority[2]||strchr("/?#",authority[2])) {
        *diagnostic="catalog URL requires a host and no credentials";jsonw_free(&cleaned);return ERR_SUCCESS;
    }
    authority+=2;size_t length=strcspn(authority,"/?#");
    if(memchr(authority,'@',length)){*diagnostic="catalog URL requires a host and no credentials";jsonw_free(&cleaned);return ERR_SUCCESS;}
    *parsed=curl_url();if(!*parsed){jsonw_free(&cleaned);return err_make(ERR_NOMEM,"catalog URL allocation");}
    CURLUcode code=curl_url_set(*parsed,CURLUPART_URL,text,CURLU_PATH_AS_IS);jsonw_free(&cleaned);
    if(code){*diagnostic=curl_url_strerror(code);return ERR_SUCCESS;}
    char *host=NULL;curl_url_get(*parsed,CURLUPART_HOST,&host,0);
    if(!host||!*host)*diagnostic="catalog URL requires a host and no credentials";
    curl_free(host);return ERR_SUCCESS;
}
static Err decode_fetched(Str raw,yyjson_doc **out,const char **diagnostic) {
    yyjson_doc *document=NULL;*out=NULL;Err error=catalog_raw_read(raw,"catalog",&document,diagnostic);
    if(!error.code) {
        if(!document){if(!*diagnostic)*diagnostic="invalid JSON";}
        else if(!get(yyjson_doc_get_root(document),"openai"))*diagnostic="catalog JSON has no openai provider";
        else error=catalog_sanitize(yyjson_doc_get_root(document),out,true);
    }
    yyjson_doc_free(document);return error;
}
static Err perform_fetch(CatalogFetch *fetch) {
    CatalogResult *out=&fetch->result;Str url={fetch->url,(uint32_t)strlen(fetch->url)};
    Err error=catalog_load_offline(fetch->path,url,out);if(error.code||fetch->offline)return error;
    bool same_url=out->catalog&&str_equal(out->url,url);
    out->status=out->catalog?"cached":"unavailable";
    pthread_once(&curl_once,initialize_curl);
    CURLU *parsed=NULL;CURL *easy=NULL;CURLM *multi=NULL;struct curl_slist *request_headers=NULL;
    Transfer transfer={.fetch=fetch};yyjson_doc *decoded=NULL;JsonWriter artifact={0},url_reason={0};
    const char *diagnostic=NULL;bool timeout=false,body_timeout=false,added=false;
    if(curl_init_status!=CURLE_OK){diagnostic="HTTP initialization failed";goto done;}
    error=validate_fetch_url(fetch->url,&parsed,&url_reason,&diagnostic);if(error.code||diagnostic)goto done;
    easy=curl_easy_init();multi=curl_multi_init();
    if(!easy||!multi){error=err_make(ERR_NOMEM,"catalog HTTP allocation");goto done;}
    request_headers=curl_slist_append(NULL,"Accept:");
    if(!request_headers){error=err_make(ERR_NOMEM,"catalog header allocation");goto done;}
    struct curl_slist *grown_headers=curl_slist_append(request_headers,"Accept-Encoding: identity");
    if(!grown_headers){error=err_make(ERR_NOMEM,"catalog header allocation");goto done;}request_headers=grown_headers;
    bool conditional=same_url&&get(yyjson_doc_get_root(out->catalog),"anthropic")&&out->has_etag&&out->etag.n&&!fetch->refresh;
    if(conditional&&memchr(out->etag.p,0,out->etag.n)) {
        /* Approved invalid-header boundary: retain the cached JSON label, but
         * do not truncate or send it through libcurl's C-string header API. */
        event_note("http_header_unsupported","pricing-cache.json:etag",1);
        conditional=false;
    }
    if(conditional) {
        JsonWriter header={0};jsonw_raw(&header,"If-None-Match: ");size_t offset=0;uint32_t cp;
        while(offset<out->etag.n) {
            if(!str_decode_next(out->etag,&offset,&cp)||cp>255){diagnostic="invalid HTTP header encoding";break;}
            char byte=(char)cp;jsonw_bytes(&header,&byte,1);
        }
        for(size_t i=0;!diagnostic&&i<header.length;i++) {
            if((header.data[i]=='\n'&&(i+1==header.length||(header.data[i+1]!=' '&&header.data[i+1]!='\t')))||
               (header.data[i]=='\r'&&(i+1==header.length||(header.data[i+1]!=' '&&header.data[i+1]!='\t'&&header.data[i+1]!='\n'))))diagnostic="invalid HTTP header value";
        }
        if(diagnostic){out->has_checked_at=true;out->checked_at_ms=fetch->now;jsonw_free(&header);goto done;}
        if(header.error.code){error=header.error;jsonw_free(&header);goto done;}
        grown_headers=curl_slist_append(request_headers,header.data);jsonw_free(&header);
        if(!grown_headers){error=err_make(ERR_NOMEM,"catalog header allocation");goto done;}request_headers=grown_headers;
    }
    CURLcode setup=CURLE_OK;
#define SET(option,value) do{if(setup==CURLE_OK)setup=curl_easy_setopt(easy,option,value);}while(0)
    SET(CURLOPT_CURLU,parsed);SET(CURLOPT_PATH_AS_IS,1L);SET(CURLOPT_NOPROXY,"*");SET(CURLOPT_FOLLOWLOCATION,0L);SET(CURLOPT_NOSIGNAL,1L);
    SET(CURLOPT_PROTOCOLS_STR,"http,https");SET(CURLOPT_HTTP_VERSION,CURL_HTTP_VERSION_1_1);
    SET(CURLOPT_CONNECTTIMEOUT_MS,(long)(fetch->connect_ms?fetch->connect_ms:1));
    SET(CURLOPT_HEADERFUNCTION,fetch_header);SET(CURLOPT_HEADERDATA,&transfer);
    SET(CURLOPT_WRITEFUNCTION,fetch_body);SET(CURLOPT_WRITEDATA,&transfer);SET(CURLOPT_HTTPHEADER,request_headers);
#undef SET
    if(setup!=CURLE_OK){diagnostic=curl_easy_strerror(setup);goto done;}
    out->has_checked_at=true;out->checked_at_ms=fetch->now;
    transfer.start=transfer.last_byte=monotonic_ms();
    if(transfer.start<0){diagnostic="monotonic clock unavailable";goto done;}
    if(curl_multi_add_handle(multi,easy)!=CURLM_OK){diagnostic="HTTP transfer initialization failed";goto done;}added=true;
    int running=1;CURLcode result=CURLE_OK;bool complete=false,header_checkpoint=false;
    while(!complete&&!fetch_cancelled(fetch)) {
        int64_t now=monotonic_ms();
        bool body=transfer.headers&&transfer.status==200;
        int64_t budget=body?fetch->body_ms:fetch->connect_ms;
        int64_t phase_start=body?transfer.body_start:transfer.start;
        int64_t remaining=budget-(now-phase_start),stall=budget-(now-transfer.last_byte);
        if(now<0){diagnostic="monotonic clock unavailable";break;}
        if(remaining<=0||stall<=0){timeout=true;body_timeout=body;break;}
        CURLMcode code=curl_multi_perform(multi,&running);
        if(code!=CURLM_OK){diagnostic=curl_multi_strerror(code);break;}
        if(transfer.headers&&!header_checkpoint) {
            header_checkpoint=true;
            if(cp_fault("catalog_timer")){timeout=true;break;}
            if(transfer.status==304||transfer.status!=200){complete=true;break;}
        }
        int queued;CURLMsg *message;
        while((message=curl_multi_info_read(multi,&queued)))if(message->msg==CURLMSG_DONE){result=message->data.result;complete=true;}
        if(complete)break;
        /* Recompute after callbacks change phases; wake within cancellation
         * granularity while preserving subsecond total and last-byte budgets. */
        now=monotonic_ms();body=transfer.headers&&transfer.status==200;budget=body?fetch->body_ms:fetch->connect_ms;
        phase_start=body?transfer.body_start:transfer.start;
        remaining=budget-(now-phase_start);stall=budget-(now-transfer.last_byte);
        int64_t wait=remaining<stall?remaining:stall;if(wait<0)wait=0;if(wait>50)wait=50;
        code=curl_multi_poll(multi,NULL,0,(int)wait,NULL);
        if(code!=CURLM_OK){diagnostic=curl_multi_strerror(code);break;}
    }
    if(fetch_cancelled(fetch))goto done;
    if(timeout){error=catalog_message(out,body_timeout?STR_LIT("catalog body timeout"):STR_LIT("catalog connect/headers timeout"));goto done;}
    if(diagnostic)goto done;
    if(transfer.body.error.code||transfer.etag.error.code){error=transfer.body.error.code?transfer.body.error:transfer.etag.error;goto done;}
    if(result!=CURLE_OK) {
        if(result==CURLE_OPERATION_TIMEDOUT){error=catalog_message(out,transfer.headers?STR_LIT("catalog body timeout"):STR_LIT("catalog connect/headers timeout"));goto done;}
        diagnostic=result==CURLE_PARTIAL_FILE?"catalog body ended before its Content-Length":curl_easy_strerror(result);goto done;
    }
    if(transfer.status==304) {
        if(!same_url)diagnostic="catalog HTTP 304 without a matching cached catalog";
        else out->status="not_modified";
        goto done;
    }
    if(transfer.status!=200){char message[80];snprintf(message,sizeof message,"catalog HTTP status %ld",transfer.status);error=fetch_diagnostic(out,message);goto done;}
    if(cp_fault("catalog_timer")||monotonic_ms()-transfer.body_start>=fetch->body_ms){error=catalog_message(out,STR_LIT("catalog body timeout"));goto done;}
    if(transfer.body.error.code){error=transfer.body.error;goto done;}
    error=decode_fetched((Str){transfer.body.data,(uint32_t)transfer.body.length},&decoded,&diagnostic);
    if(error.code||diagnostic)goto done;
    jsonw_raw(&artifact,"{\"schema\":1,\"etag\":");
    if(transfer.etag_seen)jsonw_string(&artifact,(Str){transfer.etag.data,(uint32_t)transfer.etag.length});else jsonw_raw(&artifact,"null");
    jsonw_raw(&artifact,",\"fetched_at_ms\":");jsonw_i64(&artifact,fetch->now);jsonw_raw(&artifact,",\"url\":");jsonw_string(&artifact,url);
    jsonw_raw(&artifact,",\"catalog\":");jsonw_value(&artifact,yyjson_doc_get_root(decoded));jsonw_raw(&artifact,"}\n");
    error=artifact.error;if(error.code)goto done;
    pthread_mutex_lock(&fetch->mutex);
    if(!fetch->cancel) {
        error=cp_fault("catalog_replace")?err_make(ERR_IO,"Synthetic cache replace failure"):atomic_write(fetch->path,artifact.data,artifact.length);
        if(!error.code){yyjson_doc_free(out->catalog);out->catalog=decoded;decoded=NULL;out->status="fetched";out->has_fetched_at=true;out->fetched_at_ms=fetch->now;}
    }
    pthread_mutex_unlock(&fetch->mutex);
    if(error.code==ERR_IO){diagnostic=error.message;error=fetch_diagnostic(out,diagnostic);diagnostic=NULL;}
done:
    if(diagnostic&&!error.code)error=fetch_diagnostic(out,diagnostic);
    if(added)curl_multi_remove_handle(multi,easy);curl_easy_cleanup(easy);curl_multi_cleanup(multi);curl_url_cleanup(parsed);curl_slist_free_all(request_headers);
    yyjson_doc_free(decoded);jsonw_free(&artifact);jsonw_free(&url_reason);jsonw_free(&transfer.body);jsonw_free(&transfer.etag);return error;
}
static void *fetch_worker(void *context) {
    CatalogFetch *fetch=context;
#ifdef COLOPHON_TESTING
    if(fetch->pending_input){
        pthread_mutex_lock(&fetch->mutex);fetch->pending_started=true;pthread_cond_broadcast(&fetch->finished);
        while(!fetch->cancel){struct timespec wait={0,50000000};pthread_cond_timedwait_relative_np(&fetch->finished,&fetch->mutex,&wait);}
        pthread_mutex_unlock(&fetch->mutex);
    }else
#endif
    fetch->error=perform_fetch(fetch);
    pthread_mutex_lock(&fetch->mutex);fetch->done=true;pthread_cond_signal(&fetch->finished);pthread_mutex_unlock(&fetch->mutex);return NULL;
}
static void fetch_destroy(CatalogFetch *fetch) {
    catalog_result_destroy(&fetch->result);pthread_cond_destroy(&fetch->finished);pthread_mutex_destroy(&fetch->mutex);free(fetch->path);free(fetch->url);free(fetch);
}
Err catalog_fetch_start(const char *path,Str url,bool offline,bool refresh,int64_t now,CatalogFetch **out) {
    *out=NULL;if(!path||!url.p||memchr(url.p,0,url.n))return err_make(ERR_INVALID,"invalid catalog request");
    CatalogFetch *fetch=calloc(1,sizeof *fetch);if(!fetch)return err_make(ERR_NOMEM,"catalog thread allocation");
    fetch->path=strdup(path);fetch->url=malloc((size_t)url.n+1);
    if(!fetch->path||!fetch->url){free(fetch->path);free(fetch->url);free(fetch);return err_make(ERR_NOMEM,"catalog thread allocation");}
    memcpy(fetch->url,url.p,url.n);fetch->url[url.n]=0;fetch->offline=offline;fetch->refresh=refresh;fetch->now=now;
#ifdef COLOPHON_TESTING
    fetch->pending_input=cp_fault("original_catalog_pending");
#endif
    fetch->connect_ms=cp_catalog_budget("COLOPHON_TEST_CONNECT_TIMEOUT_MS",3000);
    fetch->body_ms=cp_catalog_budget("COLOPHON_TEST_BODY_TIMEOUT_MS",30000);
    /* Hook values are bounded to an hour, so this sum cannot overflow. */
    fetch->join_ms=fetch->connect_ms+fetch->body_ms+cp_catalog_budget("COLOPHON_TEST_JOIN_EXTRA_MS",5000);
    if(fetch->join_ms<0)fetch->join_ms=0;
    int code=pthread_mutex_init(&fetch->mutex,NULL);
    if(code){free(fetch->path);free(fetch->url);free(fetch);return err_make(ERR_IO,"catalog mutex initialization failed");}
    code=pthread_cond_init(&fetch->finished,NULL);
    if(code){pthread_mutex_destroy(&fetch->mutex);free(fetch->path);free(fetch->url);free(fetch);return err_make(ERR_IO,"catalog condition initialization failed");}
    pthread_attr_t attributes;code=pthread_attr_init(&attributes);
    if(!code){code=pthread_attr_setstacksize(&attributes,512u*1024u);if(!code)code=pthread_create(&fetch->thread,&attributes,fetch_worker,fetch);pthread_attr_destroy(&attributes);}
    if(code){fetch_destroy(fetch);return err_make(ERR_IO,"catalog thread start failed: %s",strerror(code));}
#ifdef COLOPHON_TESTING
    if(fetch->pending_input){pthread_mutex_lock(&fetch->mutex);while(!fetch->pending_started)pthread_cond_wait(&fetch->finished,&fetch->mutex);pthread_mutex_unlock(&fetch->mutex);}
#endif
    *out=fetch;return ERR_SUCCESS;
}
void catalog_fetch_cancel(CatalogFetch **owner) {
    CatalogFetch *fetch=*owner;if(!fetch)return;
    pthread_mutex_lock(&fetch->mutex);fetch->cancel=true;pthread_mutex_unlock(&fetch->mutex);
    pthread_join(fetch->thread,NULL);fetch_destroy(fetch);*owner=NULL;
}
Err catalog_fetch_finish(CatalogFetch **owner,CatalogResult *out) {
    CatalogFetch *fetch=*owner;if(!fetch)return err_make(ERR_INVALID,"missing catalog thread");
    int64_t started=monotonic_ms();bool timed_out=false;
    pthread_mutex_lock(&fetch->mutex);
    while(!fetch->done) {
        int64_t remaining=fetch->join_ms-(monotonic_ms()-started);
        if(started<0||remaining<=0){timed_out=true;fetch->cancel=true;break;}
        struct timespec wait={remaining/1000,(remaining%1000)*1000000};
        int code=pthread_cond_timedwait_relative_np(&fetch->finished,&fetch->mutex,&wait);
        if(code&&code!=ETIMEDOUT){timed_out=true;fetch->cancel=true;break;}
    }
    pthread_mutex_unlock(&fetch->mutex);pthread_join(fetch->thread,NULL);
    Err error=fetch->error;
    if(timed_out) {
        error=catalog_load_offline(fetch->path,(Str){fetch->url,(uint32_t)strlen(fetch->url)},out);
        out->status=out->catalog?"cached":"unavailable";
        if(!error.code)error=catalog_message(out,STR_LIT("catalog fetch did not finish; using cached catalog"));
    } else {*out=fetch->result;fetch->result=(CatalogResult){0};}
    fetch_destroy(fetch);*owner=NULL;return error;
}
