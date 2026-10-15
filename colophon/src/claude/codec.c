#include "codec.h"
#include "out/jsonw.h"
#include "util/sha256.h"
#include <math.h>
#include <stdalign.h>
#include <stdlib.h>
#include <string.h>

/* One ordered traversal defines encoder and decoder, as in cache/codec.c.
 * An independent JSON-array wire preserves integer widths and nullable strings;
 * no pointer, struct padding, borrowed arena or composed pricing is persisted.
 * CLCD1 + SHA-256 protects the complete immutable version-1 body. */
typedef struct {
  bool reading, first;
  yyjson_val *array;
  size_t position;
  JsonWriter json;
  Arena *arena;
  Err error;
} Wire;
static void invalid(Wire *w) {
  if (!w->error.code) w->error=err_make(ERR_INVALID,"invalid Claude codec record");
}
static yyjson_val *next(Wire *w) {
  yyjson_val *v=yyjson_arr_get(w->array,w->position++);
  if(!v)invalid(w);
  return v;
}
static void separator(Wire *w) {
  if(!w->first)jsonw_raw(&w->json,",");
  w->first=false;
}
static void unsigned_integer(Wire *w,uint64_t *n) {
  if(w->error.code)return;
  if(w->reading){yyjson_val *v=next(w);if(!yyjson_is_uint(v))invalid(w);else *n=yyjson_get_uint(v);}
  else {separator(w);jsonw_i128(&w->json,*n);}
}
static void sint(Wire *w,int64_t *n) {
  if(w->error.code)return;
  if(w->reading){yyjson_val *v=next(w);if(!yyjson_is_int(v)||(yyjson_is_uint(v)&&yyjson_get_uint(v)>INT64_MAX))invalid(w);else *n=yyjson_get_sint(v);}
  else {separator(w);jsonw_i64(&w->json,*n);}
}
static void wide(Wire *w,__int128 *n) {
  unsigned __int128 bits;memcpy(&bits,n,sizeof bits);
  uint64_t lo=(uint64_t)bits,hi=(uint64_t)(bits>>64);
  unsigned_integer(w,&lo);unsigned_integer(w,&hi);
  if(w->reading){bits=((unsigned __int128)hi<<64)|lo;memcpy(n,&bits,sizeof bits);}
}
static void boolean(Wire *w,bool *b) {
  if(w->error.code)return;
  if(w->reading){yyjson_val *v=next(w);if(!yyjson_is_bool(v))invalid(w);else *b=yyjson_is_true(v);}
  else {separator(w);jsonw_raw(&w->json,*b?"true":"false");}
}
static void string(Wire *w,Str *s) {
  if(w->error.code)return;
  if(w->reading){yyjson_val *v=next(w);if(yyjson_is_null(v))*s=(Str){0};else if(!yyjson_is_str(v)||yyjson_get_len(v)>UINT32_MAX)invalid(w);else w->error=str_copy(w->arena,(Str){yyjson_get_str(v),(uint32_t)yyjson_get_len(v)},s);}
  else {separator(w);if(s->p)jsonw_string(&w->json,*s);else jsonw_raw(&w->json,"null");}
}
static void real(Wire *w,double *n) {
  if(w->error.code)return;
  if(w->reading){yyjson_val *v=next(w);if(!yyjson_is_num(v))invalid(w);else *n=yyjson_get_num(v);}
  else {separator(w);jsonw_double(&w->json,*n);}
}
static void ms(Wire *w,MaybeMs *m){boolean(w,&m->present);if(m->present)sint(w,&m->value);}
static void num(Wire *w,MaybeNum *m){boolean(w,&m->present);if(m->present){boolean(w,&m->value.is_float);if(m->value.is_float)real(w,&m->value.f);else sint(w,&m->value.i);}}
static void scalar(Wire *w,JScalar *s){
  uint64_t kind=s->kind;unsigned_integer(w,&kind);if(kind>JS_OBJECT){invalid(w);return;}s->kind=(JKind)kind;
  boolean(w,&s->empty);
  switch(s->kind){case JS_BOOL:boolean(w,&s->value.b);break;case JS_INT:sint(w,&s->value.i);break;case JS_FLOAT:real(w,&s->value.f);break;case JS_STRING:string(w,&s->value.s);break;default:break;}
}
static void count(Wire *w,size_t *n){uint64_t value=*n;unsigned_integer(w,&value);if(value>SIZE_MAX||(w->reading&&value>yyjson_arr_size(w->array)-w->position)){invalid(w);return;}*n=(size_t)value;}
/* Apple ARM64 max_align_t is only 8; all decoded types are at most 16.
 * Wide tool counters and UsageUnit need their actual 128-bit alignment. */
_Static_assert(alignof(CorpusTools)<=alignof(__int128), "CorpusTools alignment");
_Static_assert(alignof(ClaudeUsageRow)<=alignof(__int128), "ClaudeUsageRow alignment");
_Static_assert(alignof(UsageUnit)<=alignof(__int128), "UsageUnit alignment");
_Static_assert(alignof(TurnFact)<=alignof(__int128), "TurnFact alignment");
_Static_assert(alignof(Request)<=alignof(__int128), "Request alignment");
_Static_assert(alignof(Str)<=alignof(__int128), "Str alignment");
static void allocate(Wire *w,void **p,size_t n,size_t element){
  if(!w->reading||w->error.code||!n)return;
  if(n>SIZE_MAX/element){invalid(w);return;}
  w->error=arena_alloc(w->arena,n*element,alignof(__int128),p);
  if(!w->error.code)memset(*p,0,n*element);
}
/* Unknown-type values are reader-owned heap values; all other map values are
 * record-arena values. Map nodes/keys retain their usual Omap ownership. */
static void map(Wire *w,Omap *m,int kind){
  size_t n=m->size;count(w,&n);OmapEntry *entry=m->first;
  for(size_t i=0;i<n&&!w->error.code;i++){
    Str key=w->reading?(Str){0}:entry->key;string(w,&key);
    void *value=w->reading?NULL:entry->value;
    size_t bytes=kind==2?sizeof(__int128):kind==3?sizeof(Str):sizeof(uint64_t);
    if(w->reading&&!w->error.code){
      if(!key.p||omap_get(m,key)){invalid(w);break;}
      if(kind==1){value=calloc(1,bytes);if(!value)w->error=err_make(ERR_NOMEM,"Claude codec allocation failed");}
      else allocate(w,&value,1,bytes);
      if(w->error.code)break;
      w->error=omap_put(m,key,value);if(w->error.code){if(kind==1)free(value);break;}
    }
    if(kind==2)wide(w,value);else if(kind==3)string(w,value);else unsigned_integer(w,value);
    if(!w->reading)entry=entry->next;
  }
}
#define S(v) string(w,&(v))
#define B(v) boolean(w,&(v))
#define I(v) sint(w,&(v))
#define U(v) unsigned_integer(w,&(v))
#define W(v) wide(w,&(v))
#define M(v) ms(w,&(v))
#define N(v) num(w,&(v))
#define J(v) scalar(w,&(v))
static void record_v1(Wire *w,ClaudeRecord *r){
  S(r->key.path);I(r->key.size);I(r->key.mtime_ns);B(r->key.archived);B(r->key.stat_ok);
  uint64_t dev=r->key.device,ino=r->key.inode;U(dev);U(ino);r->key.device=(dev_t)dev;r->key.inode=(ino_t)ino;
  S(r->id);S(r->search_root);S(r->config_dir);S(r->parent_session);
  S(r->parent_agent);S(r->tool_use_id);S(r->description);S(r->agent_type);S(r->custom_title);S(r->ai_title);
  B(r->has_spawn_depth);I(r->spawn_depth);map(w,&r->tool_turns,3);
  SessionMeta *m=&r->meta;S(m->id);S(m->request_session_id);S(m->forked_from_id);M(m->created_at_ms);B(m->is_subagent);
  J(m->timestamp_raw);J(m->cwd);J(m->originator);J(m->cli_version);J(m->parent_thread_id);J(m->depth);J(m->agent_path);J(m->agent_nickname);J(m->agent_role);J(m->branch);J(m->origin_url);J(m->sha);J(m->rollout_title);
  count(w,&r->aliases.count);allocate(w,(void **)&r->aliases.items,r->aliases.count,sizeof(Str));
  for(size_t i=0;i<r->aliases.count&&!w->error.code;i++)S(r->aliases.items[i]);
  if(w->reading)r->aliases.capacity=r->aliases.count;
  ReaderResult *d=&r->reader;U(d->malformed);U(d->recovered);U(d->physical_lines);U(d->decoded_records);B(d->partial_final_line);
  Str tail={d->tail_sha256,64};S(tail);if(w->reading&&!w->error.code){if(!tail.p||tail.n!=64)invalid(w);else {memcpy(d->tail_sha256,tail.p,64);d->tail_sha256[64]=0;}}
  map(w,&d->unknown_types,1);M(r->first_ms);M(r->last_ms);
  count(w,&r->turn_count);
  allocate(w,(void **)&r->turns,r->turn_count,sizeof *r->turns);allocate(w,(void **)&r->requests,r->turn_count,sizeof *r->requests);allocate(w,(void **)&r->answers,r->turn_count,sizeof *r->answers);allocate(w,(void **)&r->tools,r->turn_count,sizeof *r->tools);
  for(size_t i=0;i<r->turn_count&&!w->error.code;i++){
    allocate(w,(void **)&r->turns[i],1,sizeof(TurnFact));if(w->error.code)break;
    TurnFact *t=r->turns[i];S(t->key);S(t->turn_id);S(t->start_src);S(t->end_src);S(t->end_kind);M(t->start_ms);M(t->end_ms);M(t->last_ms);N(t->reported_ms);N(t->ttft_ms);B(t->has_start_rec);U(t->start_rec);
    Request *q=&r->requests[i];M(q->at_ms);S(q->text);S(q->kind);U(q->images);B(q->before_turn);B(q->time_unreliable);S(r->answers[i]);
    CorpusTools *tools=&r->tools[i];W(tools->shell);W(tools->shell_failed);W(tools->file_edits);W(tools->web);W(tools->image);map(w,&tools->mcp,2);map(w,&tools->other,2);
  }
  count(w,&r->usage_count);allocate(w,(void **)&r->usage_rows,r->usage_count,sizeof *r->usage_rows);
  for(size_t i=0;i<r->usage_count&&!w->error.code;i++){
    ClaudeUsageRow *row=&r->usage_rows[i];S(row->message_id);S(row->request_id);S(row->session_id);B(row->incomplete);B(row->sidechain);B(row->subagent);
    UsageUnit *u=&row->unit;S(u->session_id);S(u->turn_id);S(u->display_turn);S(u->model_raw);S(u->model);S(u->source);count(w,&u->file);U(u->line);M(u->at_ms);M(u->timestamp_ms);
    W(u->input);W(u->cached);W(u->cache_write);W(u->cache_write_1h);W(u->output);B(u->fast);B(u->reasoning.present);W(u->reasoning.value);
    B(u->claude_price_snapshot);B(u->claude_cost_priced);I(u->claude_cost_nanos);
  }
  if(w->reading)r->usage_capacity=r->usage_count;map(w,&r->rows_dropped,0);
}
Err claude_codec_encode(const ClaudeRecord *record,unsigned char **out,size_t *length){
  *out=NULL;*length=0;Wire w={.first=true,.arena=(Arena *)&record->arena};
  jsonw_raw(&w.json,"[");record_v1(&w,(ClaudeRecord *)record);jsonw_raw(&w.json,"]");
  Err e=w.error.code?w.error:w.json.error;
  if(!e.code){
    if(w.json.length>SIZE_MAX-71)e=err_make(ERR_NOMEM,"Claude codec too large");
    else {*out=malloc(w.json.length+71);if(!*out)e=err_make(ERR_NOMEM,"Claude codec allocation failed");}
    if(!e.code){memcpy(*out,"CLCD1\n",6);sha256_hex(w.json.data,w.json.length,(char *)*out+6);(*out)[70]='\n';memcpy(*out+71,w.json.data,w.json.length);*length=w.json.length+71;}
  }
  jsonw_free(&w.json);return e;
}
Err claude_codec_decode(const void *bytes,size_t length,ClaudeRecord *out){
  *out=(ClaudeRecord){0};const unsigned char *data=bytes;
  if(length<73||memcmp(data,"CLCD1\n",6)||data[70]!='\n')return err_make(ERR_INVALID,"invalid Claude codec version");
  char digest[65];sha256_hex(data+71,length-71,digest);
  if(memcmp(digest,data+6,64))return err_make(ERR_INVALID,"invalid Claude codec checksum");
  yyjson_doc *doc=yyjson_read((const char *)data+71,length-71,0);
  if(!doc)return err_make(ERR_INVALID,"invalid Claude codec JSON");
  Wire w={.reading=true,.array=yyjson_doc_get_root(doc),.arena=&out->arena};
  if(!yyjson_is_arr(w.array))invalid(&w);else record_v1(&w,out);
  if(!w.error.code&&(w.position!=yyjson_arr_size(w.array)||!out->key.path.p||!out->id.p||!out->search_root.p))invalid(&w);
  yyjson_doc_free(doc);if(w.error.code)claude_record_destroy(out);return w.error;
}
