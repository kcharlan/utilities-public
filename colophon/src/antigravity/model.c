#include "model.h"
#include "parse/tokenstream.h"
#include <string.h>
#include <stdio.h>
#define TRY(x) do {Err e_=(x);if(e_.code)return e_;}while(0)
static Str text(AgMismatches *m,Str input,uint32_t n) {Str v={0};ag_wire_text(m,AG_MODEL_INFO,input,n,&v);return token_model_trim(v);}
static Str pricing_alias(Str lower) {
    const char *aliases[][2]={{"gemini-pro-default","gemini-3.1-pro-preview"},{"gemini-pro-agent","gemini-3.1-pro-preview"},{"gemini-3.1-pro","gemini-3.1-pro-preview"},{"gemini-3.1-pro-high","gemini-3.1-pro-preview"},{"gemini-3.1-pro-low","gemini-3.1-pro-preview"},{"gemini-3.7-flash-safety-le","gemini-3.7-flash"}};
    for(size_t i=0;i<sizeof aliases/sizeof *aliases;i++)if(str_equal(lower,(Str){aliases[i][0],(uint32_t)strlen(aliases[i][0])}))return (Str){aliases[i][1],(uint32_t)strlen(aliases[i][1])};
    return (Str){0};
}
Err antigravity_normalize_model(Arena *arena,Str raw,Str *out) {
    Str s=token_model_trim(raw),lower;TRY(str_lower(arena,s,&lower));
    /* Pinned order: exact alias, one routing suffix, then alias again. */
    Str alias=pricing_alias(lower);if(alias.n)return str_copy(arena,alias,out);
    const char *suffixes[]={"-tiered","-low","-thinking","-medium","-high","-trial"};
    for(size_t i=0;i<sizeof suffixes/sizeof *suffixes;i++){size_t n=strlen(suffixes[i]);if(s.n>n&&!memcmp(lower.p+lower.n-n,suffixes[i],n)){s.n-=(uint32_t)n;lower.n-=(uint32_t)n;break;}}
    alias=pricing_alias(lower);if(alias.n)s=alias;
    return str_copy(arena,s,out);
}
Err antigravity_model_typed(AgMismatches *m,Arena *arena,Str response,Str usage,Str metadata,Str previous,const Omap *numbers,Str *raw,Str *normalized) {
    Str value=token_model_trim(response);uint64_t model=0;
    bool has_model=!value.n&&ag_wire_uint(m,AG_USAGE,usage,1,&model)==AG_FOUND;
    char key[32];int n=snprintf(key,sizeof key,"%llu",(unsigned long long)model);
    if(!value.n&&has_model&&numbers){Str *learned=omap_get(numbers,(Str){key,(uint32_t)n});if(learned)value=*learned;}
    if(!value.n){Str info={0};TRY(antigravity_message_merge_typed(m,AG_STEP_METADATA,arena,metadata,24,&info));value=text(m,info,12);if(!value.n)value=text(m,info,8);}
    if(!value.n)value=previous;
    if(!value.n&&has_model){char marker[64];int len=snprintf(marker,sizeof marker,"antigravity/model-%llu",(unsigned long long)model);TRY(str_copy(arena,(Str){marker,(uint32_t)len},&value));}
    if(!value.n)value=STR_LIT("antigravity/unattributed");
    *raw=value;return antigravity_normalize_model(arena,value,normalized);
}
Err antigravity_model(Arena *arena,Str response,Str usage,Str metadata,Str previous,const Omap *numbers,Str *raw,Str *normalized){return antigravity_model_typed(NULL,arena,response,usage,metadata,previous,numbers,raw,normalized);}
