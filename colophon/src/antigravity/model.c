#include "model.h"
#include "parse/tokenstream.h"
#include <string.h>
#define TRY(x) do {Err e_=(x);if(e_.code)return e_;}while(0)
typedef struct {int64_t value;const char *slug;} Model;
static const Model models[]={
#include "models.inc"
};
Str antigravity_model_enum(int64_t value) {
    size_t lo=0,hi=sizeof models/sizeof *models;
    while(lo<hi){size_t mid=lo+(hi-lo)/2;if(models[mid].value<value)lo=mid+1;else hi=mid;}
    if(lo==sizeof models/sizeof *models||models[lo].value!=value)return (Str){0};
    const char *s=models[lo].slug;return (Str){s,(uint32_t)strlen(s)};
}
static Str text(Str input,uint32_t n) {AgField f={0};return ag_wire_last(input,n,&f)==AG_FOUND?token_model_trim(f.bytes):(Str){0};}
Err antigravity_normalize_model(Arena *arena,Str raw,Str *out) {
    Str s=token_model_trim(raw),lower;TRY(str_lower(arena,s,&lower));
    const char *suffixes[]={"-tiered","-low","-thinking","-medium","-high","-trial"};
    for(size_t i=0;i<sizeof suffixes/sizeof *suffixes;i++){size_t n=strlen(suffixes[i]);if(s.n>n&&!memcmp(lower.p+lower.n-n,suffixes[i],n)){s.n-=(uint32_t)n;lower.n-=(uint32_t)n;break;}}
    const char *aliases[][2]={{"gemini-pro-default","gemini-3.1-pro-preview"},{"gemini-pro-agent","gemini-3.1-pro-preview"},{"gemini-3.1-pro","gemini-3.1-pro-preview"},{"gemini-3.7-flash-safety-le","gemini-3.7-flash"}};
    for(size_t i=0;i<sizeof aliases/sizeof *aliases;i++)if(str_equal(lower,(Str){aliases[i][0],(uint32_t)strlen(aliases[i][0])})){s=(Str){aliases[i][1],(uint32_t)strlen(aliases[i][1])};break;}
    return str_copy(arena,s,out);
}
Err antigravity_model(Arena *arena,Str response,Str usage,Str metadata,Str previous,Str *raw,Str *normalized) {
    Str value=token_model_trim(response);AgField f={0};
    if(!value.n&&ag_wire_last(usage,1,&f)==AG_FOUND)value=antigravity_model_enum((int64_t)f.integer);
    if(!value.n){Str info={0};TRY(antigravity_message_merge(arena,metadata,24,&info));value=text(info,12);if(!value.n)value=text(info,8);}
    if(!value.n)value=previous.n?previous:STR_LIT("antigravity/unattributed");
    *raw=value;return antigravity_normalize_model(arena,value,normalized);
}
