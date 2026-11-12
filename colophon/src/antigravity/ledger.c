#include "ledger.h"
#include "corpus.h"
#include "model.h"
#include "scan.h"
#include "corpus/provider.h"
#include "corpus/subagents.h"
#include "corpus/titles.h"
#include "out/jsonw.h"
#include "parse/record.h"
#include "util/atomic.h"
#include "util/fileio.h"
#include "util/sha256.h"
#include "util/sort.h"
#include <dirent.h>
#include <errno.h>
#include <stdalign.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#define TRY(x) do {Err e_=(x);if(e_.code)return e_;}while(0)
#define APPEND(a,d,n,c,v) record_append_aligned(a,(void **)&(d),&(n),&(c),sizeof(v),_Alignof(__typeof__(v)),&(v))
static Str text(const char *s){return (Str){s,(uint32_t)strlen(s)};}
static char *join(const char *a,const char *b){size_t n=strlen(a)+strlen(b)+2;char *p=malloc(n);if(p)snprintf(p,n,"%s/%s",a,b);return p;}
static yyjson_val *get(yyjson_val *v,const char *key){return yyjson_obj_get(v,key);}
static bool integer(yyjson_val *v,int64_t *out){if(yyjson_is_sint(v)){*out=yyjson_get_sint(v);return true;}if(yyjson_is_uint(v)&&yyjson_get_uint(v)<=INT64_MAX){*out=(int64_t)yyjson_get_uint(v);return true;}return false;}
static bool string(yyjson_val *v,Str *out){if(!yyjson_is_str(v)||yyjson_get_len(v)>UINT32_MAX)return false;*out=(Str){yyjson_get_str(v),(uint32_t)yyjson_get_len(v)};return true;}
static bool boolean(yyjson_val *v,bool *out){if(!yyjson_is_bool(v))return false;*out=yyjson_get_bool(v);return true;}
static bool maybe_ms(yyjson_val *v,MaybeMs *out){if(yyjson_is_null(v)){*out=(MaybeMs){0};return true;}int64_t n;if(!integer(v,&n))return false;*out=(MaybeMs){true,n};return true;}
static int unhex(char c){return c>='0'&&c<='9'?c-'0':c>='a'&&c<='f'?c-'a'+10:c>='A'&&c<='F'?c-'A'+10:-1;}
static bool copy_string(Arena *a,yyjson_val *v,Str *out,bool *oom){Str s;if(!string(v,&s))return false;Err e=str_copy(a,s,out);if(e.code)*oom=true;return !e.code;}
static bool decode(AntigravityLedger *l,AntigravityLedgerRecord *r,Str raw,Str expected,Str home,bool *oom){
    yyjson_read_err read_error={0};yyjson_doc *doc=yyjson_read_opts((char *)raw.p,raw.n,0,NULL,&read_error);if(!doc){*oom=read_error.code==YYJSON_READ_ERROR_MEMORY_ALLOCATION;return false;}yyjson_val *v=yyjson_doc_get_root(doc),*x;int64_t n;bool ok=yyjson_is_obj(v)&&integer(get(v,"schema"),&n)&&n==1;
    SessionModel *s=&r->header;Str id={0},stored_home={0};
    ok=ok&&copy_string(&l->arena,get(v,"id"),&id,oom)&&antigravity_uuid(id)&&str_equal(id,expected)&&copy_string(&l->arena,get(v,"home"),&stored_home,oom)&&str_equal(stored_home,home);
    s->id=s->key=s->identity=id;s->meta.id=id;s->provider=PROVIDER_ANTIGRAVITY;
    ok=ok&&copy_string(&l->arena,get(v,"surface"),&s->antigravity_surface,oom)&&copy_string(&l->arena,get(v,"title"),&s->title_full,oom)&&copy_string(&l->arena,get(v,"title_source"),&s->title_source,oom)&&boolean(get(v,"archived"),&s->archived)&&maybe_ms(get(v,"start_ms"),&s->start_ms)&&maybe_ms(get(v,"end_ms"),&s->end_ms);
    Str cwd={0},branch={0};ok=ok&&copy_string(&l->arena,get(v,"cwd"),&cwd,oom)&&copy_string(&l->arena,get(v,"git_root"),&s->antigravity_git_root,oom)&&copy_string(&l->arena,get(v,"branch"),&branch,oom)&&copy_string(&l->arena,get(v,"parent_id"),&s->parent_id,oom)&&boolean(get(v,"is_subagent"),&s->is_subagent);
    s->meta.cwd=(JScalar){.kind=cwd.n?JS_STRING:JS_ABSENT,.value.s=cwd};s->meta.branch=(JScalar){.kind=branch.n?JS_STRING:JS_ABSENT,.value.s=branch};
    x=get(v,"source");ok=ok&&yyjson_is_obj(x)&&integer(get(x,"size"),&r->source_size)&&r->source_size>=0&&integer(get(x,"mtime_ns"),&r->source_mtime_ns);
    x=get(v,"events");ok=ok&&yyjson_is_arr(x);size_t idx,max;yyjson_val *item;
    if(ok)yyjson_arr_foreach(x,idx,max,item){AntigravityLedgerEvent event={0};int64_t order;yyjson_val *tokens=get(item,"tokens"),*ids=get(item,"ids");
        ok=yyjson_is_obj(item)&&integer(get(item,"order"),&order)&&order>=0&&yyjson_is_arr(tokens)&&yyjson_arr_size(tokens)==6&&boolean(get(item,"reasoning"),&event.reasoning)&&boolean(get(item,"step_clock"),&event.step_clock)&&maybe_ms(get(item,"at_ms"),&event.at_ms)&&copy_string(&l->arena,get(item,"model_raw"),&event.model_raw,oom)&&yyjson_is_arr(ids);if(ok)event.order=(size_t)order;
        yyjson_val *model=get(item,"model_number");if(yyjson_is_null(model))event.has_model_number=false;else {event.has_model_number=integer(model,&event.model_number);ok=ok&&event.has_model_number;}
        for(size_t i=0;ok&&i<6;i++){n=0;ok=integer(yyjson_arr_get(tokens,i),&n)&&n>=0;event.tokens[i]=(uint64_t)n;}
        size_t j,k;yyjson_val *pair;const int fields[]={11,12,7};if(ok)yyjson_arr_foreach(ids,j,k,pair){int64_t field;Str hex={0};ok=yyjson_is_arr(pair)&&yyjson_arr_size(pair)==2&&integer(yyjson_arr_get(pair,0),&field)&&string(yyjson_arr_get(pair,1),&hex)&&!(hex.n%2);if(!ok)break;size_t slot=0;while(slot<3&&fields[slot]!=field)slot++;if(slot==3||event.ids[slot].p)ok=false;
            char *p=NULL;if(ok&&arena_alloc(&l->arena,hex.n/2+1,1,(void**)&p).code){*oom=true;ok=false;}for(size_t z=0;ok&&z<hex.n;z+=2){int a=unhex(hex.p[z]),b=unhex(hex.p[z+1]);if(a<0||b<0)ok=false;else p[z/2]=(char)(a*16+b);}if(ok)event.ids[slot]=(Str){p,hex.n/2};if(!ok)break;}
        if(!ok)break;if(APPEND(&l->arena,r->events,r->event_count,r->event_capacity,event).code){*oom=true;ok=false;break;}
    }
    r->previous_count=r->event_count;yyjson_doc_free(doc);return ok;
}
static int path_order(const void *a,const void *b,void *context){(void)context;const char *const *x=a,*const *y=b;return strcmp(*x,*y);}
Err antigravity_ledger_load(const char *home,AntigravityStore *store,AntigravityLedger *l){
    if(store->disabled)return ERR_SUCCESS;char hash[65];sha256_hex(store->home.p,store->home.n,hash);
    char *base=join(home,"antigravity-ledger");if(!base)return err_make(ERR_NOMEM,"ledger path allocation failed");l->directory=join(base,hash);free(base);if(!l->directory)return err_make(ERR_NOMEM,"ledger path allocation failed");
    DIR *dir=opendir(l->directory);if(!dir){if(errno==ENOENT)return ERR_SUCCESS;return err_make(ERR_IO,"cannot open Antigravity ledger directory");}
    char **names=NULL;size_t count=0,capacity=0;Err error=ERR_SUCCESS;struct dirent *entry;
    for(;;){errno=0;entry=readdir(dir);if(!entry){if(errno)error=err_make(ERR_IO,"cannot enumerate Antigravity ledger directory");break;}size_t n=strlen(entry->d_name);if(n<6||strcmp(entry->d_name+n-5,".json"))continue;
        if(count==capacity){size_t next=capacity?capacity*2:16;char **p=realloc(names,next*sizeof *p);if(!p){error=err_make(ERR_NOMEM,"ledger names allocation failed");break;}names=p;capacity=next;}
        names[count]=strdup(entry->d_name);if(!names[count]){error=err_make(ERR_NOMEM,"ledger name allocation failed");break;}count++;
    }
    if(closedir(dir)&&!error.code)error=err_make(ERR_IO,"cannot close Antigravity ledger directory");
    if(!error.code)error=stable_sort(names,count,sizeof *names,path_order,NULL);
    for(size_t i=0;!error.code&&i<count;i++){
        char *path=join(l->directory,names[i]);if(!path){error=err_make(ERR_NOMEM,"ledger path allocation failed");break;}
        size_t len=strlen(names[i])-5;Str id={names[i],(uint32_t)len};AntigravityLedgerRecord *r=NULL;error=arena_alloc(&l->arena,sizeof *r,alignof(AntigravityLedgerRecord),(void**)&r);if(error.code){free(path);break;}*r=(AntigravityLedgerRecord){0};
        error=str_copy(&l->arena,text(path),&r->path);char *bytes=NULL;size_t n=0;struct stat st;
        bool regular=!lstat(path,&st)&&S_ISREG(st.st_mode);Err read=regular?file_read_all(path,&bytes,&n):err_make(ERR_IO,"invalid ledger file");
        bool oom=false;if(!error.code&&(!read.code&&n<=UINT32_MAX))r->unreadable=!decode(l,r,(Str){bytes,(uint32_t)n},id,store->home,&oom);else r->unreadable=true;if(oom||read.code==ERR_NOMEM)error=err_make(ERR_NOMEM,"ledger decode allocation failed");
        if(!error.code&&!r->unreadable)error=str_copy(&l->arena,(Str){bytes,(uint32_t)n},&r->original);
        if(!error.code&&r->unreadable)error=corpus_strings_add(&store->arena,&store->ledger_unreadable,r->path);
        if(!error.code)error=str_copy(&l->arena,id,&r->header.id);
        if(!error.code)error=omap_put(&l->by_id,r->header.id,r);
        if(!error.code)error=APPEND(&l->arena,l->records,l->count,l->capacity,r);
        free(bytes);free(path);
    }
    for(size_t i=0;i<count;i++)free(names[i]);free(names);return error;
}
bool antigravity_ledger_present(const AntigravityLedger *l){return l->count!=0;}
Err antigravity_ledger_corpus_add(AntigravityLedger *l,AntigravityStore *store,Corpus *c){
    Err e=ERR_SUCCESS;Omap public_ids={0};for(OmapEntry *q=c->sessions.first;!e.code&&q;q=q->next){SessionModel *s=q->value;e=omap_put(&public_ids,s->id,s);}
    for(size_t i=0;!e.code&&i<l->count;i++){AntigravityLedgerRecord *r=l->records[i];SessionModel *s=&r->header;if(r->unreadable)continue;SessionModel *existing=omap_get(&c->sessions,s->id);if(existing&&existing->provider==PROVIDER_ANTIGRAVITY)continue;if(existing||omap_get(&public_ids,s->id)){e=corpus_strings_add(&store->arena,&store->corpus_collisions,s->id);continue;}
        s->flags=F_RETAINED;s->kind=s->is_subagent?STR_LIT("subagent"):STR_LIT("session");s->agent_label=s->is_subagent?s->title_full:(Str){0};s->archive_reason=s->archived?STR_LIT("session"):(Str){0};s->meta.is_subagent=s->is_subagent;s->has_link=s->parent_id.n;s->has_depth=!s->is_subagent;
        s->meta.parent_thread_id=(JScalar){.kind=s->parent_id.n?JS_STRING:JS_ABSENT,.value.s=s->parent_id};s->meta.created_at_ms=s->start_ms;s->created_at_ms=(MaybeNum){s->start_ms.present,{.i=s->start_ms.value}};
        e=title_display(&c->arena,s->title_full,&s->title);if(!e.code)e=corpus_session_idle(&c->arena,s);if(!e.code)e=omap_put(&c->sessions,s->id,s);if(!e.code){r->retained=true;store->ledger_retained++;}
    }
    omap_destroy(&public_ids);if(!e.code)e=antigravity_corpus_link(store,c);return e;
}
Err antigravity_ledger_begin(AntigravityLedger *l,SessionModel *s,const AntigravitySession *source){
    if(!l)return ERR_SUCCESS;AntigravityLedgerRecord *r=omap_get(&l->by_id,s->id);
    if(!r){TRY(arena_alloc(&l->arena,sizeof *r,alignof(AntigravityLedgerRecord),(void**)&r));*r=(AntigravityLedgerRecord){0};r->header=*s;TRY(omap_put(&l->by_id,s->id,r));TRY(APPEND(&l->arena,l->records,l->count,l->capacity,r));}
    if(r->unreadable)return ERR_SUCCESS;
    r->header=*s;r->event_count=0;r->live=true;struct stat st;
    if(!stat(source->database.p,&st)){r->source_size=st.st_size;__int128 ns=(__int128)st.st_mtimespec.tv_sec*1000000000+st.st_mtimespec.tv_nsec;if(ns>=INT64_MIN&&ns<=INT64_MAX)r->source_mtime_ns=(int64_t)ns;}
    return ERR_SUCCESS;
}
Err antigravity_ledger_capture(AntigravityLedger *l,SessionModel *s,AntigravityLedgerEvent event){
    if(!l)return ERR_SUCCESS;AntigravityLedgerRecord *r=omap_get(&l->by_id,s->id);if(!r||r->unreadable)return ERR_SUCCESS;
    TRY(str_copy(&l->arena,event.model_raw,&event.model_raw));for(size_t i=0;i<3;i++)if(event.ids[i].n)TRY(str_copy(&l->arena,event.ids[i],&event.ids[i]));
    return APPEND(&l->arena,r->events,r->event_count,r->event_capacity,event);
}
static void field_str(JsonWriter *w,const char *key,Str value){jsonw_raw(w,key);jsonw_string(w,value);}
static void field_ms(JsonWriter *w,const char *key,MaybeMs value){jsonw_raw(w,key);if(value.present)jsonw_i64(w,value.value);else jsonw_raw(w,"null");}
static void encode(JsonWriter *w,const AntigravityLedgerRecord *r,Str home){
    const SessionModel *s=&r->header;jsonw_raw(w,"{\"schema\":1");field_str(w,",\"id\":",s->id);field_str(w,",\"surface\":",s->antigravity_surface);field_str(w,",\"home\":",home);field_str(w,",\"title\":",s->title_full);field_str(w,",\"title_source\":",s->title_source);
    jsonw_raw(w,s->archived?",\"archived\":true":",\"archived\":false");field_ms(w,",\"start_ms\":",s->start_ms);field_ms(w,",\"end_ms\":",s->end_ms);
    field_str(w,",\"cwd\":",s->meta.cwd.kind==JS_STRING?s->meta.cwd.value.s:(Str){0});field_str(w,",\"git_root\":",s->antigravity_git_root);field_str(w,",\"branch\":",s->meta.branch.kind==JS_STRING?s->meta.branch.value.s:(Str){0});field_str(w,",\"parent_id\":",s->parent_id);
    jsonw_raw(w,s->is_subagent?",\"is_subagent\":true":",\"is_subagent\":false");jsonw_raw(w,",\"source\":{\"size\":");jsonw_i64(w,r->source_size);jsonw_raw(w,",\"mtime_ns\":");jsonw_i64(w,r->source_mtime_ns);jsonw_raw(w,"},\"events\":[");
    static const char hex[]="0123456789abcdef";const int fields[]={11,12,7};
    for(size_t i=0;i<r->event_count;i++){const AntigravityLedgerEvent *e=&r->events[i];if(i)jsonw_raw(w,",");jsonw_raw(w,"{\"order\":");jsonw_i64(w,(int64_t)e->order);jsonw_raw(w,",\"tokens\":[");for(size_t j=0;j<6;j++){if(j)jsonw_raw(w,",");jsonw_i64(w,(int64_t)e->tokens[j]);}
        jsonw_raw(w,e->reasoning?"],\"reasoning\":true": "],\"reasoning\":false");jsonw_raw(w,e->step_clock?",\"step_clock\":true":",\"step_clock\":false");field_ms(w,",\"at_ms\":",e->at_ms);field_str(w,",\"model_raw\":",e->model_raw);jsonw_raw(w,",\"model_number\":");if(e->has_model_number)jsonw_i64(w,e->model_number);else jsonw_raw(w,"null");jsonw_raw(w,",\"ids\":[");bool comma=false;
        for(size_t j=0;j<3;j++)if(e->ids[j].n){if(comma)jsonw_raw(w,",");comma=true;jsonw_raw(w,"[");jsonw_i64(w,fields[j]);jsonw_raw(w,",\"");for(size_t k=0;k<e->ids[j].n;k++){unsigned char c=(unsigned char)e->ids[j].p[k];char pair[2]={hex[c>>4],hex[c&15]};jsonw_bytes(w,pair,2);}jsonw_raw(w,"\"]");}jsonw_raw(w,"]}");
    }jsonw_raw(w,"]}");
}
Err antigravity_ledger_commit(AntigravityLedger *l,const AntigravityStore *store,const Corpus *corpus,volatile sig_atomic_t *interrupted){
    (void)corpus;if(!l->directory)return ERR_SUCCESS;
    for(size_t i=0;i<l->count;i++){AntigravityLedgerRecord *r=l->records[i];if(!r->live||r->unreadable)continue;if(interrupted&&*interrupted)return err_make(ERR_IO,"interrupted");
        JsonWriter w={0};encode(&w,r,store->home);Err e=w.error;if(!e.code&&(r->original.n!=w.length||memcmp(r->original.p,w.data,w.length))){e=file_mkdir_parents(l->directory);char *path=NULL;if(!e.code){char *parent=strdup(l->directory);if(!parent)e=err_make(ERR_NOMEM,"ledger path allocation failed");else{char *slash=strrchr(parent,'/');if(!slash)e=err_make(ERR_INVALID,"invalid ledger directory");else{*slash=0;if(chmod(parent,0700)||chmod(l->directory,0700))e=err_make(ERR_IO,"ledger directory chmod failed");}free(parent);}}
            if(!e.code){size_t n=r->header.id.n+6;char *name=malloc(n);if(!name)e=err_make(ERR_NOMEM,"ledger filename allocation failed");else{snprintf(name,n,"%.*s.json",(int)r->header.id.n,r->header.id.p);path=join(l->directory,name);free(name);if(!path)e=err_make(ERR_NOMEM,"ledger path allocation failed");}}
            if(!e.code)e=atomic_write(path,w.data,w.length);free(path);
        }jsonw_free(&w);if(e.code)return e;
    }return ERR_SUCCESS;
}
void antigravity_ledger_destroy(AntigravityLedger *l){omap_destroy(&l->by_id);arena_destroy(&l->arena);free(l->directory);*l=(AntigravityLedger){0};}
