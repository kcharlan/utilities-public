#include "json_number.h"
#include "events.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
bool json_number_is_integer(Str s) {
    size_t i=s.n&&s.p[0]=='-';if(i==s.n)return false;
    for(;i<s.n;i++)if(s.p[i]<'0'||s.p[i]>'9')return false;
    return true;
}
bool json_number(yyjson_val *v,const char *site,PyNum *out) {
    if(yyjson_is_sint(v)){*out=(PyNum){.i=yyjson_get_sint(v)};return true;}
    if(yyjson_is_uint(v)){uint64_t n=yyjson_get_uint(v);if(n>INT64_MAX){event_note("tier2_int",site,1);return false;}*out=(PyNum){.i=(int64_t)n};return true;}
    if(yyjson_is_real(v)){*out=(PyNum){.is_float=true,.f=yyjson_get_real(v)};return true;}
    if(!yyjson_is_raw(v))return false;
    Str s={yyjson_get_raw(v),(uint32_t)yyjson_get_len(v)};
    if(!json_number_is_integer(s)){*out=(PyNum){true,0,strtod(s.p,NULL)};return true;}
    bool neg=s.p[0]=='-';uint64_t n=0,limit=neg?(UINT64_C(1)<<63):INT64_MAX;
    for(size_t i=neg;i<s.n;i++){unsigned d=(unsigned)(s.p[i]-'0');if(n>(limit-d)/10){event_note("tier2_int",site,1);return false;}n=n*10+d;}
    *out=(PyNum){false,neg?(n==(UINT64_C(1)<<63)?INT64_MIN:-(int64_t)n):(int64_t)n,0};return true;
}
bool json_number_equal(yyjson_val *a,yyjson_val *b) {
    if(!yyjson_is_raw(a)||!yyjson_is_raw(b))return false;
    Str sa={yyjson_get_raw(a),(uint32_t)yyjson_get_len(a)},sb={yyjson_get_raw(b),(uint32_t)yyjson_get_len(b)};
    bool ai=json_number_is_integer(sa),bi=json_number_is_integer(sb);
    if(ai&&bi){if(str_equal(sa,STR_LIT("-0")))sa=STR_LIT("0");if(str_equal(sb,STR_LIT("-0")))sb=STR_LIT("0");return str_equal(sa,sb);}
    if(!ai&&!bi)return strtod(sa.p,NULL)==strtod(sb.p,NULL);
    Str integer=ai?sa:sb;double f=strtod(ai?sb.p:sa.p,NULL);
    if(!isfinite(f)||trunc(f)!=f)return false;
    char exact[400];int n=snprintf(exact,sizeof(exact),"%.0f",f);
    if(n<0||(size_t)n>=sizeof(exact))return false;
    if(str_equal(integer,STR_LIT("-0")))integer=STR_LIT("0");
    if(!strcmp(exact,"-0"))return str_equal(integer,STR_LIT("0"));
    return str_equal(integer,(Str){exact,(uint32_t)n});
}
