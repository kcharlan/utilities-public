#define _DARWIN_C_SOURCE
#include "ledger.h"
#include "parse/tokenstream.h"
#include "util/json_number.h"
#include "util/json_read.h"
#include "util/time.h"
#include "util/sort.h"
#include "util/fileio.h"
#include "util/atomic.h"
#include "testing/hooks.h"
#include "gen/assets.h"
#include <errno.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static yyjson_val *get(yyjson_val *v,const char *key){return obj_get_last(v,(Str){key,(uint32_t)strlen(key)});}
static Str string(yyjson_val *v){return yyjson_is_str(v)?(Str){yyjson_get_str(v),(uint32_t)yyjson_get_len(v)}:(Str){0};}
static Err message(LedgerCheck *check,PriceMessages *list,const char *format,...) {
    va_list args,copy;va_start(args,format);va_copy(copy,args);
    int length=vsnprintf(NULL,0,format,copy);va_end(copy);
    if(length<0){va_end(args);return err_make(ERR_INVALID,"price diagnostic formatting");}
    char *bytes;Err error=arena_alloc(&check->arena,(size_t)length+1,1,(void **)&bytes);
    if(error.code){va_end(args);return error;}
    vsnprintf(bytes,(size_t)length+1,format,args);va_end(args);
    if(list->count==list->capacity) {
        size_t next=list->capacity?list->capacity*2:8;
        if(next<list->capacity||next>SIZE_MAX/sizeof *list->items)return err_make(ERR_NOMEM,"price diagnostics overflow");
        Str *grown=realloc(list->items,next*sizeof *grown);if(!grown)return err_make(ERR_NOMEM,"price diagnostics allocation");
        list->items=grown;list->capacity=next;
    }
    list->items[list->count++]=(Str){bytes,(uint32_t)length};return ERR_SUCCESS;
}
typedef struct {yyjson_val *left,*right;bool root;} EqualPair;
bool ledger_json_equal(yyjson_val *left,yyjson_val *right,bool omit_notes) {
    size_t count=1,capacity=32;EqualPair *stack=malloc(capacity*sizeof *stack);if(!stack)return false;
    stack[0]=(EqualPair){left,right,true};bool equal=true;
    while(count&&equal) {
        EqualPair pair=stack[--count];yyjson_val *a=pair.left,*b=pair.right;
        if(!a||!b){equal=a==b;continue;}
        bool an=yyjson_is_raw(a)||yyjson_is_num(a),bn=yyjson_is_raw(b)||yyjson_is_num(b);
        if(an&&bn){PyNum x,y;equal=json_number(a,"price.equal",&x)&&json_number(b,"price.equal",&y)&&pynum_equal(x,y);continue;}
        if(yyjson_get_type(a)!=yyjson_get_type(b)){equal=false;break;}
        if(yyjson_is_str(a)){equal=str_equal(string(a),string(b));continue;}
        if(yyjson_is_bool(a)){equal=yyjson_get_bool(a)==yyjson_get_bool(b);continue;}
        if(yyjson_is_null(a))continue;
        size_t needed=yyjson_get_len(a);
        if(needed>SIZE_MAX-count||count+needed>SIZE_MAX/sizeof *stack){equal=false;break;}
        if(count+needed>capacity){capacity=count+needed;EqualPair *grown=realloc(stack,capacity*sizeof *stack);if(!grown){equal=false;break;}stack=grown;}
        if(yyjson_is_arr(a)) {
            if(yyjson_arr_size(a)!=yyjson_arr_size(b)){equal=false;break;}
            for(size_t i=0;i<needed;i++)stack[count++]=(EqualPair){yyjson_arr_get(a,i),yyjson_arr_get(b,i),false};
        } else {
            Omap am={0},bm={0};
            if(json_object_dict(a,&am).code||json_object_dict(b,&bm).code){equal=false;omap_destroy(&am);omap_destroy(&bm);break;}
            if(pair.root&&omit_notes){omap_delete(&am,STR_LIT("note"),NULL);omap_delete(&am,STR_LIT("recorded_at"),NULL);omap_delete(&bm,STR_LIT("note"),NULL);omap_delete(&bm,STR_LIT("recorded_at"),NULL);}
            if(am.size!=bm.size)equal=false;
            for(OmapEntry *entry=am.first;entry&&equal;entry=entry->next){yyjson_val *other=omap_get(&bm,entry->key);if(!other)equal=false;else stack[count++]=(EqualPair){entry->value,other,false};}
            omap_destroy(&am);omap_destroy(&bm);
        }
    }
    free(stack);return equal;
}
static bool instant(yyjson_val *v,int64_t *out) {
    Str s=string(v);if(s.n!=20)return false;
    for(size_t i=0;i<20;i++) {
        char expected=i==4||i==7?'-':i==10?'T':i==13||i==16?':':i==19?'Z':0;
        if(expected?s.p[i]!=expected:s.p[i]<'0'||s.p[i]>'9')return false;
    }
    return time_parse_rfc3339(s,"price.effective_from",out);
}
static bool model_valid(yyjson_val *v) {
    Str model=string(v);if(!model.n||!token_model_trim(model).n)return false;
    if(model.n>=8&&!memcmp(model.p,"catalog:",8)) {
        size_t bar=SIZE_MAX;for(size_t i=8;i<model.n;i++)if(model.p[i]=='|')bar=i;
        if(bar==SIZE_MAX||bar==8||bar==model.n-1)return false;
        Str matched={model.p+8,(uint32_t)bar-8},normalized={model.p+bar+1,model.n-(uint32_t)bar-1};
        return str_equal(token_model_trim(matched),matched)&&str_equal(normalize_codex_model(normalized),normalized);
    }
    return str_equal(normalize_codex_model(model),model);
}
typedef struct {PyNum number;bool valid;} LedgerNumber;
static bool ledger_number(LedgerCheck *check,yyjson_val *v,const char *site,PyNum *out) {
    if(check->numeric_error.code)return false;
    Str key={(const char *)&v,sizeof v};LedgerNumber *ticket=omap_get(&check->numeric_tickets,key);
    if(!ticket) {
        check->numeric_error=arena_alloc(&check->arena,sizeof *ticket,_Alignof(LedgerNumber),(void **)&ticket);
        if(check->numeric_error.code)return false;
        *ticket=(LedgerNumber){0};ticket->valid=json_number(v,site,&ticket->number);
        check->numeric_error=omap_put(&check->numeric_tickets,key,ticket);
        if(check->numeric_error.code)return false;
    }
    if(ticket->valid)*out=ticket->number;return ticket->valid;
}
static bool valid_number(LedgerCheck *check,yyjson_val *v,bool positive,const char *site) {
    PyNum number;if(!ledger_number(check,v,site,&number))return false;
    return number.is_float?isfinite(number.f)&&(positive?number.f>0:number.f>=0):(positive?number.i>0:number.i>=0);
}
typedef enum {LEDGER_ENTRY,LEDGER_RATES,LEDGER_LONG_RATES,LEDGER_PRIORITY,LEDGER_METADATA,LEDGER_IGNORED} LedgerShape;
static LedgerShape child_shape(LedgerShape parent,Str key,bool *known) {
    *known=false;if(parent==LEDGER_METADATA)return LEDGER_METADATA;
    const char *entry[]={"model","effective_from","source","per_million","long_context","priority","recorded_at","note","approximate_date"};
    const char *rates[]={"input","cached_input","cache_write","output","threshold"};
    const char *priority[]={"multiplier","max_input_tokens"};
    const char **fields=parent==LEDGER_ENTRY?entry:parent==LEDGER_PRIORITY?priority:rates;
    size_t length=parent==LEDGER_ENTRY?9:parent==LEDGER_PRIORITY?2:parent==LEDGER_LONG_RATES?5:parent==LEDGER_RATES?4:0;
    for(size_t i=0;i<length;i++)if(str_equal(key,(Str){fields[i],(uint32_t)strlen(fields[i])})) {
        *known=true;
        if(parent==LEDGER_ENTRY&&i==3)return LEDGER_RATES;
        if(parent==LEDGER_ENTRY&&i==4)return LEDGER_LONG_RATES;
        if(parent==LEDGER_ENTRY&&i==5)return LEDGER_PRIORITY;
        return LEDGER_IGNORED;
    }
    return parent==LEDGER_IGNORED?LEDGER_IGNORED:LEDGER_METADATA;
}
typedef struct {yyjson_val *value;Str path,site;LedgerShape shape;} NonfiniteNode;
static Err nonfinite(LedgerCheck *check,yyjson_val *root,Str initial,const char *prefix,Str site,LedgerShape shape) {
    size_t count=1,capacity=32;NonfiniteNode *stack=malloc(capacity*sizeof *stack);if(!stack)return err_make(ERR_NOMEM,"ledger walk allocation");
    stack[0]=(NonfiniteNode){root,initial,site,shape};Err error=ERR_SUCCESS;
    while(count&&!error.code) {
        NonfiniteNode node=stack[--count];yyjson_val *v=node.value;
        bool integer=yyjson_is_sint(v)||yyjson_is_uint(v)||(yyjson_is_raw(v)&&json_number_is_integer((Str){yyjson_get_raw(v),(uint32_t)yyjson_get_len(v)}));
        if(integer&&node.shape==LEDGER_METADATA) {
            PyNum number;
            if(!ledger_number(check,v,node.site.p,&number))error=check->numeric_error.code?check->numeric_error:
                message(check,&check->errors,"%s%.*s contains an integer outside int64",prefix,(int)node.path.n,node.path.p);
        } else if(!integer&&(yyjson_is_raw(v)||yyjson_is_real(v))) {
            PyNum number;
            if(json_number(v,"price.ledger.metadata",&number)&&number.is_float&&!isfinite(number.f))error=message(check,&check->errors,"%s%.*s contains a nonfinite JSON number",prefix,(int)node.path.n,node.path.p);
        }
        if(!yyjson_is_ctn(v))continue;
        size_t needed=yyjson_get_len(v),begin=count;
        if(needed>SIZE_MAX-count||count+needed>SIZE_MAX/sizeof *stack){error=err_make(ERR_NOMEM,"ledger walk overflow");break;}
        if(count+needed>capacity){capacity=count+needed;NonfiniteNode *grown=realloc(stack,capacity*sizeof *stack);if(!grown){error=err_make(ERR_NOMEM,"ledger walk allocation");break;}stack=grown;}
        yyjson_obj_iter it=yyjson_obj_iter_with(v);yyjson_val *key=NULL;
        for(size_t i=0;i<needed;i++) {
            JsonWriter path={0},trusted={0};jsonw_bytes(&path,node.path.p,node.path.n);jsonw_bytes(&trusted,node.site.p,node.site.n);yyjson_val *child;LedgerShape child_context=node.shape;
            if(yyjson_is_obj(v)) {
                key=yyjson_obj_iter_next(&it);if(node.path.n)jsonw_raw(&path,".");Str s=string(key);jsonw_bytes(&path,s.p,s.n);child=yyjson_obj_iter_get_val(key);
                bool known;child_context=child_shape(node.shape,s,&known);
                if(known){jsonw_raw(&trusted,".");jsonw_bytes(&trusted,s.p,s.n);}
                else {char position[48];snprintf(position,sizeof position,"{value[%zu]}",i);jsonw_raw(&trusted,position);}
            } else {char number[40];snprintf(number,sizeof number,"[%zu]",i);jsonw_raw(&path,number);jsonw_raw(&trusted,number);child=yyjson_arr_get(v,i);}
            Str copied,trusted_copy;error=path.error.code?path.error:trusted.error;
            if(!error.code)error=str_copy(&check->arena,(Str){path.data,(uint32_t)path.length},&copied);
            if(!error.code)error=str_copy(&check->arena,(Str){trusted.data,(uint32_t)trusted.length},&trusted_copy);
            jsonw_free(&path);jsonw_free(&trusted);
            if(error.code)break;stack[count++]=(NonfiniteNode){child,copied,trusted_copy,child_context};
        }
        for(size_t a=begin,b=count;a<b&&a<--b;a++){NonfiniteNode swap=stack[a];stack[a]=stack[b];stack[b]=swap;}
    }
    free(stack);return error;
}
Err validate_ledger(yyjson_val *document,bool curated,LedgerCheck *out) {
    PyNum schema;
    if(!yyjson_is_obj(document)||!ledger_number(out,get(document,"schema"),"price-history.json:schema",&schema)||schema.is_float||schema.i!=1)
        return out->numeric_error.code?out->numeric_error:message(out,&out->errors,"ledger schema must be 1 in a JSON object");
    yyjson_val *entries=get(document,"entries");
    if(!yyjson_is_arr(entries))return message(out,&out->errors,"ledger entries must be a list");
    Err error=ERR_SUCCESS;yyjson_obj_iter it=yyjson_obj_iter_with(document);yyjson_val *key;
    size_t position=0;
    while((key=yyjson_obj_iter_next(&it))) {
        size_t current=position++;if(str_equal(string(key),STR_LIT("entries")))continue;
        char site[80];bool schema_field=str_equal(string(key),STR_LIT("schema"));
        snprintf(site,sizeof site,schema_field?"price-history.json:schema":"price-history.json:{value[%zu]}",current);
        error=nonfinite(out,yyjson_obj_iter_get_val(key),string(key),"ledger: ",(Str){site,(uint32_t)strlen(site)},schema_field?LEDGER_IGNORED:LEDGER_METADATA);if(error.code)return error;
    }
#define ERROR(...) do {error=message(out,&out->errors,__VA_ARGS__);if(error.code)goto done;}while(0)
    size_t length=yyjson_arr_size(entries);
    if(length>SIZE_MAX/sizeof *out->entries)return err_make(ERR_NOMEM,"ledger entries overflow");
    out->entries=calloc(length?length:1,sizeof *out->entries);if(!out->entries)return err_make(ERR_NOMEM,"ledger entries allocation");out->capacity=length;
    for(size_t number=0;number<length;number++) {
        yyjson_val *entry=yyjson_arr_get(entries,number);size_t start_errors=out->errors.count;
        if(!yyjson_is_obj(entry)){ERROR("entry %zu: must be an object",number);continue;}
        char prefix[48];snprintf(prefix,sizeof prefix,"entry %zu: ",number);
        char entry_site[80];snprintf(entry_site,sizeof entry_site,"price-history.json:entries[%zu]",number);
        error=nonfinite(out,entry,STR_LIT(""),prefix,(Str){entry_site,(uint32_t)strlen(entry_site)},LEDGER_ENTRY);if(error.code)goto done;
        if(!model_valid(get(entry,"model")))ERROR("entry %zu: model must be a nonempty normalized id or catalog override key",number);
        yyjson_val *effective=get(entry,"effective_from");int64_t clock;
        if(!effective||!((curated&&yyjson_is_null(effective))||instant(effective,&clock)))ERROR("entry %zu: effective_from must be a whole-second RFC 3339 UTC instant%s",number,curated?" or null":"; null is curated-only");
        Str source=string(get(entry,"source"));
        if(curated?!str_equal(source,STR_LIT("curated")):!str_equal(source,STR_LIT("catalog"))&&!str_equal(source,STR_LIT("manual")))ERROR("entry %zu: source must be %s",number,curated?"curated":"catalog or manual");
        const char *blocks[]={"per_million","long_context"},*fields[]={"input","cached_input","cache_write","output"};
        for(size_t b=0;b<2;b++) {
            yyjson_val *rates=get(entry,blocks[b]);if(b&&!rates)continue;
            if(!yyjson_is_obj(rates)){ERROR("entry %zu: %s must be an object",number,blocks[b]);continue;}
            for(size_t i=0;i<4;i++){char site[160];snprintf(site,sizeof site,"%s.%s.%s",entry_site,blocks[b],fields[i]);if(!valid_number(out,get(rates,fields[i]),false,site))ERROR("entry %zu: %s.%s must be a finite number >= 0",number,blocks[b],fields[i]);}
            char site[160];snprintf(site,sizeof site,"%s.long_context.threshold",entry_site);
            PyNum threshold;if(b&&(!ledger_number(out,get(rates,"threshold"),site,&threshold)||threshold.is_float||threshold.i<=0))ERROR("entry %zu: long_context.threshold must be a positive integer",number);
        }
        yyjson_val *priority=get(entry,"priority");
        if(priority) {
            if(!yyjson_is_obj(priority))ERROR("entry %zu: priority must be an object",number);
            else {
                char site[160];snprintf(site,sizeof site,"%s.priority.multiplier",entry_site);
                if(!valid_number(out,get(priority,"multiplier"),true,site))ERROR("entry %zu: priority.multiplier must be a finite number > 0",number);
                yyjson_val *cap=get(priority,"max_input_tokens");PyNum n;
                snprintf(site,sizeof site,"%s.priority.max_input_tokens",entry_site);
                if(!cap||(!yyjson_is_null(cap)&&(!ledger_number(out,cap,site,&n)||n.is_float||n.i<=0)))ERROR("entry %zu: priority.max_input_tokens must be a positive integer or null",number);
            }
        }
        yyjson_val *recorded=get(entry,"recorded_at");
        if(str_equal(source,STR_LIT("catalog"))&&!recorded)ERROR("entry %zu: recorded_at is required for catalog entries",number);
        if(recorded&&!time_parse_rfc3339(string(recorded),"price.ledger.recorded_at",&clock))ERROR("entry %zu: recorded_at must be an RFC 3339 instant",number);
        yyjson_val *note=get(entry,"note"),*approximate=get(entry,"approximate_date");
        if(note&&!yyjson_is_str(note))ERROR("entry %zu: note must be a string",number);
        if(approximate&&!yyjson_is_bool(approximate))ERROR("entry %zu: approximate_date must be a boolean",number);
        if(out->errors.count!=start_errors)continue;
        bool duplicate=false;
        for(size_t i=0;i<out->count;i++) {
            yyjson_val *earlier=out->entries[i];
            if(str_equal(string(get(earlier,"model")),string(get(entry,"model")))&&ledger_json_equal(get(earlier,"effective_from"),effective,false)&&str_equal(string(get(earlier,"source")),source)) {
                size_t earlier_number=0;while(earlier_number<length&&yyjson_arr_get(entries,earlier_number)!=earlier)earlier_number++;
                if(ledger_json_equal(entry,earlier,true))error=message(out,&out->warnings,"entry %zu: duplicate of entry %zu; collapsed",number,earlier_number);
                else ERROR("entry %zu: conflicts with entry %zu",number,earlier_number);
                if(error.code)goto done;duplicate=true;break;
            }
        }
        if(!duplicate)out->entries[out->count++]=entry;
    }
done:
    if(out->errors.count)out->count=0;return error.code?error:out->numeric_error;
#undef ERROR
}
void ledger_check_destroy(LedgerCheck *check) {free(check->entries);free(check->errors.items);free(check->warnings.items);omap_destroy(&check->numeric_tickets);arena_destroy(&check->arena);*check=(LedgerCheck){0};}
static void messages_json(JsonWriter *w,const PriceMessages *messages) {jsonw_raw(w,"[");for(size_t i=0;i<messages->count;i++){if(i)jsonw_raw(w,",");jsonw_string(w,messages->items[i]);}jsonw_raw(w,"]");}
void ledger_check_json(JsonWriter *w,const LedgerCheck *check) {
    jsonw_raw(w,"{\"entries\":[");for(size_t i=0;i<check->count;i++){if(i)jsonw_raw(w,",");jsonw_value(w,check->entries[i]);}
    jsonw_raw(w,"],\"errors\":");messages_json(w,&check->errors);jsonw_raw(w,",\"warnings\":");messages_json(w,&check->warnings);jsonw_raw(w,"}");
}
static Err history_copy(yyjson_val *values,yyjson_doc **out) {
    if(!yyjson_is_arr(values))return err_make(ERR_INVALID,"history entries must be an array");
    yyjson_mut_doc *doc=yyjson_mut_doc_new(NULL);if(!doc)return err_make(ERR_NOMEM,"history allocation");
    yyjson_mut_doc_set_root(doc,yyjson_val_mut_copy(doc,values));
    Err error=doc->root?json_freeze(doc,out):err_make(ERR_NOMEM,"history allocation");
    yyjson_mut_doc_free(doc);return error;
}
static int entry_compare(const void *a,const void *b,void *unused) {
    (void)unused;const HistoryEntry *x=*(HistoryEntry *const *)a,*y=*(HistoryEntry *const *)b;
    if(x->null_time!=y->null_time)return x->null_time?-1:1;
    if(!x->null_time&&x->effective_ms!=y->effective_ms)return x->effective_ms<y->effective_ms?-1:1;
    return (x->rank>y->rank)-(x->rank<y->rank);
}
Err price_history(yyjson_val *curated,yyjson_val *user,PriceHistory *out) {
    Err error=history_copy(curated,&out->curated);if(error.code)return error;
    error=history_copy(user,&out->user);if(error.code)return error;
    yyjson_val *sources[]={yyjson_doc_get_root(out->curated),yyjson_doc_get_root(out->user)};
    for(size_t source=0;source<2;source++)for(size_t i=0;i<yyjson_arr_size(sources[source]);i++) {
        yyjson_val *value=yyjson_arr_get(sources[source],i);Str key=string(get(value,"model"));
        yyjson_val *effective=get(value,"effective_from");Str origin=string(get(value,"source"));
        if(!key.p||!effective||!origin.p)return err_make(ERR_INVALID,"invalid history entry");
        HistoryEntry *entry;error=arena_alloc(&out->arena,sizeof *entry,_Alignof(HistoryEntry),(void **)&entry);if(error.code)return error;
        *entry=(HistoryEntry){.value=value,.null_time=yyjson_is_null(effective)};
        if(!entry->null_time&&!instant(effective,&entry->effective_ms))return err_make(ERR_INVALID,"invalid history effective time");
        if(str_equal(origin,STR_LIT("curated")))entry->rank=0;
        else if(str_equal(origin,STR_LIT("catalog")))entry->rank=1;
        else if(str_equal(origin,STR_LIT("manual")))entry->rank=2;
        else return err_make(ERR_INVALID,"invalid history source");
        if(!price_entry_decode(value,&entry->rates))return err_make(ERR_INVALID,"invalid history rates");
        yyjson_val *priority=get(value,"priority");entry->has_priority=priority!=NULL;
        if(priority&&!price_priority_decode(priority,&entry->priority))return err_make(ERR_INVALID,"invalid history priority");
        HistoryGroup *group=omap_get(&out->groups,key);
        if(!group) {
            error=arena_alloc(&out->arena,sizeof *group,_Alignof(HistoryGroup),(void **)&group);if(error.code)return error;
            *group=(HistoryGroup){0};error=str_copy(&out->arena,key,&group->key);if(error.code)return error;
            error=omap_put(&out->groups,key,group);if(error.code)return error;
        }
        if(group->count==group->capacity) {
            size_t next=group->capacity?group->capacity*2:8;
            if(next<group->capacity||next>SIZE_MAX/sizeof *group->entries)return err_make(ERR_NOMEM,"history overflow");
            HistoryEntry **grown=realloc(group->entries,next*sizeof *grown);if(!grown)return err_make(ERR_NOMEM,"history allocation");
            group->entries=grown;group->capacity=next;
        }
        group->entries[group->count++]=entry;
    }
    for(OmapEntry *entry=out->groups.first;entry;entry=entry->next) {
        HistoryGroup *group=entry->value;error=stable_sort(group->entries,group->count,sizeof *group->entries,entry_compare,NULL);if(error.code)return error;
    }
    return ERR_SUCCESS;
}
const HistoryGroup *history_entries_for(const PriceHistory *history,Str model) {return omap_get(&history->groups,model);}
bool history_has_any(const PriceHistory *history,Str model) {const HistoryGroup *group=history_entries_for(history,model);return group&&group->count;}
HistoryPick history_pick(const PriceHistory *history,Str model,int64_t at_ms) {
    const HistoryGroup *group=history_entries_for(history,model);HistoryPick result={0};
    if(!group||!group->count)return result;
    size_t position=0;
    while(position<group->count&&(group->entries[position]->null_time||group->entries[position]->effective_ms<=at_ms))position++;
    if(position)position--;
    else {
        result.before_first=true;
        while(position+1<group->count&&group->entries[position+1]->null_time==group->entries[0]->null_time&&group->entries[position+1]->effective_ms==group->entries[0]->effective_ms)position++;
    }
    result.entry=group->entries[position];result.index=position;return result;
}
void history_destroy(PriceHistory *history) {
    for(OmapEntry *entry=history->groups.first;entry;entry=entry->next){HistoryGroup *group=entry->value;free(group->entries);}
    omap_destroy(&history->groups);arena_destroy(&history->arena);yyjson_doc_free(history->curated);yyjson_doc_free(history->user);*history=(PriceHistory){0};
}
void history_entries_json(JsonWriter *w,const HistoryGroup *group) {jsonw_raw(w,"[");if(group)for(size_t i=0;i<group->count;i++){if(i)jsonw_raw(w,",");jsonw_value(w,group->entries[i]->value);}jsonw_raw(w,"]");}
void history_pick_json(JsonWriter *w,HistoryPick pick) {
    if(!pick.entry){jsonw_raw(w,"null");return;}
    jsonw_raw(w,"{\"entry\":");jsonw_value(w,pick.entry->value);jsonw_raw(w,",\"period_index\":");jsonw_i64(w,(int64_t)pick.index);
    jsonw_raw(w,pick.before_first?",\"before_first\":true}":",\"before_first\":false}");
}
static int source_compare(const void *a,const void *b,void *unused) {(void)unused;return str_compare((*(OmapEntry *const *)a)->key,(*(OmapEntry *const *)b)->key);}
static yyjson_mut_val *rate_block(yyjson_mut_doc *doc,const PriceRates *rates,bool extended,int64_t threshold) {
    yyjson_mut_val *value=yyjson_mut_obj(doc);if(!value)return NULL;
    if(extended&&!yyjson_mut_obj_add_int(doc,value,"threshold",threshold))return NULL;
    const char *keys[]={"input","output","cached_input","cache_write"};PyNum numbers[]={rates->input,rates->output,rates->cached_input,rates->cache_write};
    for(size_t i=0;i<4;i++) {
        yyjson_mut_val *key=yyjson_mut_strcpy(doc,keys[i]);
        yyjson_mut_val *number=numbers[i].is_float?yyjson_mut_real(doc,numbers[i].f):yyjson_mut_sint(doc,numbers[i].i);
        if(!key||!number||!yyjson_mut_obj_add(value,key,number))return NULL;
    }
    return value;
}
Err record_catalog_rates(const PriceHistory *history,ModelsDevIndex *index,int64_t fetched_at_ms,
                         yyjson_val *recording_ids,int64_t now_ms,yyjson_doc **out) {
    *out=NULL;Omap sources={0};Arena arena={0};OmapEntry **sorted=NULL;
    yyjson_mut_doc *doc=yyjson_mut_doc_new(NULL);Err error=ERR_SUCCESS;
    if(!doc)return err_make(ERR_NOMEM,"catalog recording allocation");
    yyjson_mut_val *rows=yyjson_mut_arr(doc);yyjson_mut_doc_set_root(doc,rows);
    if(!rows){error=err_make(ERR_NOMEM,"catalog recording allocation");goto done;}
    for(OmapEntry *entry=index->models.first;entry;entry=entry->next) {
        CatalogModel *model=entry->value;Str normalized,*copy;
        error=models_dev_normalize(index,model->model_id,&normalized);if(error.code)goto done;
        error=arena_alloc(&arena,sizeof *copy,_Alignof(Str),(void **)&copy);if(error.code)goto done;
        *copy=normalized;error=omap_put(&sources,normalized,copy);if(error.code)goto done;
    }
    for(OmapEntry *entry=history->groups.first;entry;entry=entry->next) {
        Str *copy;error=arena_alloc(&arena,sizeof *copy,_Alignof(Str),(void **)&copy);if(error.code)goto done;
        *copy=entry->key;error=omap_put(&sources,entry->key,copy);if(error.code)goto done;
    }
    if(!yyjson_is_obj(recording_ids)){error=err_make(ERR_INVALID,"invalid recording ids");goto done;}
    yyjson_obj_iter it=yyjson_obj_iter_with(recording_ids);yyjson_val *key;
    while((key=yyjson_obj_iter_next(&it))) {
        Str *copy;if(!yyjson_is_str(yyjson_obj_iter_get_val(key))){error=err_make(ERR_INVALID,"invalid recording id");goto done;}
        error=arena_alloc(&arena,sizeof *copy,_Alignof(Str),(void **)&copy);if(error.code)goto done;
        *copy=string(yyjson_obj_iter_get_val(key));error=omap_put(&sources,string(key),copy);if(error.code)goto done;
    }
    if(sources.size>SIZE_MAX/sizeof *sorted){error=err_make(ERR_NOMEM,"catalog recording overflow");goto done;}
    sorted=malloc((sources.size?sources.size:1)*sizeof *sorted);if(!sorted){error=err_make(ERR_NOMEM,"catalog recording allocation");goto done;}
    size_t count=0;for(OmapEntry *entry=sources.first;entry;entry=entry->next)sorted[count++]=entry;
    error=stable_sort(sorted,count,sizeof *sorted,source_compare,NULL);if(error.code)goto done;
    int64_t seconds;floordiv_i64(fetched_at_ms,1000,&seconds);
    int64_t effective_ms;if(__builtin_mul_overflow(seconds,INT64_C(1000),&effective_ms)){error=err_make(ERR_INVALID,"invalid catalog recording clock");goto done;}
    char effective[21],recorded[21];
    if(!time_format_rfc3339(effective_ms,effective)||!time_format_rfc3339(now_ms,recorded)){error=err_make(ERR_INVALID,"invalid catalog recording clock");goto done;}
    for(size_t i=0;i<count;i++) {
        Str model=*(Str *)sorted[i]->value;PricingTargets targets;
        error=codex_models_dev_pricing_targets(&arena,model,&targets);if(error.code)goto done;
        CatalogLookup lookup={0};
        for(size_t j=0;j<targets.count;j++){error=models_dev_pricing(index,STR_LIT("openai"),targets.model[j],&lookup);if(error.code)goto done;if(lookup.model)break;}
        if(!lookup.model)continue;
        const HistoryGroup *group=history_entries_for(history,sorted[i]->key);
        bool same_date=false;
        if(group)for(size_t j=0;j<group->count;j++)if(!group->entries[j]->null_time&&group->entries[j]->effective_ms==effective_ms)same_date=true;
        if(same_date)continue;
        PriceEntry rates;bool found;error=resolve_rates(model,index,&rates,&found);if(error.code)goto done;if(!found)continue;
        const HistoryEntry *previous=NULL;
        if(group)for(size_t j=group->count;j>0;j--) {
            const HistoryEntry *candidate=group->entries[j-1];
            if(candidate->rank!=2&&(candidate->null_time||candidate->effective_ms<=effective_ms)){previous=candidate;break;}
        }
        if(previous&&price_entry_equal(&previous->rates,&rates))continue;
        yyjson_mut_val *row=yyjson_mut_obj(doc),*standard=rate_block(doc,&rates.standard,false,0);
        if(!row||!standard||!yyjson_mut_obj_add_strn(doc,row,"model",sorted[i]->key.p,sorted[i]->key.n)||
           !yyjson_mut_obj_add_strcpy(doc,row,"effective_from",effective)||!yyjson_mut_obj_add_val(doc,row,"per_million",standard)||
           !yyjson_mut_obj_add_str(doc,row,"source","catalog")||!yyjson_mut_obj_add_strcpy(doc,row,"recorded_at",recorded)||
           !yyjson_mut_obj_add_bool(doc,row,"approximate_date",true)){error=err_make(ERR_NOMEM,"catalog recording allocation");goto done;}
        if(rates.has_extended) {
            yyjson_mut_val *extended=rate_block(doc,&rates.extended,true,rates.threshold);
            if(!extended||!yyjson_mut_obj_add_val(doc,row,"long_context",extended)){error=err_make(ERR_NOMEM,"catalog recording allocation");goto done;}
        }
        HistoryPick picked=history_pick(history,sorted[i]->key,effective_ms);
        if(picked.entry&&picked.entry->has_priority) {
            yyjson_mut_val *priority=yyjson_val_mut_copy(doc,get(picked.entry->value,"priority"));
            if(!priority||!yyjson_mut_obj_add_val(doc,row,"priority",priority)){error=err_make(ERR_NOMEM,"catalog recording allocation");goto done;}
        }
        if(!yyjson_mut_arr_append(rows,row)){error=err_make(ERR_NOMEM,"catalog recording allocation");goto done;}
    }
    error=json_freeze(doc,out);
done:
    yyjson_mut_doc_free(doc);omap_destroy(&sources);arena_destroy(&arena);free(sorted);return error;
}
static Err append_warning(LedgerAppend *out,Str warning) {return str_copy(&out->arena,warning,&out->warning);}
static bool stat_clock(const struct stat *stat,int64_t *out) {
    return !__builtin_mul_overflow((int64_t)stat->st_mtimespec.tv_sec,INT64_C(1000000000),out)&&
        !__builtin_add_overflow(*out,(int64_t)stat->st_mtimespec.tv_nsec,out);
}
static Err current_clock(const char *path,bool *present,int64_t *clock,struct stat *value) {
    if(stat(path,value)) {
        if(errno==ENOENT){*present=false;return ERR_SUCCESS;}
        return err_make(ERR_IO,"stat failed: %s",strerror(errno));
    }
    *present=true;if(!stat_clock(value,clock))return err_make(ERR_INVALID,"ledger mtime out of range");return ERR_SUCCESS;
}
static void pretty_ledger(JsonWriter *out,const JsonWriter *compact) {
    bool quoted=false,escape=false;size_t depth=0;
    for(size_t i=0;i<compact->length;i++) {
        char c=compact->data[i];
        if(quoted){jsonw_bytes(out,&c,1);if(escape)escape=false;else if(c=='\\')escape=true;else if(c=='"')quoted=false;continue;}
        if(c=='"'){quoted=true;jsonw_bytes(out,&c,1);continue;}
        if(c=='{'||c=='[') {
            jsonw_bytes(out,&c,1);depth++;
            if(i+1<compact->length&&compact->data[i+1]!='}'&&compact->data[i+1]!=']') {
                jsonw_raw(out,"\n");for(size_t j=0;j<depth;j++)jsonw_raw(out,"  ");
            }
        } else if(c=='}'||c==']') {
            if(depth)depth--;
            if(i&&compact->data[i-1]!='{'&&compact->data[i-1]!='['){jsonw_raw(out,"\n");for(size_t j=0;j<depth;j++)jsonw_raw(out,"  ");}
            jsonw_bytes(out,&c,1);
        } else if(c==','){jsonw_raw(out,",\n");for(size_t j=0;j<depth;j++)jsonw_raw(out,"  ");}
        else if(c==':')jsonw_raw(out,": ");else jsonw_bytes(out,&c,1);
    }
    jsonw_raw(out,"\n");
}
Err append_user_ledger(const char *path,yyjson_val *new_entries,bool start_present,int64_t start_mtime_ns,LedgerAppend *out) {
    if(!yyjson_is_arr(new_entries))return err_make(ERR_INVALID,"invalid new ledger entries");
    if(!yyjson_arr_size(new_entries))return ERR_SUCCESS;
    static const Str changed=STR_LIT("price-history.json changed during the run; recording skipped");
    struct stat captured;bool present=false;int64_t clock=0;
    char *bytes=NULL;size_t length=0;JsonRead parsed={0};yyjson_mut_doc *dict=NULL;yyjson_doc *document=NULL,*combined=NULL;
    LedgerCheck checked={0};JsonWriter compact={0},pretty={0};Err error=current_clock(path,&present,&clock,&captured);
    if(error.code)goto io_error;
    if(present!=start_present||(present&&clock!=start_mtime_ns)){error=append_warning(out,changed);goto done;}
    if(present) {
        error=file_read_all(path,&bytes,&length);if(error.code)goto io_error;
        if(cp_fault("append_ledger_reread_edit")) {
            int fd=open(path,O_WRONLY);if(fd<0){error=err_make(ERR_IO,"ledger checkpoint open failed: %s",strerror(errno));goto io_error;}
            struct timespec times[]={captured.st_atimespec,captured.st_mtimespec};
            times[1].tv_nsec+=1000000;if(times[1].tv_nsec>=1000000000){times[1].tv_nsec-=1000000000;times[1].tv_sec++;}
            int result=futimens(fd,times),saved=errno;close(fd);
            if(result){error=err_make(ERR_IO,"ledger checkpoint mtime failed: %s",strerror(saved));goto io_error;}
        }
    }
    error=current_clock(path,&present,&clock,&captured);if(error.code)goto io_error;
    if(present!=start_present||(present&&clock!=start_mtime_ns)){error=append_warning(out,changed);goto done;}
    if(bytes) {
        if(length>UINT32_MAX){error=err_make(ERR_INVALID,"ledger too large");goto io_error;}
        parsed=json_read((Str){bytes,(uint32_t)length},STRICT,JSON_CONSTANTS_REJECT,"price-history.json:reread");
        if(parsed.status!=JSON_OK) {
            if(parsed.stats.first_constant) {
                const char *constants[]={"","NaN","Infinity","-Infinity"};
                jsonw_raw(&pretty,"price-history.json: recording skipped: Non-JSON constant: ");jsonw_raw(&pretty,constants[parsed.stats.first_constant]);
                error=pretty.error;if(!error.code)error=append_warning(out,(Str){pretty.data,(uint32_t)pretty.length});goto done;
            }
            const char *diagnostic=parsed.status==JSON_T2_ENCODING?"price-history.json: recording skipped: invalid UTF-8":
                "price-history.json: recording skipped: invalid JSON";
            error=append_warning(out,(Str){diagnostic,(uint32_t)strlen(diagnostic)});goto done;
        }
        error=json_load_dict_semantics(parsed.doc,&dict);if(error.code)goto done;
    } else {
        dict=yyjson_mut_doc_new(NULL);if(!dict){error=err_make(ERR_NOMEM,"ledger allocation");goto done;}
        yyjson_mut_val *root=yyjson_mut_obj(dict),*entries=yyjson_mut_arr(dict);
        if(!root||!entries||!yyjson_mut_obj_add_int(dict,root,"schema",1)||!yyjson_mut_obj_add_val(dict,root,"entries",entries)){error=err_make(ERR_NOMEM,"ledger allocation");goto done;}
        yyjson_mut_doc_set_root(dict,root);
    }
    error=json_freeze(dict,&document);if(error.code)goto done;
    error=validate_ledger(yyjson_doc_get_root(document),false,&checked);if(error.code)goto done;
    if(checked.errors.count)goto validation_error;
    ledger_check_destroy(&checked);
    yyjson_mut_val *entries=yyjson_mut_obj_get(dict->root,"entries");
    for(size_t i=0;i<yyjson_arr_size(new_entries);i++) {
        yyjson_mut_val *copy=yyjson_val_mut_copy(dict,yyjson_arr_get(new_entries,i));
        if(!copy||!yyjson_mut_arr_append(entries,copy)){error=err_make(ERR_NOMEM,"ledger append allocation");goto done;}
    }
    error=json_freeze(dict,&combined);if(error.code)goto done;
    error=validate_ledger(yyjson_doc_get_root(combined),false,&checked);if(error.code)goto done;
    if(checked.errors.count)goto validation_error;
    jsonw_value(&compact,yyjson_doc_get_root(combined));if(compact.error.code){error=compact.error;goto done;}
    pretty_ledger(&pretty,&compact);if(pretty.error.code){error=pretty.error;goto done;}
    if(cp_fault("append_ledger")){error=err_make(ERR_IO,"synthetic append failure");goto io_error;}
    error=atomic_write(path,pretty.data,pretty.length);if(error.code)goto io_error;
    out->appended=true;goto done;
validation_error:
    jsonw_raw(&pretty,"price-history.json: ");
    for(size_t i=0;i<checked.errors.count;i++){if(i)jsonw_raw(&pretty,"; ");jsonw_bytes(&pretty,checked.errors.items[i].p,checked.errors.items[i].n);}
    error=pretty.error;if(!error.code)error=append_warning(out,(Str){pretty.data,(uint32_t)pretty.length});goto done;
io_error:
    jsonw_free(&pretty);pretty=(JsonWriter){0};
    jsonw_raw(&pretty,"price-history.json: recording skipped: ");jsonw_raw(&pretty,error.message);
    error=pretty.error;if(!error.code)error=append_warning(out,(Str){pretty.data,(uint32_t)pretty.length});
done:
    ledger_check_destroy(&checked);yyjson_mut_doc_free(dict);yyjson_doc_free(document);yyjson_doc_free(combined);json_read_free(&parsed);free(bytes);jsonw_free(&compact);jsonw_free(&pretty);return error;
}
void ledger_append_destroy(LedgerAppend *append) {arena_destroy(&append->arena);*append=(LedgerAppend){0};}
static Err runtime_diagnostic(RuntimeLedger *ledger,const char *path,Str level,Str text) {
    LedgerDiagnostic *diagnostic;Err e=arena_alloc(&ledger->arena,sizeof *diagnostic,_Alignof(LedgerDiagnostic),(void **)&diagnostic);if(e.code)return e;
    *diagnostic=(LedgerDiagnostic){.level=level};JsonWriter bytes={0};jsonw_raw(&bytes,path);jsonw_raw(&bytes,": ");jsonw_bytes(&bytes,text.p,text.n);
    e=bytes.error;if(!e.code)e=str_copy(&ledger->arena,(Str){bytes.data,(uint32_t)bytes.length},&diagnostic->message);jsonw_free(&bytes);if(e.code)return e;
    if(ledger->last)ledger->last->next=diagnostic;else ledger->diagnostics=diagnostic;ledger->last=diagnostic;return ERR_SUCCESS;
}
Err runtime_ledger_warning(RuntimeLedger *ledger,const char *path,Str warning) {return runtime_diagnostic(ledger,path,STR_LIT("warning"),warning);}
Err runtime_ledger_load(const char *path,RuntimeLedger *out) {
    char *bytes=NULL;size_t length=0;JsonRead parsed={0},curated={0};yyjson_mut_doc *dictionary=NULL,*entries=NULL;Err error=ERR_SUCCESS;
    curated=json_read((Str){(const char *)cp_asset_curated_price_history,(uint32_t)cp_asset_curated_price_history_len},STR,JSON_CONSTANTS_REJECT,"price.curated");
    if(curated.status!=JSON_OK){error=err_make(ERR_INVALID,"invalid embedded curated ledger");goto done;}
    out->curated=curated.doc;curated.doc=NULL;
    error=file_read_all(path,&bytes,&length);
    if(error.code) {
        if(error.code==ERR_NOMEM)goto done;
        error=message(&out->check,&out->check.errors,"%s",error.message);if(error.code)goto done;
    } else {
        if(length>UINT32_MAX){error=message(&out->check,&out->check.errors,"invalid JSON: ledger too large");if(error.code)goto done;}
        else {
            parsed=json_read((Str){bytes,(uint32_t)length},BYTES,JSON_CONSTANTS_REJECT,"price-history.json");
            if(parsed.status==JSON_NOMEM){error=err_make(ERR_NOMEM,"ledger read allocation");goto done;}
            if(parsed.status!=JSON_OK) {
                if(parsed.stats.first_constant) {
                    const char *constants[]={"","NaN","Infinity","-Infinity"};error=message(&out->check,&out->check.errors,"Non-JSON constant: %s",constants[parsed.stats.first_constant]);
                } else error=message(&out->check,&out->check.errors,"%s",parsed.status==JSON_T2_ENCODING?"invalid UTF-8":"invalid JSON");
                if(error.code)goto done;
            } else {
                error=json_load_dict_semantics(parsed.doc,&dictionary);if(error.code)goto done;
                error=json_freeze(dictionary,&out->document);if(error.code)goto done;
                error=validate_ledger(yyjson_doc_get_root(out->document),false,&out->check);if(error.code)goto done;
            }
        }
    }
    entries=yyjson_mut_doc_new(NULL);if(!entries){error=err_make(ERR_NOMEM,"ledger entries allocation");goto done;}
    yyjson_mut_val *rows=yyjson_mut_arr(entries);yyjson_mut_doc_set_root(entries,rows);
    if(!rows){error=err_make(ERR_NOMEM,"ledger entries allocation");goto done;}
    for(size_t i=0;i<out->check.count;i++){yyjson_mut_val *copy=yyjson_val_mut_copy(entries,out->check.entries[i]);if(!copy||!yyjson_mut_arr_append(rows,copy)){error=err_make(ERR_NOMEM,"ledger entries allocation");goto done;}}
    error=json_freeze(entries,&out->entries);if(error.code)goto done;
    JsonWriter reason={0};
    for(size_t i=0;i<out->check.errors.count;i++) {
        error=runtime_diagnostic(out,path,STR_LIT("error"),out->check.errors.items[i]);if(error.code)break;
        if(i)jsonw_raw(&reason,"; ");jsonw_bytes(&reason,out->check.errors.items[i].p,out->check.errors.items[i].n);
    }
    if(!error.code)error=reason.error;
    if(!error.code&&out->check.errors.count)error=str_copy(&out->arena,(Str){reason.data,(uint32_t)reason.length},&out->reason);
    jsonw_free(&reason);if(error.code)goto done;
    for(size_t i=0;i<out->check.warnings.count;i++){error=runtime_diagnostic(out,path,STR_LIT("warning"),out->check.warnings.items[i]);if(error.code)goto done;}
    out->available=out->check.errors.count==0;
done:
    free(bytes);json_read_free(&parsed);json_read_free(&curated);yyjson_mut_doc_free(dictionary);yyjson_mut_doc_free(entries);return error;
}
Err runtime_ledger_history(const RuntimeLedger *ledger,yyjson_val *new_entries,PriceHistory *out) {
    yyjson_val *curated=get(yyjson_doc_get_root(ledger->curated),"entries"),*user=yyjson_doc_get_root(ledger->entries);
    if(!new_entries)return price_history(curated,user,out);
    if(!yyjson_is_arr(new_entries))return err_make(ERR_INVALID,"invalid new ledger entries");
    yyjson_mut_doc *combined=yyjson_mut_doc_new(NULL);yyjson_doc *frozen=NULL;if(!combined)return err_make(ERR_NOMEM,"history merge allocation");
    yyjson_mut_doc_set_root(combined,yyjson_val_mut_copy(combined,user));Err error=ERR_SUCCESS;
    if(!combined->root){error=err_make(ERR_NOMEM,"history merge allocation");goto done;}
    for(size_t i=0;i<yyjson_arr_size(new_entries);i++){yyjson_mut_val *copy=yyjson_val_mut_copy(combined,yyjson_arr_get(new_entries,i));if(!copy||!yyjson_mut_arr_append(combined->root,copy)){error=err_make(ERR_NOMEM,"history merge allocation");goto done;}}
    error=json_freeze(combined,&frozen);if(!error.code)error=price_history(curated,yyjson_doc_get_root(frozen),out);
done:
    yyjson_mut_doc_free(combined);yyjson_doc_free(frozen);return error;
}
void runtime_ledger_json(JsonWriter *w,const RuntimeLedger *ledger) {
    jsonw_raw(w,"[");if(ledger)for(LedgerDiagnostic *diagnostic=ledger->diagnostics;diagnostic;diagnostic=diagnostic->next){if(diagnostic!=ledger->diagnostics)jsonw_raw(w,",");jsonw_raw(w,"{\"level\":");jsonw_string(w,diagnostic->level);jsonw_raw(w,",\"message\":");jsonw_string(w,diagnostic->message);jsonw_raw(w,"}");}jsonw_raw(w,"]");
}
void runtime_ledger_destroy(RuntimeLedger *ledger) {ledger_check_destroy(&ledger->check);yyjson_doc_free(ledger->curated);yyjson_doc_free(ledger->document);yyjson_doc_free(ledger->entries);arena_destroy(&ledger->arena);*ledger=(RuntimeLedger){0};}
