#include "model.h"
#include "parse/tokenstream.h"
#include <string.h>
#include <stdio.h>
#define TRY(x) do {Err e_=(x);if(e_.code)return e_;}while(0)
static Str text(AgMismatches *m,Str input,uint32_t n) {Str v={0};ag_wire_text(m,AG_MODEL_INFO,input,n,&v);return token_model_trim(v);}
static Str pricing_alias(const PricingRules *rules,Str lower) {return rules_alias(rules,"antigravity",lower);}
Err antigravity_strip_routing(const PricingRules *rules,Arena *arena,Str raw,Str *out) {
    Str s=token_model_trim(raw),lower;TRY(str_lower(arena,s,&lower));
    yyjson_val *suffixes=rules_section(rules,"antigravity_routing_suffixes",true);if(!suffixes)suffixes=rules_section(rules,"antigravity_routing_suffixes",false);
    size_t i,count;yyjson_val *item;yyjson_arr_foreach(suffixes,i,count,item){size_t n=yyjson_get_len(item);const char *suffix=yyjson_get_str(item);if(s.n>n&&!memcmp(lower.p+lower.n-n,suffix,n)){s.n-=(uint32_t)n;lower.n-=(uint32_t)n;break;}}
    return str_copy(arena,s,out);
}
Err antigravity_normalize_model(const PricingRules *rules,Arena *arena,Str raw,Str *out) {
    Str s=token_model_trim(raw),lower;TRY(str_lower(arena,s,&lower));
    /* Offline fallback retains its pinned alias precedence. */
    Str alias=pricing_alias(rules,lower);if(alias.n)return str_copy(arena,alias,out);
    TRY(antigravity_strip_routing(rules,arena,s,&s));TRY(str_lower(arena,s,&lower));
    alias=pricing_alias(rules,lower);if(alias.n)s=alias;
    return str_copy(arena,s,out);
}
Err antigravity_model_typed(const PricingRules *rules,AgMismatches *m,Arena *arena,Str response,Str usage,Str metadata,Str previous,const Omap *numbers,Str *raw,Str *normalized) {
    Str value=token_model_trim(response);uint64_t model=0;
    bool has_model=!value.n&&ag_wire_uint(m,AG_USAGE,usage,1,&model)==AG_FOUND;
    char key[32];int n=snprintf(key,sizeof key,"%llu",(unsigned long long)model);
    if(!value.n&&has_model&&numbers){Str *learned=omap_get(numbers,(Str){key,(uint32_t)n});if(learned)value=*learned;}
    if(!value.n){Str info={0};TRY(antigravity_message_merge_typed(m,AG_STEP_METADATA,arena,metadata,24,&info));value=text(m,info,12);if(!value.n)value=text(m,info,8);}
    if(!value.n)value=previous;
    if(!value.n&&has_model){char marker[64];int len=snprintf(marker,sizeof marker,"antigravity/model-%llu",(unsigned long long)model);TRY(str_copy(arena,(Str){marker,(uint32_t)len},&value));}
    if(!value.n)value=STR_LIT("antigravity/unattributed");
    *raw=value;return antigravity_normalize_model(rules,arena,value,normalized);
}
Err antigravity_model(const PricingRules *rules,Arena *arena,Str response,Str usage,Str metadata,Str previous,const Omap *numbers,Str *raw,Str *normalized){return antigravity_model_typed(rules,NULL,arena,response,usage,metadata,previous,numbers,raw,normalized);}
