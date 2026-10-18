#define _DARWIN_C_SOURCE
#include "db.h"
#include "meta/metadata.h"
#include "parse/record.h"
#include "testing/hooks.h"
#include "util/fileio.h"
#include "util/json_number.h"
#include "util/json_read.h"
#include "util/time.h"
#include <errno.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#define TRY(expr) do { Err e_=(expr); if(e_.code) return e_; } while(0)
#define APPEND(a,data,n,cap,value) record_append_aligned((a),(void **)&(data),&(n),&(cap),sizeof(value),_Alignof(__typeof__(value)),&(value))
static Str text(const char *s) { return s?(Str){s,(uint32_t)strlen(s)}:(Str){0}; }
static bool equal(Str a,const char *b) { return str_equal(a,text(b)); }
static Err sql_error(sqlite3 *db) {
    int code=sqlite3_errcode(db);
    /* SQLite error text can contain schema SQL or user-controlled values. */
    return err_make(code==SQLITE_NOMEM?ERR_NOMEM:ERR_IO,"OpenCode SQLite read failed (code %d)",code);
}
static Err prepare(sqlite3 *db,const char *sql,sqlite3_stmt **out) {
    return sqlite3_prepare_v2(db,sql,-1,out,NULL)==SQLITE_OK?ERR_SUCCESS:sql_error(db);
}
static Err execute(sqlite3 *db,const char *sql) {
    return sqlite3_exec(db,sql,NULL,NULL,NULL)==SQLITE_OK?ERR_SUCCESS:sql_error(db);
}
static bool allowed_table(const char *name) {
    static const char *const names[]={"project","session_v2","session_message","migration","kv","sqlite_master","sqlite_schema"};
    for(size_t i=0;i<sizeof names/sizeof *names;i++)if(name&&!strcmp(name,names[i]))return true;
    return false;
}
static int authorize(void *unused,int action,const char *a,const char *b,const char *db,const char *trigger) {
    (void)unused;(void)db;(void)trigger;
    switch(action){
    case SQLITE_SELECT:case SQLITE_TRANSACTION:case SQLITE_FUNCTION:return SQLITE_OK;
    case SQLITE_READ:return allowed_table(a)?SQLITE_OK:SQLITE_DENY;
    case SQLITE_PRAGMA:return a&&!strcmp(a,"table_info")&&allowed_table(b)?SQLITE_OK:SQLITE_DENY;
    default:return SQLITE_DENY;
    }
}
Err opencode_db_open(const char *path,sqlite3 **out) {
    *out=NULL;char *uri=NULL;sqlite3 *db=NULL;Err e=metadata_database_uri(path,&uri);
    if(!e.code&&sqlite3_open_v2(uri,&db,SQLITE_OPEN_READONLY|SQLITE_OPEN_URI,NULL)!=SQLITE_OK)e=sql_error(db);
    free(uri);
    if(!e.code&&sqlite3_busy_timeout(db,1000)!=SQLITE_OK)e=sql_error(db);
    if(!e.code&&sqlite3_set_authorizer(db,authorize,NULL)!=SQLITE_OK)e=sql_error(db);
    if(e.code){if(db)sqlite3_close(db);}else *out=db;
    return e;
}
Err opencode_store_add_database(OpencodeStore *s,Str path,bool primary) {
    if(!path.p||memchr(path.p,0,path.n))return err_make(ERR_INVALID,"invalid OpenCode database path");
    Str owned={0};
    /* Keep provenance independent of the caller's working-directory lifetime. */
    if(path.n&&path.p[0]=='/')TRY(file_lexical_path(path,false,&owned));
    else {
        char *cwd=getcwd(NULL,0);if(!cwd)return err_make(ERR_IO,"cannot read working directory");
        size_t n=strlen(cwd)+path.n+2;char *full=malloc(n);
        if(!full){free(cwd);return err_make(ERR_NOMEM,"OpenCode path allocation failed");}
        snprintf(full,n,"%s/%.*s",cwd,(int)path.n,path.p);free(cwd);
        Err e=file_lexical_path(text(full),false,&owned);free(full);if(e.code)return e;
    }
    Str absolute={0};Err e=str_copy(&s->arena,owned,&absolute);free((void *)owned.p);if(e.code)return e;
    OpencodeDatabase db={.path=absolute,.primary=primary,.status=OC_DB_SKIPPED};
    return APPEND(&s->arena,s->databases,s->database_count,s->database_capacity,db);
}
static Str sql_text(sqlite3_stmt *st,int col) {
    if(sqlite3_column_type(st,col)!=SQLITE_TEXT)return (Str){0};
    const char *p=(const char *)sqlite3_column_text(st,col);int n=sqlite3_column_bytes(st,col);
    Str value={p,(uint32_t)n};
    return p&&str_utf8_scalar_valid(value)&&!memchr(p,0,(size_t)n)?value:(Str){0};
}
static Err copy_cell(Arena *a,sqlite3_stmt *st,int col,Str *out) {
    Str value=sql_text(st,col);return value.p?str_copy(a,value,out):ERR_SUCCESS;
}
static yyjson_val *get(yyjson_val *v,const char *key) { return obj_get_last(v,text(key)); }
static Str js(yyjson_val *v) {
    if(!yyjson_is_str(v))return (Str){0};
    Str s={yyjson_get_str(v),(uint32_t)yyjson_get_len(v)};
    return str_utf8_scalar_valid(s)&&!memchr(s.p,0,s.n)?s:(Str){0};
}
static Err copy_json(Arena *a,yyjson_val *v,Str *out) {
    Str value=js(v);return value.p?str_copy(a,value,out):ERR_SUCCESS;
}
/* JSON decimals/exponents must be integral before any binary64 conversion.
 * Strip coefficient zeroes, then check the remaining decimal scale and the
 * signed-64 bound. Exponents saturate beyond the input length: a nonzero
 * coefficient can never return to range from that magnitude. */
static bool decimal_integer(Str raw,int64_t *out) {
    size_t i=raw.n&&raw.p[0]=='-',begin=i,digits=0,first=SIZE_MAX,last=0,fractional=0;
    bool point=false;
    while(i<raw.n&&raw.p[i]!='e'&&raw.p[i]!='E'){
        char c=raw.p[i++];
        if(c=='.'){point=true;continue;}
        if(c<'0'||c>'9')return false;
        if(c!='0'){if(first==SIZE_MAX)first=digits;last=digits;}
        digits++;if(point)fractional++;
    }
    if(!digits)return false;
    if(first==SIZE_MAX){*out=0;return true;}
    if(begin)return false;
    int64_t exponent=0,limit=(int64_t)raw.n+20;
    if(i<raw.n){
        i++;bool negative=i<raw.n&&raw.p[i]=='-';
        if(i<raw.n&&(raw.p[i]=='-'||raw.p[i]=='+'))i++;
        if(i==raw.n)return false;
        for(;i<raw.n;i++){
            unsigned digit=(unsigned)(raw.p[i]-'0');if(digit>9)return false;
            if(exponent>(limit-(int64_t)digit)/10)exponent=limit;
            else exponent=exponent*10+digit;
        }
        if(negative)exponent=-exponent;
    }
    int64_t scale=exponent-(int64_t)fractional+(int64_t)(digits-last-1);
    size_t significant=last-first+1;
    if(scale<0||scale>18||significant>19||(int64_t)significant+scale>19)return false;
    uint64_t value=0;size_t ordinal=0;
    for(i=begin;i<raw.n&&raw.p[i]!='e'&&raw.p[i]!='E';i++){
        if(raw.p[i]=='.')continue;
        unsigned digit=(unsigned)(raw.p[i]-'0');
        if(ordinal>=first&&ordinal<=last){
            if(value>((uint64_t)INT64_MAX-digit)/10)return false;
            value=value*10+digit;
        }
        ordinal++;
    }
    while(scale--){if(value>(uint64_t)INT64_MAX/10)return false;value*=10;}
    *out=(int64_t)value;return true;
}
static bool integer(yyjson_val *v,int64_t *out) {
    if(yyjson_is_raw(v)){
        Str raw={yyjson_get_raw(v),(uint32_t)yyjson_get_len(v)};
        if(!json_number_is_integer(raw))return decimal_integer(raw,out);
    }
    PyNum number;
    if(!json_number(v,"opencode.number",&number))return false;
    if(!number.is_float){if(number.i<0)return false;*out=number.i;return true;}
    if(!isfinite(number.f)||number.f<0||number.f>=0x1p63||trunc(number.f)!=number.f)return false;
    *out=(int64_t)number.f;return true;
}
static MaybeMs json_clock(yyjson_val *v,uint64_t *invalid) {
    MaybeMs clock={0};int64_t n;
    if(!v)return clock;
    if(integer(v,&n)&&time_ms_from_i64(n,true,"opencode.clock",&clock.value))clock.present=true;
    else (*invalid)++;
    return clock;
}
static MaybeMs sql_clock(sqlite3_stmt *st,int c,uint64_t *invalid) {
    MaybeMs clock={0};int kind=sqlite3_column_type(st,c);
    if(kind==SQLITE_NULL)return clock;
    int64_t n=kind==SQLITE_INTEGER?sqlite3_column_int64(st,c):-1;
    if(n>=0&&time_ms_from_i64(n,true,"opencode.clock",&clock.value))clock.present=true;
    else (*invalid)++;
    return clock;
}
static bool json_cost(yyjson_val *v,double *out) {
    /* Unlike tokens, recorded costs have no signed-integer bound. The JSON
     * reader has validated number spellings before this conversion. */
    double d;
    if(yyjson_is_raw(v))d=strtod(yyjson_get_raw(v),NULL);
    else if(yyjson_is_num(v))d=yyjson_get_num(v);
    else return false;
    if(!isfinite(d)||d<0)return false;
    *out=d;return true;
}
static bool json_tokens(yyjson_val *v,OpencodeTokens *out) {
    if(!yyjson_is_obj(v))return false;
    const char *names[]={"input","output","reasoning","read","write"};
    __int128 *fields[]={&out->input,&out->output,&out->reasoning,&out->cache_read,&out->cache_write};
    yyjson_val *cache=get(v,"cache");
    if(cache&&!yyjson_is_obj(cache))return false;
    for(size_t i=0;i<5;i++){
        yyjson_val *value=get(i<3?v:cache,names[i]);int64_t n=0;
        if(!value&&i>=2)continue;
        if(!integer(value,&n))return false;
        *fields[i]=n;
    }
    return true;
}
static Err increment(Arena *a,Omap *map,Str key,uint64_t amount) {
    uint64_t *value=omap_get(map,key);
    if(value){*value+=amount;return ERR_SUCCESS;}
    TRY(arena_alloc(a,sizeof *value,_Alignof(uint64_t),(void **)&value));*value=amount;
    return omap_put(map,key,value);
}
static Err merge_counts(Arena *a,Omap *to,const Omap *from) {
    for(OmapEntry *p=from->first;p;p=p->next)TRY(increment(a,to,p->key,*(uint64_t *)p->value));
    return ERR_SUCCESS;
}
/* Compatibility and SELECT columns share these lists; optional columns become
 * SQL NULL at their stable projection indexes. No SELECT * or content PRAGMAs. */
typedef struct { const char *name; bool optional; } Column;
static const Column session_columns[]={
    {"id",false},{"project_id",false},{"parent_id",false},{"fork_session_id",true},
    {"directory",false},{"title",false},{"version",false},{"agent",false},{"model",false},
    {"cost",false},{"tokens_input",false},{"tokens_output",false},{"tokens_reasoning",false},
    {"tokens_cache_read",false},{"tokens_cache_write",false},{"time_created",false},
    {"time_updated",false},{"time_idle",false},{"idle_outcome",false},{"time_archived",true}
};
static const Column message_columns[]={{"id",false},{"session_id",false},{"type",false},{"seq",false},{"time_created",false},{"data",false}};
static const Column project_columns[]={{"id",false},{"time_archived",true}};
static const Column migration_columns[]={{"id",false}};
static const Column kv_columns[]={{"key",false},{"value",false}};
typedef struct { const char *name;const Column *columns;size_t count;Omap available; } Table;
#define TABLE(name,columns) {name,columns,sizeof columns/sizeof *columns,{0}}
static Err schema_columns(sqlite3 *db,Table *table) {
    char sql[128];snprintf(sql,sizeof sql,"PRAGMA table_info(\"%s\")",table->name);
    sqlite3_stmt *st=NULL;Err e=prepare(db,sql,&st);int rc=SQLITE_DONE;
    while(!e.code&&(rc=sqlite3_step(st))==SQLITE_ROW){Str name=sql_text(st,1);if(name.p)e=omap_put(&table->available,name,(void *)1);}
    if(!e.code&&rc!=SQLITE_DONE)e=sql_error(db);
    sqlite3_finalize(st);
    for(size_t i=0;!e.code&&i<table->count;i++)if(!table->columns[i].optional&&!omap_get(&table->available,text(table->columns[i].name)))
        e=err_make(ERR_INVALID,"OpenCode %s missing required column %s",table->name,table->columns[i].name);
    return e;
}
static Err schema_guard(sqlite3 *db,OpencodeDatabase *info,Table *tables,size_t n) {
    sqlite3_stmt *st=NULL;Err e=prepare(db,"SELECT name,type FROM sqlite_master WHERE type IN ('table','view')",&st);
    int rc=SQLITE_DONE;bool legacy=false;Omap found={0};
    static const char *const generations[]={"session","session_v2","session_message","session_share","session_inbox","session_pending"};
    while(!e.code&&(rc=sqlite3_step(st))==SQLITE_ROW){
        Str name=sql_text(st,0),kind=sql_text(st,1);
        if(equal(name,"session"))legacy=true;
        if(name.n>=7&&!memcmp(name.p,"session",7)){
            bool allowed=false;for(size_t i=0;i<sizeof generations/sizeof *generations;i++)if(equal(name,generations[i]))allowed=true;
            if(!allowed)e=err_make(ERR_INVALID,"unrecognized OpenCode session generation table");
        }
        for(size_t i=0;!e.code&&i<n;i++)if(equal(name,tables[i].name)){
            if(!equal(kind,"table"))e=err_make(ERR_INVALID,"OpenCode query source is not a table");
            else e=omap_put(&found,name,(void *)1);
        }
    }
    if(!e.code&&rc!=SQLITE_DONE)e=sql_error(db);
    sqlite3_finalize(st);st=NULL;
    for(size_t i=0;!e.code&&i<n;i++){
        if(!omap_get(&found,text(tables[i].name)))e=err_make(ERR_INVALID,"OpenCode missing required table %s",tables[i].name);
        else e=schema_columns(db,&tables[i]);
    }
    omap_destroy(&found);
    if(!e.code)e=prepare(db,"SELECT id FROM migration ORDER BY id DESC LIMIT 1",&st);
    if(!e.code){rc=sqlite3_step(st);if(rc==SQLITE_ROW){Str id=sql_text(st,0);if(!id.n)e=err_make(ERR_INVALID,"invalid OpenCode migration id");else {e=str_copy(&info->arena,id,&info->latest_migration);info->untested=str_compare(id,STR_LIT("20261010180456_project_time_archived"))>0;}}else if(rc!=SQLITE_DONE)e=sql_error(db);}
    sqlite3_finalize(st);st=NULL;
    if(!e.code)e=prepare(db,"SELECT key FROM kv WHERE key LIKE 'migration.%'",&st);
    while(!e.code&&(rc=sqlite3_step(st))==SQLITE_ROW)if(!equal(sql_text(st,0),"migration.v1-v2"))e=err_make(ERR_INVALID,"unrecognized OpenCode migration key");
    if(!e.code&&rc!=SQLITE_DONE)e=sql_error(db);sqlite3_finalize(st);st=NULL;
    if(!e.code&&legacy){
        e=prepare(db,"SELECT value FROM kv WHERE key='migration.v1-v2'",&st);
        if(!e.code){rc=sqlite3_step(st);if(rc==SQLITE_ROW){
            JsonRead read=json_read(sql_text(st,0),STRICT,JSON_CONSTANTS_REJECT,"opencode.migration");
            if(read.status==JSON_NOMEM)e=err_make(ERR_NOMEM,"OpenCode migration JSON allocation failed");
            else if(read.status!=JSON_OK||!equal(js(get(yyjson_doc_get_root(read.doc),"phase")),"completed"))e=err_make(ERR_INVALID,"OpenCode v1 migration incomplete or malformed");
            json_read_free(&read);
        }else if(rc==SQLITE_DONE)e=err_make(ERR_INVALID,"OpenCode v1 migration phase missing");else e=sql_error(db);}
        sqlite3_finalize(st);
    }
    return e;
}
static size_t select_columns(char *sql,size_t size,size_t used,const Table *t,const char *alias) {
    for(size_t i=0;i<t->count;i++){
        bool has=omap_get(&t->available,text(t->columns[i].name))!=NULL;
        used+=(size_t)snprintf(sql+used,size-used,"%s%s",i?",":"",has?alias:"NULL");
        if(has)used+=(size_t)snprintf(sql+used,size-used,".\"%s\"",t->columns[i].name);
    }
    return used;
}
static Err model(Arena *a,yyjson_val *v,Str *id,Str *provider) {
    TRY(copy_json(a,get(v,"id"),id));return copy_json(a,get(v,"providerID"),provider);
}
static Err read_sessions(sqlite3 *db,Table *tables,OpencodeStore *stage,OpencodeDatabase *info,size_t index,volatile sig_atomic_t *stop) {
    char sql[2048]="SELECT ";size_t used=select_columns(sql,sizeof sql,7,&tables[0],"s");
    snprintf(sql+used,sizeof sql-used,",%s FROM session_v2 s LEFT JOIN project p ON p.id=s.project_id ORDER BY s.id",
        omap_get(&tables[2].available,STR_LIT("time_archived"))?"p.time_archived":"NULL");
    sqlite3_stmt *st=NULL;Err e=prepare(db,sql,&st);int rc=SQLITE_DONE;
    while(!e.code&&(rc=sqlite3_step(st))==SQLITE_ROW){
        if(stop&&cp_fault("opencode.cancel.sessions"))*stop=1;
        if(stop&&*stop){e=err_make(ERR_IO,"interrupted");break;}
        Str id=sql_text(st,0);if(!id.n)continue;
        OpencodeSession *s=NULL;e=arena_alloc(&stage->arena,sizeof *s,_Alignof(OpencodeSession),(void **)&s);if(e.code)break;
        memset(s,0,sizeof *s);s->database=info->path;s->database_index=index;s->primary=info->primary;s->provenance_complete=true;
        Str *strings[]={&s->id,&s->project_id,&s->parent_id,&s->fork_session_id,&s->directory,&s->title,&s->version,&s->agent};
        for(int i=0;!e.code&&i<8;i++)e=copy_cell(&stage->arena,st,i,strings[i]);
        if(e.code)break;
        JsonRead read=json_read(sql_text(st,8),STRICT,JSON_CONSTANTS_REJECT,"opencode.session.model");
        if(read.status==JSON_NOMEM)e=err_make(ERR_NOMEM,"OpenCode model JSON allocation failed");
        else if(read.status==JSON_OK)e=model(&stage->arena,yyjson_doc_get_root(read.doc),&s->model_id,&s->provider_id);
        json_read_free(&read);if(e.code)break;
        s->cost_present=sqlite3_column_type(st,9)!=SQLITE_NULL;
        int type=sqlite3_column_type(st,9);
        if(type==SQLITE_INTEGER||type==SQLITE_FLOAT)s->cost=sqlite3_column_double(st,9);
        s->cost_valid=(type==SQLITE_INTEGER||type==SQLITE_FLOAT)&&isfinite(s->cost)&&s->cost>=0;
        if(s->cost_present&&!s->cost_valid)s->invalid_numbers++;
        s->tokens_present=true;s->tokens_valid=true;
        __int128 *fields[]={&s->tokens.input,&s->tokens.output,&s->tokens.reasoning,&s->tokens.cache_read,&s->tokens.cache_write};
        for(int i=0;i<5;i++){
            if(sqlite3_column_type(st,10+i)!=SQLITE_INTEGER||sqlite3_column_int64(st,10+i)<0){s->tokens_valid=false;s->invalid_numbers++;}
            else *fields[i]=sqlite3_column_int64(st,10+i);
        }
        s->created_ms=sql_clock(st,15,&s->invalid_numbers);s->updated_ms=sql_clock(st,16,&s->invalid_numbers);s->idle_ms=sql_clock(st,17,&s->invalid_numbers);
        e=copy_cell(&stage->arena,st,18,&s->idle_outcome);
        MaybeMs archived=sql_clock(st,19,&s->invalid_numbers),project=sql_clock(st,20,&s->invalid_numbers);
        s->archived=archived.present;s->project_archived=project.present;
        if(!e.code)e=APPEND(&stage->arena,stage->sessions,stage->session_count,stage->session_capacity,s);
        if(!e.code)e=omap_put(&stage->session_ids,s->id,s);
    }
    if(!e.code&&rc!=SQLITE_DONE)e=sql_error(db);sqlite3_finalize(st);return e;
}
static bool message_kind(Str type,OpencodeMessageKind *out) {
    static const char *const kinds[]={"agent-switched","model-switched","location-switched","user","synthetic","system","skill","shell","assistant","compaction","idle"};
    for(size_t i=0;i<sizeof kinds/sizeof *kinds;i++)if(equal(type,kinds[i])){*out=(OpencodeMessageKind)i;return true;}
    return false;
}
static Err append_text(Arena *a,Str *out,Str piece) {
    if(!piece.n)return ERR_SUCCESS;
    if(piece.n>UINT32_MAX-out->n)return err_make(ERR_NOMEM,"OpenCode text too large");
    char *p=NULL;TRY(arena_alloc(a,(size_t)out->n+piece.n+1,1,(void **)&p));
    if(out->n)memcpy(p,out->p,out->n);memcpy(p+out->n,piece.p,piece.n);p[out->n+piece.n]=0;
    *out=(Str){p,out->n+piece.n};return ERR_SUCCESS;
}
static Err parse_content(Arena *a,OpencodeSession *s,OpencodeMessage *m,yyjson_val *content,bool *malformed) {
    if(!yyjson_is_arr(content)){*malformed=true;return ERR_SUCCESS;}
    size_t i,max;yyjson_val *v;
    yyjson_arr_foreach(content,i,max,v){
        Str type=js(get(v,"type"));
        if(!yyjson_is_obj(v)||!type.n){*malformed=true;continue;}
        if(equal(type,"text")){
            Str part=js(get(v,"text"));if(!part.p){*malformed=true;continue;}
            TRY(append_text(a,&m->text,part));
        }else if(equal(type,"reasoning")){
            if(!js(get(v,"text")).p)*malformed=true;
        }else if(equal(type,"tool")){
            yyjson_val *state=get(v,"state"),*time=get(v,"time");Str status=js(get(state,"status"));
            Str id=js(get(v,"id")),name=js(get(v,"name"));
            if(!id.n||!name.n||!(equal(status,"streaming")||equal(status,"running")||equal(status,"completed")||equal(status,"error"))){*malformed=true;continue;}
            OpencodeTool tool={.failed=equal(status,"error")};
            TRY(str_copy(a,id,&tool.id));TRY(str_copy(a,name,&tool.name));
            yyjson_val *metadata=get(state,"metadata");Str child=js(get(metadata,"sessionID"));if(!child.n)child=js(get(metadata,"sessionId"));
            TRY(str_copy(a,child,&tool.child_session_id));
            tool.created_ms=json_clock(get(time,"created"),&s->invalid_numbers);tool.ran_ms=json_clock(get(time,"ran"),&s->invalid_numbers);tool.completed_ms=json_clock(get(time,"completed"),&s->invalid_numbers);
            TRY(APPEND(a,m->tools,m->tool_count,m->tool_capacity,tool));
        }else {
            TRY(increment(a,&s->unknown_content_types,type.p?type:STR_LIT("<missing>"),1));s->provenance_complete=false;
        }
    }
    return ERR_SUCCESS;
}
static Err parse_message(Arena *a,OpencodeSession *s,sqlite3_stmt *st) {
    Str type=sql_text(st,2);OpencodeMessage m={0};
    if(!message_kind(type,&m.kind)){
        s->provenance_complete=false;return increment(a,&s->unknown_message_types,type.p?type:STR_LIT("<missing>"),1);
    }
    bool malformed=false;JsonRead read=json_read(sql_text(st,5),STRICT,JSON_CONSTANTS_ALLOW,"opencode.message");
    Err e=ERR_SUCCESS;
    if(read.status==JSON_NOMEM)e=err_make(ERR_NOMEM,"OpenCode message JSON allocation failed");
    yyjson_val *v=read.status==JSON_OK?yyjson_doc_get_root(read.doc):NULL;
    Str id=sql_text(st,0);
    if(!yyjson_is_obj(v)||!id.n||!str_equal(js(get(v,"type")),type)||!js(get(v,"id")).n||sqlite3_column_type(st,3)!=SQLITE_INTEGER||sqlite3_column_int64(st,3)<0)malformed=true;
    if(!e.code&&!malformed){
        e=str_copy(a,id,&m.id);if(!e.code)e=str_copy(a,type,&m.type);m.seq=sqlite3_column_int64(st,3);
        m.row_created_ms=sql_clock(st,4,&s->invalid_numbers);
        yyjson_val *time=get(v,"time");
        m.created_ms=json_clock(get(time,"created"),&s->invalid_numbers);m.streamed_ms=json_clock(get(time,"streamed"),&s->invalid_numbers);m.completed_ms=json_clock(get(time,"completed"),&s->invalid_numbers);
        if(!yyjson_is_obj(time))malformed=true;
        if(!e.code)e=model(a,get(v,"model"),&m.model_id,&m.provider_id);
        if(!e.code)e=copy_json(a,get(v,"agent"),&m.agent);
        if(!e.code)e=copy_json(a,get(v,"finish"),&m.finish);
        /* Structured error type is sufficient; no credential-bearing body or message. */
        if(!e.code)e=copy_json(a,get(get(v,"error"),"type"),&m.error);
        if(!e.code)e=copy_json(a,get(v,"status"),&m.status);
        if(!e.code)e=copy_json(a,get(v,"outcome"),&m.outcome);
        if(!e.code&&m.kind==OC_MSG_ASSISTANT)e=parse_content(a,s,&m,get(v,"content"),&malformed);
        else if(!e.code&&(m.kind==OC_MSG_USER||m.kind==OC_MSG_SYNTHETIC||m.kind==OC_MSG_SYSTEM||m.kind==OC_MSG_SKILL)){
            Str body=js(get(v,"text"));if(!body.p)malformed=true;else e=str_copy(a,body,&m.text);
            if(m.kind==OC_MSG_USER){
                yyjson_val *files=get(v,"files");if(files&&!yyjson_is_arr(files))malformed=true;
                size_t i,max;yyjson_val *file;yyjson_arr_foreach(files,i,max,file){Str mime=js(get(file,"mime"));if(mime.n>6&&!memcmp(mime.p,"image/",6))m.images++;}
            }
        }else if(!e.code&&m.kind==OC_MSG_SHELL){if(!js(get(v,"command")).p||!m.status.n)malformed=true;}
        else if(!e.code&&m.kind==OC_MSG_AGENT){if(!m.agent.n)malformed=true;}
        else if(!e.code&&m.kind==OC_MSG_MODEL){if(!m.model_id.n||!m.provider_id.n)malformed=true;}
        else if(!e.code&&m.kind==OC_MSG_LOCATION){if(!yyjson_is_obj(get(v,"location")))malformed=true;}
        else if(!e.code&&m.kind==OC_MSG_COMPACTION){if(!(equal(m.status,"running")||equal(m.status,"completed")||equal(m.status,"failed")))malformed=true;}
        else if(!e.code&&m.kind==OC_MSG_IDLE){if(!(equal(m.outcome,"succeeded")||equal(m.outcome,"failed")||equal(m.outcome,"interrupted")))malformed=true;}
        if(m.kind==OC_MSG_ASSISTANT||m.kind==OC_MSG_COMPACTION){
            yyjson_val *tokens=get(v,"tokens"),*cost=get(v,"cost");
            m.tokens_present=tokens!=NULL;m.cost_present=cost!=NULL;
            m.tokens_valid=tokens&&json_tokens(tokens,&m.tokens);m.cost_valid=cost&&json_cost(cost,&m.cost);
            if(tokens&&!m.tokens_valid)s->invalid_numbers++;if(cost&&!m.cost_valid)s->invalid_numbers++;
        }
        if(!e.code&&!malformed)e=APPEND(a,s->messages,s->message_count,s->message_capacity,m);
    }
    if(malformed){s->malformed_messages++;s->provenance_complete=false;}
    json_read_free(&read);return e;
}
static Err read_messages(sqlite3 *db,Table *table,OpencodeStore *stage,volatile sig_atomic_t *stop) {
    char sql[1024]="SELECT ";size_t n=select_columns(sql,sizeof sql,7,table,"m");
    snprintf(sql+n,sizeof sql-n," FROM session_message m ORDER BY m.session_id,m.seq,m.id");
    sqlite3_stmt *st=NULL;Err e=prepare(db,sql,&st);int rc=SQLITE_DONE;
    while(!e.code&&(rc=sqlite3_step(st))==SQLITE_ROW){
        if(cp_fault("opencode.read.messages")){e=err_make(ERR_IO,"OpenCode message read failed");break;}
        if(stop&&*stop){e=err_make(ERR_IO,"interrupted");break;}
        OpencodeSession *s=omap_get(&stage->session_ids,sql_text(st,1));
        if(s)e=parse_message(&stage->arena,s,st);
    }
    if(!e.code&&rc!=SQLITE_DONE)e=sql_error(db);sqlite3_finalize(st);return e;
}
static int progress(void *data) {
    volatile sig_atomic_t *stop=data;
    if(stop&&cp_fault("opencode.cancel.progress"))*stop=1;
    return stop&&*stop;
}
static void session_maps_destroy(OpencodeSession *s) { omap_destroy(&s->unknown_message_types);omap_destroy(&s->unknown_content_types); }
static void stage_destroy(OpencodeStore *s) {
    for(size_t i=0;i<s->session_count;i++)session_maps_destroy(s->sessions[i]);
    omap_destroy(&s->session_ids);arena_destroy(&s->arena);memset(s,0,sizeof *s);
}
static Err read_database(OpencodeStore *stage,OpencodeDatabase *info,size_t index,volatile sig_atomic_t *stop) {
    sqlite3 *db=NULL;Err e=opencode_db_open(info->path.p,&db);
    Table tables[]={TABLE("session_v2",session_columns),TABLE("session_message",message_columns),TABLE("project",project_columns),TABLE("migration",migration_columns),TABLE("kv",kv_columns)};
    if(!e.code)sqlite3_progress_handler(db,1000,progress,(void *)stop);
    if(!e.code)e=execute(db,"BEGIN");
    if(!e.code)e=schema_guard(db,info,tables,sizeof tables/sizeof *tables);
    if(!e.code)e=read_sessions(db,tables,stage,info,index,stop);
    if(!e.code)e=read_messages(db,&tables[1],stage,stop);
    if(!e.code&&stop&&cp_fault("opencode.cancel.commit"))*stop=1;
    if(!e.code&&stop&&*stop)e=err_make(ERR_IO,"interrupted");
    if(!e.code)e=execute(db,"COMMIT");
    for(size_t i=0;i<sizeof tables/sizeof *tables;i++)omap_destroy(&tables[i].available);
    if(db)sqlite3_close(db);
    return e;
}
Err opencode_store_read(OpencodeStore *store,volatile sig_atomic_t *stop) {
    for(size_t i=0;i<store->database_count;i++){
        if(stop&&*stop)return err_make(ERR_IO,"interrupted");
        OpencodeDatabase *info=&store->databases[i];struct stat st;
        if(stat(info->path.p,&st)<0){
            info->status=errno==ENOENT?OC_DB_ABSENT:OC_DB_UNREADABLE;
            TRY(str_copy(&store->arena,info->status==OC_DB_ABSENT?STR_LIT("database absent"):STR_LIT("database inaccessible"),&info->reason));continue;
        }
        if(!S_ISREG(st.st_mode)){info->status=OC_DB_SKIPPED;TRY(str_copy(&store->arena,STR_LIT("database is not a regular file"),&info->reason));continue;}
        OpencodeStore stage={0};Err e=read_database(&stage,info,i,stop);
        if(e.code){
            stage_destroy(&stage);arena_destroy(&info->arena);info->latest_migration=(Str){0};info->untested=false;
            if(e.code==ERR_NOMEM||(stop&&*stop))return e;
            info->status=e.code==ERR_INVALID?OC_DB_UNSUPPORTED:OC_DB_UNREADABLE;
            TRY(str_copy(&store->arena,text(e.message),&info->reason));continue;
        }
        info->status=OC_DB_OK;
        for(size_t j=0;!e.code&&j<stage.session_count;j++){
            OpencodeSession *s=stage.sessions[j];
            if(omap_get(&store->session_ids,s->id)){store->duplicate_sessions++;continue;}
            e=APPEND(&store->arena,store->sessions,store->session_count,store->session_capacity,s);
            if(!e.code)e=omap_put(&store->session_ids,s->id,s);
            if(!e.code)e=merge_counts(&store->arena,&store->unknown_message_types,&s->unknown_message_types);
            if(!e.code)e=merge_counts(&store->arena,&store->unknown_content_types,&s->unknown_content_types);
            if(!e.code){store->malformed_messages+=s->malformed_messages;store->invalid_numbers+=s->invalid_numbers;info->accepted_sessions++;info->accepted_messages+=s->message_count;}
        }
        /* Accepted session maps survive with their database arena. Destroy
         * duplicate-loser maps before releasing the temporary session index. */
        for(size_t j=0;j<stage.session_count;j++){
            OpencodeSession *s=stage.sessions[j];
            if(omap_get(&store->session_ids,s->id)!=s)session_maps_destroy(s);
        }
        omap_destroy(&stage.session_ids);
        /* Transfer the staging arena separately from migration metadata. */
        if(!e.code){
            /* Migration metadata was allocated before facts; preserve it in the
             * store arena before replacing the database's arena owner. */
            Str migration={0};e=str_copy(&store->arena,info->latest_migration,&migration);
            if(!e.code){arena_destroy(&info->arena);info->latest_migration=migration;info->arena=stage.arena;stage.arena=(Arena){0};}
        }
        if(e.code){
            /* Already-published pointers need the staging owner even on NOMEM. */
            arena_destroy(&info->arena);info->latest_migration=(Str){0};info->arena=stage.arena;
            return e;
        }
    }
    return ERR_SUCCESS;
}
void opencode_store_destroy(OpencodeStore *s) {
    for(size_t i=0;i<s->session_count;i++)session_maps_destroy(s->sessions[i]);
    omap_destroy(&s->session_ids);omap_destroy(&s->unknown_message_types);omap_destroy(&s->unknown_content_types);
    for(size_t i=0;i<s->database_count;i++)arena_destroy(&s->databases[i].arena);
    arena_destroy(&s->arena);memset(s,0,sizeof *s);
}
