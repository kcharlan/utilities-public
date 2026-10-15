#include "claude_model.h"
#include "claude/foundation.h"
#include "gen/assets.h"
#include "parse/tokenstream.h"
#include "util/json_read.h"
#include "util/json_number.h"
#include <stdlib.h>
#include <string.h>
#define TRY(x) do {Err e_=(x);if(e_.code)return e_;}while(0)
static yyjson_val *get(yyjson_val *v,const char *k){return obj_get_last(v,(Str){k,(uint32_t)strlen(k)});}
static bool prefix(Str v,const char *p){return price_literal_parts(v,(Str){p,(uint32_t)strlen(p)},STR_LIT(""),false)==0;}
Err normalize_claude_model(Arena *arena,Str raw,Str *out) {
    Str v=token_model_trim(raw);
    if(prefix(v,"anthropic."))v=(Str){v.p+10,v.n-10};
    size_t dot=price_literal_parts(v,STR_LIT("."),STR_LIT(""),true);
    if(dot!=SIZE_MAX&&price_literal_parts(v,STR_LIT("claude-"),STR_LIT(""),false)!=SIZE_MAX){Str tail={v.p+dot+1,v.n-(uint32_t)dot-1};if(prefix(tail,"claude-"))v=tail;}
    size_t suffix;TRY(claude_foundation_model_suffix(v,true,&suffix));if(suffix!=SIZE_MAX)v.n=(uint32_t)suffix;
    JsonRead seed=json_read((Str){(const char *)cp_asset_curated_bundled_claude,(uint32_t)cp_asset_curated_bundled_claude_len},STR,JSON_CONSTANTS_REJECT,"claude.bundled");
    if(seed.status!=JSON_OK){json_read_free(&seed);return err_make(ERR_INVALID,"invalid Claude bundled prices");}
    yyjson_val *models=get(yyjson_doc_get_root(seed.doc),"claude");
    Err e=claude_foundation_model_suffix(v,false,&suffix);
    if(!e.code&&suffix!=SIZE_MAX){Str base={v.p,(uint32_t)suffix};if(obj_get_last(models,base))v=base;}
    if(!e.code)e=str_copy(arena,v,out);json_read_free(&seed);return e;
}
static const char *preferred(Str lower) {
    if(prefix(lower,"claude-"))return "anthropic";
    if(prefix(lower,"gpt-")||prefix(lower,"chatgpt-")||prefix(lower,"text-embedding-"))return "openai";
    const char *reasoning[]={"o1","o3","o4"};for(size_t i=0;i<3;i++){Str family={reasoning[i],2};if(str_equal(lower,family)||(lower.n>2&&!memcmp(lower.p,family.p,2)&&lower.p[2]=='-'))return "openai";}
    const char *google[]={"gemini-","gemma-","deep-research-","veo-","lyria-"};for(size_t i=0;i<5;i++)if(prefix(lower,google[i]))return "google";
    if(str_equal(lower,STR_LIT("kimi-for-coding"))||str_equal(lower,STR_LIT("k3"))||str_equal(lower,STR_LIT("k3[1m]"))||prefix(lower,"k3-"))return "kimi-for-coding";
    if(prefix(lower,"kimi-")||prefix(lower,"moonshot-"))return "moonshot";
    if(prefix(lower,"minimax-"))return "minimax";
    if(prefix(lower,"deepseek-"))return "deepseek";
    return NULL;
}
Err claude_models_dev_lookup(Arena *arena,ModelsDevIndex *index,Str raw,ClaudeLookup *out) {
    *out=(ClaudeLookup){0};if(!index)return ERR_SUCCESS;
    Str trimmed=token_model_trim(raw);if(!trimmed.n)return ERR_SUCCESS;
    const char *providers[]={"anthropic","openai","google","moonshot","kimi-for-coding","minimax","deepseek","kimi-coding","opencode","opencode-free"};
    Str normalized,lower;TRY(normalize_claude_model(arena,trimmed,&normalized));TRY(str_lower(arena,normalized,&lower));const char *vendor=preferred(lower);
    size_t slash=price_literal_parts(trimmed,STR_LIT("/"),STR_LIT(""),false);bool explicit=slash!=SIZE_MAX;
    Str route={0},model=trimmed;
    bool codex_route=false;
    if(explicit){TRY(str_lower(arena,(Str){trimmed.p,(uint32_t)slash},&route));model=(Str){trimmed.p+slash+1,trimmed.n-(uint32_t)slash-1};if(!model.n||!route.n)return ERR_SUCCESS;
        codex_route=str_equal(route,STR_LIT("openai"))||str_equal(route,STR_LIT("deepseek"))||str_equal(route,STR_LIT("kimi-coding"))||str_equal(route,STR_LIT("kimi-for-coding"))||str_equal(route,STR_LIT("opencode"))||str_equal(route,STR_LIT("opencode-free"));
        if(codex_route&&(model.p[0]=='/'||model.p[model.n-1]=='/'))return ERR_SUCCESS;
        if(str_equal(route,STR_LIT("openai")))normalized=normalize_codex_model(model);else if(codex_route)normalized=model;else TRY(normalize_claude_model(arena,model,&normalized));}
    Str routes[10];size_t route_count=0;
    if(explicit){
        bool supported=false;for(size_t p=0;p<sizeof providers/sizeof *providers;p++)if(str_equal(route,(Str){providers[p],(uint32_t)strlen(providers[p])}))supported=true;
        if(!supported)return ERR_SUCCESS;
        routes[route_count++]=route;
        if(str_equal(route,STR_LIT("kimi-coding")))routes[route_count++]=STR_LIT("kimi-for-coding");
        if(str_equal(route,STR_LIT("opencode-free")))routes[route_count++]=STR_LIT("opencode");
    } else for(size_t p=0;p<7;p++){
        if(vendor&&strcmp(vendor,providers[p])&&!(strcmp(vendor,"moonshot")==0&&strcmp(providers[p],"kimi-for-coding")==0))continue;
        routes[route_count++]=(Str){providers[p],(uint32_t)strlen(providers[p])};
    }
    size_t matched_providers=0;bool kimi_alias=false;
    for(size_t p=0;p<route_count;p++){
        Str provider=routes[p];
        Str targets[3]={model,normalized,STR_LIT("k3")};size_t count=str_equal(model,normalized)?1:2;
        kimi_alias|=str_equal(provider,STR_LIT("kimi-for-coding"))&&(str_equal(token_model_trim(model),STR_LIT("k3[1m]"))||str_equal(token_model_trim(normalized),STR_LIT("k3[1m]")));
        CatalogLookup lookup={0};
        for(size_t t=0;t<count;t++){TRY(claude_catalog_pricing(index,provider,targets[t],&lookup));if(lookup.model)break;}
        if(!lookup.model)continue;
        if(explicit||vendor){*out=(ClaudeLookup){lookup,provider};return ERR_SUCCESS;}
        if(++matched_providers==1)*out=(ClaudeLookup){lookup,provider};else *out=(ClaudeLookup){0};
    }
    if(!out->catalog.model&&kimi_alias){CatalogLookup lookup;TRY(claude_catalog_pricing(index,STR_LIT("kimi-for-coding"),STR_LIT("k3"),&lookup));if(lookup.model)*out=(ClaudeLookup){lookup,STR_LIT("kimi-for-coding")};}
    return ERR_SUCCESS;
}
static Str without_date(Str s) {
    const size_t widths[]={11,9};for(size_t w=0;w<2;w++){size_t n=widths[w];if(s.n<=n)continue;Str tail={s.p+s.n-n,(uint32_t)n};bool match=true;for(size_t i=0;i<n;i++){bool dash=i==0||(n==11&&(i==5||i==8));if(dash?tail.p[i]!='-':tail.p[i]<'0'||tail.p[i]>'9'){match=false;break;}}if(match)return (Str){s.p,s.n-(uint32_t)n};}return s;
}
static Str alias(Str s){if(str_equal(s,STR_LIT("gpt-reserve")))return STR_LIT("gpt-5.6-luna");if(str_equal(s,STR_LIT("gpt-5.6")))return STR_LIT("gpt-5.6-sol");if(str_equal(s,STR_LIT("gpt-5.3-spark")))return STR_LIT("gpt-5.3-codex-spark");return s;}
static yyjson_val *exact(yyjson_val *v,Str s){return obj_get_last(v,s);}
Err claude_fast_multiplier(Str model,double *out) {
    *out=1;JsonRead seed=json_read((Str){(const char *)cp_asset_ccusage_fast_multiplier_overrides,(uint32_t)cp_asset_ccusage_fast_multiplier_overrides_len},STR,JSON_CONSTANTS_REJECT,"claude.fast");
    if(seed.status!=JSON_OK){json_read_free(&seed);return err_make(ERR_INVALID,"invalid fast overrides");}
    yyjson_val *root=yyjson_doc_get_root(seed.doc),*ex=get(root,"exact"),*value=exact(ex,model);if(!value)value=exact(ex,alias(model));
    for(size_t start=0;!value&&start<=model.n;){
        size_t end=start;while(end<model.n&&model.p[end]!='/'&&model.p[end]!=':')end++;
        for(size_t offset=start;!value&&offset<=end;){
            Str part={model.p+offset,(uint32_t)(end-offset)},base=without_date(part);value=exact(ex,part);if(!value)value=exact(ex,base);if(!value)value=exact(ex,alias(base));
            if(!value){char *bytes=malloc((size_t)part.n+1);if(!bytes){json_read_free(&seed);return err_make(ERR_NOMEM,"fast model allocation");}for(size_t i=0;i<part.n;i++)bytes[i]=part.p[i]=='.'||part.p[i]=='@'?'-':part.p[i];
                yyjson_obj_iter it=yyjson_obj_iter_with(get(root,"normalized_prefix"));yyjson_val *key;
                while((key=yyjson_obj_iter_next(&it))){
                    Str prefix_key={yyjson_get_str(key),(uint32_t)yyjson_get_len(key)};
                    if(prefix_key.n>part.n)continue;
                    /* ccusage tests only rfind's last occurrence, even when an
                     * earlier occurrence would have a valid suffix boundary. */
                    for(size_t i=(size_t)part.n-prefix_key.n+1;i-->0;){
                        if(memcmp(bytes+i,prefix_key.p,prefix_key.n))continue;
                        size_t end=i+prefix_key.n;
                        if(end==part.n||bytes[end]=='-')value=yyjson_obj_iter_get_val(key);
                        break;
                    }
                    if(value)break;
                }
                free(bytes);
            }
            size_t dot=offset;while(dot<end&&model.p[dot]!='.')dot++;if(dot==end)break;offset=dot+1;
        }
        if(end==model.n)break;start=end+1;
    }
    if(value){PyNum n;if(json_number(value,"claude.fast.multiplier",&n))*out=n.is_float?n.f:(double)n.i;}json_read_free(&seed);return ERR_SUCCESS;
}
