#include "rules.h"
#include "model.h"
#include "gen/assets.h"
#include "util/fileio.h"
#include "util/json_number.h"
#include <errno.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
static yyjson_val *get(yyjson_val *v,const char *s){return obj_get_last(v,(Str){s,(uint32_t)strlen(s)});}
static bool text_value(yyjson_val *v){return yyjson_is_str(v)&&yyjson_get_len(v)>0&&strlen(yyjson_get_str(v))==yyjson_get_len(v);}
static bool number(yyjson_val *v,bool integer,PyNum *n){return json_number(v,"pricing_rules.number",n)&&(!integer||!n->is_float)&&(n->is_float?isfinite(n->f):true);}
static bool map(yyjson_val *v,int kind){
    if(!yyjson_is_obj(v))return false;yyjson_obj_iter it=yyjson_obj_iter_with(v);yyjson_val *key;
    while((key=yyjson_obj_iter_next(&it))){yyjson_val *value=yyjson_obj_iter_get_val(key);PyNum n;
        if(!text_value(key))return false;
        if(kind==0){if(!text_value(value))return false;}
        else if(!number(value,kind==2,&n)||(kind==1&&(n.is_float?n.f<=0:n.i<=0)))return false;
    }return true;
}
static bool array(yyjson_val *v){if(!yyjson_is_arr(v))return false;size_t i,n;yyjson_val *item;yyjson_arr_foreach(v,i,n,item)if(!text_value(item))return false;return true;}
static bool validate(yyjson_doc *doc){
    yyjson_val *root=yyjson_doc_get_root(doc),*v;PyNum n;
    if(!yyjson_is_obj(root)||!number(get(root,"schema"),true,&n)||n.i!=1)return false;
    yyjson_obj_iter it=yyjson_obj_iter_with(root);yyjson_val *key;
    while((key=yyjson_obj_iter_next(&it))){if(!text_value(key))return false;const char *s=yyjson_get_str(key);v=yyjson_obj_iter_get_val(key);
        if(!strcmp(s,"schema"))continue;
        if(!strcmp(s,"aliases")){if(!yyjson_is_obj(v))return false;yyjson_obj_iter sub=yyjson_obj_iter_with(v);yyjson_val *k;while((k=yyjson_obj_iter_next(&sub))){if(!text_value(k))return false;const char *scope=yyjson_get_str(k);if(strcmp(scope,"codex")&&strcmp(scope,"claude")&&strcmp(scope,"antigravity"))return false;if(!map(yyjson_obj_iter_get_val(k),0))return false;}continue;}
        if(!strcmp(s,"antigravity_routing_suffixes")){if(!array(v))return false;continue;}
        if(!strcmp(s,"codex_cutoffs_ms")){if(!map(v,2))return false;continue;}
        if(!strcmp(s,"claude_provider_exact")||!strcmp(s,"claude_provider_families")||!strcmp(s,"claude_provider_prefixes")||!strcmp(s,"claude_catalog_aliases")){if(!map(v,0))return false;continue;}
        if(!strcmp(s,"codex_fast")||!strcmp(s,"claude_fast")){bool codex=!strcmp(s,"codex_fast");if(!yyjson_is_obj(v))return false;yyjson_obj_iter sub=yyjson_obj_iter_with(v);yyjson_val *k;while((k=yyjson_obj_iter_next(&sub))){if(!text_value(k))return false;const char *field=yyjson_get_str(k);yyjson_val *value=yyjson_obj_iter_get_val(k);
            if((codex&&!strcmp(field,"multipliers"))||(!codex&&(!strcmp(field,"exact")||!strcmp(field,"normalized_prefix")))){if(!map(value,1))return false;}
            else if(codex&&!strcmp(field,"uncapped")){if(!array(value))return false;}
            else if(codex&&!strcmp(field,"max_input_tokens")){if(!number(value,true,&n)||n.i<=0)return false;}
            else return false;}continue;}
        return false;
    }return true;
}
Err pricing_rules_load(const char *path,PricingRules *out){
    JsonRead base=json_read((Str){(const char *)cp_asset_pricing_rules,(uint32_t)cp_asset_pricing_rules_len},STR,JSON_CONSTANTS_REJECT,"pricing_rules.default");
    if(base.status!=JSON_OK||!validate(base.doc)){json_read_free(&base);return err_make(ERR_INVALID,"invalid embedded pricing rules");}out->defaults=base.doc;
    if(!path)return ERR_SUCCESS;
    char *bytes=NULL;size_t len=0;Err e=file_read_limited(path,1024*1024,&bytes,&len);
    if(e.code==ERR_NOMEM)return e;
    if(e.code){out->user_invalid=true;return ERR_SUCCESS;}
    JsonRead user=json_read((Str){bytes,(uint32_t)len},STR,JSON_CONSTANTS_REJECT,"pricing_rules.user");free(bytes);
    if(user.status==JSON_NOMEM)return err_make(ERR_NOMEM,"pricing rules allocation");
    if(user.status!=JSON_OK||!validate(user.doc)){json_read_free(&user);out->user_invalid=true;return ERR_SUCCESS;}
    out->user=user.doc;return ERR_SUCCESS;
}
void pricing_rules_destroy(PricingRules *r){yyjson_doc_free(r->defaults);yyjson_doc_free(r->user);*r=(PricingRules){0};}
yyjson_val *rules_section(const PricingRules *r,const char *section,bool user){if(!r)return NULL;yyjson_doc *d=user?r->user:r->defaults;return d?get(yyjson_doc_get_root(d),section):NULL;}
static yyjson_val *lookup(const PricingRules *r,const char *section,const char *field,Str key){for(int i=1;i>=0;i--){yyjson_val *v=rules_section(r,section,i);if(field)v=get(v,field);v=obj_get_last(v,key);if(v)return v;}return NULL;}
Str rules_alias(const PricingRules *r,const char *scope,Str name){yyjson_val *v=lookup(r,"aliases",scope,name);return yyjson_is_str(v)?(Str){yyjson_get_str(v),(uint32_t)yyjson_get_len(v)}:(Str){0};}
double rules_codex_fast(const PricingRules *r,Str name){yyjson_val *v=lookup(r,"codex_fast","multipliers",name);PyNum n;return v&&number(v,false,&n)?(n.is_float?n.f:(double)n.i):0;}
bool rules_codex_cutoff(const PricingRules *r,Str name,int64_t *ms){yyjson_val *v=lookup(r,"codex_cutoffs_ms",NULL,name);PyNum n;if(!v||!number(v,true,&n))return false;*ms=n.i;return true;}
int64_t rules_codex_cap(const PricingRules *r){for(int i=1;i>=0;i--){yyjson_val *v=get(rules_section(r,"codex_fast",i),"max_input_tokens");PyNum n;if(v&&number(v,true,&n))return n.i;}return 0;}
bool rules_codex_uncapped(const PricingRules *r,Str name){for(int i=1;i>=0;i--){yyjson_val *v=get(rules_section(r,"codex_fast",i),"uncapped");if(v){size_t j,n;yyjson_val *x;yyjson_arr_foreach(v,j,n,x){Str s={yyjson_get_str(x),(uint32_t)yyjson_get_len(x)};if(str_equal(s,name))return true;}return false;}}return false;}
Str rules_claude_catalog_alias(const PricingRules *r,Str name){yyjson_val *v=lookup(r,"claude_catalog_aliases",NULL,name);return yyjson_is_str(v)?(Str){yyjson_get_str(v),(uint32_t)yyjson_get_len(v)}:(Str){0};}
const char *rules_claude_provider(const PricingRules *r,Str lower){
    yyjson_val *v=lookup(r,"claude_provider_exact",NULL,lower);if(v)return yyjson_get_str(v);
    const char *sections[]={"claude_provider_families","claude_provider_prefixes"};
    for(size_t type=0;type<2;type++){
        yyjson_val *base=rules_section(r,sections[type],false),*user=rules_section(r,sections[type],true);
        for(int source=0;source<2;source++){yyjson_obj_iter it=yyjson_obj_iter_with(source?user:base);yyjson_val *key;
            while((key=yyjson_obj_iter_next(&it))){Str k={yyjson_get_str(key),(uint32_t)yyjson_get_len(key)};
                if(source&&obj_get_last(base,k))continue;
                if(type){if(price_literal_parts(lower,k,STR_LIT(""),false)!=0)continue;}
                else if(lower.n<k.n||memcmp(lower.p,k.p,k.n)||(lower.n!=k.n&&lower.p[k.n]!='-'))continue;
                v=obj_get_last(user,k);if(!v)v=yyjson_obj_iter_get_val(key);return yyjson_get_str(v);
            }
        }
    }return NULL;
}
