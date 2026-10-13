#include "cost.h"
#include "util/events.h"
#include "util/json_number.h"
#include "util/json_read.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
static yyjson_val *get(yyjson_val *v, const char *key) {
    return obj_get_last(v, (Str){key, (uint32_t)__builtin_strlen(key)});
}
static bool rate(yyjson_val *v, PyNum *out) {
    return json_number(v, "price.rate", out) && (!out->is_float || isfinite(out->f));
}
static bool rates(yyjson_val *v, PriceRates *out) {
    return yyjson_is_obj(v) && rate(get(v,"input"), &out->input) &&
        rate(get(v,"cached_input"), &out->cached_input) &&
        rate(get(v,"cache_write"), &out->cache_write) && rate(get(v,"output"), &out->output);
}
bool price_entry_decode(yyjson_val *v, PriceEntry *out) {
    *out = (PriceEntry){0};
    if (!yyjson_is_obj(v) || !rates(get(v,"per_million"), &out->standard)) return false;
    yyjson_val *long_context = get(v,"long_context");
    if (!long_context || yyjson_is_null(long_context)) return true;
    PyNum threshold;
    if (!rates(long_context,&out->extended) ||
        !json_number(get(long_context,"threshold"),"price.threshold",&threshold) || threshold.is_float)
        return false;
    out->has_extended=true; out->threshold=threshold.i;
    return true;
}
bool price_priority_decode(yyjson_val *v, PricePriority *out) {
    *out=(PricePriority){0};
    if (yyjson_is_null(v)) return true;
    if (!yyjson_is_obj(v) || !rate(get(v,"multiplier"),&out->multiplier)) return false;
    yyjson_val *cap=get(v,"max_input_tokens");
    if (!cap) return false;
    if (!yyjson_is_null(cap)) {
        PyNum n;
        if (!json_number(cap,"price.priority.cap",&n) || n.is_float) return false;
        out->capped=true; out->cap=n.i;
    }
    out->present=true;
    return true;
}
bool price_entry_equal(const PriceEntry *a,const PriceEntry *b) {
    if(a->has_extended!=b->has_extended||(a->has_extended&&a->threshold!=b->threshold))return false;
    PyNum left[]={a->standard.input,a->standard.cached_input,a->standard.cache_write,a->standard.output,a->extended.input,a->extended.cached_input,a->extended.cache_write,a->extended.output};
    PyNum right[]={b->standard.input,b->standard.cached_input,b->standard.cache_write,b->standard.output,b->extended.input,b->extended.cached_input,b->extended.cache_write,b->extended.output};
    for(size_t i=0;i<(a->has_extended?8:4);i++)if(!pynum_equal(left[i],right[i]))return false;
    return true;
}
static double per_million(PyNum n, const char *site) {
    if (n.is_float) return n.f / 1000000.0;
    if (n.i >= -INT64_C(9007199254740992) && n.i <= INT64_C(9007199254740992)) return (double)n.i / 1000000.0;
    event_note("int_rate_large",site,1);
    char spelling[40];
    snprintf(spelling,sizeof spelling,"%llde-6",(long long)n.i);
    return strtod(spelling,NULL);
}
double cost_usd(const PriceEntry *entry, __int128 input, __int128 cached, __int128 output) {
    __int128 ti=input>0?input:0, c=cached>0?cached:0;
    if (c>ti) c=ti;
    const PriceRates *r=entry->has_extended && ti>entry->threshold?&entry->extended:&entry->standard;
    double ir=per_million(r->input,"price.cost.per_million.input");
    double cr=per_million(r->cached_input,"price.cost.per_million.cached_input");
    double wr=per_million(r->cache_write,"price.cost.per_million.cache_write");
    double or=per_million(r->output,"price.cost.per_million.output");
    return (((double)(ti-c)*ir+(double)c*cr)+0.0*wr)+(double)(output>0?output:0)*or;
}
bool priority_cost_usd(const PriceEntry *entry, const PricePriority *priority,
                       __int128 input, __int128 cached, __int128 output, double *out) {
    if (!priority->present || (priority->capped && input>priority->cap)) return false;
    double multiplier=priority->multiplier.is_float?priority->multiplier.f:(double)priority->multiplier.i;
    *out=cost_usd(entry,input,cached,output)*multiplier;
    return true;
}
