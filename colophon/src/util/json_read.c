#define _DARWIN_C_SOURCE
#include "json_read.h"
#include "json_number.h"
#include "omap.h"
#include "events.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

JsonStatus wtf8_validate(Str s,JsonMode mode,JsonStats *stats) {
    const unsigned char *p=(const unsigned char*)s.p;
    if(mode==BYTES&&s.n>=2&&((p[0]==0xff&&p[1]==0xfe)||(p[0]==0xfe&&p[1]==0xff)||p[0]==0||p[1]==0))return JSON_T2_ENCODING;
    if(s.n>=3&&!memcmp(s.p,"\xef\xbb\xbf",3)){stats->bom++;if(mode!=BYTES)return JSON_INVALID;}
    size_t offset=0;uint32_t cp;
    while(offset<s.n){if(!str_decode_next(s,&offset,&cp)){stats->invalid_unicode++;return JSON_INVALID;}
        if(cp>=0xd800&&cp<=0xdfff){stats->raw_surrogates++;if(mode==STRICT){stats->invalid_unicode++;return JSON_INVALID;}}}
    return JSON_OK;
}
yyjson_val *obj_get_last(yyjson_val *o,Str key) {
    yyjson_val *answer=NULL,*k;yyjson_obj_iter it=yyjson_obj_iter_with(o);
    while((k=yyjson_obj_iter_next(&it)))if(str_equal(key,(Str){yyjson_get_str(k),(uint32_t)yyjson_get_len(k)}))answer=yyjson_obj_iter_get_val(k);
    return answer;
}
yyjson_val *obj_get_first_typed(yyjson_val *o,Str key,yyjson_type type) {
    yyjson_val *k;yyjson_obj_iter it=yyjson_obj_iter_with(o);
    while((k=yyjson_obj_iter_next(&it))){yyjson_val *v=yyjson_obj_iter_get_val(k);if(yyjson_get_type(v)==type&&str_equal(key,(Str){yyjson_get_str(k),(uint32_t)yyjson_get_len(k)}))return v;}
    return NULL;
}
typedef struct { yyjson_val *v; size_t depth; } Node;
typedef struct { Node *p;size_t n,cap; } Stack;
static bool push(Stack *s,Node node) {
    if(s->n==s->cap){size_t cap=s->cap?s->cap*2:64;if(cap<s->cap||cap>SIZE_MAX/sizeof(Node))return false;Node *p=realloc(s->p,cap*sizeof(Node));if(!p)return false;s->p=p;s->cap=cap;}
    s->p[s->n++]=node;return true;
}
static unsigned escape(Str s,size_t i) {
    if(i+6>s.n||s.p[i]!='\\'||s.p[i+1]!='u')return 0;unsigned cp=0;
    for(size_t j=2;j<6;j++){char c=s.p[i+j];unsigned h;if(c>='0'&&c<='9')h=(unsigned)(c-'0');else if(c>='a'&&c<='f')h=(unsigned)(c-'a'+10);else if(c>='A'&&c<='F')h=(unsigned)(c-'A'+10);else return 0;cp=cp*16+h;}return cp;
}
typedef struct { size_t *positions;unsigned *units;size_t n,cap;unsigned sentinel; } Surrogates;
static JsonStatus prepare(Str input,char **prepared,Surrogates *sur,JsonStats *stats) {
    if(!memmem(input.p,input.n,"\\ud",3)&&!memmem(input.p,input.n,"\\uD",3))return JSON_OK;
    uint32_t present=0;bool inside=false;
    for(size_t i=0;i<input.n;i++){
        if(input.p[i]=='"'){inside=!inside;continue;}
        if(!inside)continue;
        if(input.p[i]=='\\'){
            unsigned cp=escape(input,i);
            if(cp>=0xfdd0&&cp<=0xfdef)present|=UINT32_C(1)<<(cp-0xfdd0);
            if(cp>=0xd800&&cp<=0xdbff){unsigned low=escape(input,i+6);if(low>=0xdc00&&low<=0xdfff){i+=11;continue;}}
            if(cp>=0xd800&&cp<=0xdfff){
                if(sur->n==sur->cap){size_t cap=sur->cap?sur->cap*2:8;size_t *positions=realloc(sur->positions,cap*sizeof(size_t));if(!positions)return JSON_NOMEM;sur->positions=positions;unsigned *units=realloc(sur->units,cap*sizeof(unsigned));if(!units)return JSON_NOMEM;sur->units=units;sur->cap=cap;}
                sur->positions[sur->n]=i;sur->units[sur->n++]=cp;
            }
            i+=cp?5:1;
        }else if((unsigned char)input.p[i]>=128){size_t end=i;uint32_t cp;if(!str_decode_next(input,&end,&cp))return JSON_INVALID;if(cp>=0xfdd0&&cp<=0xfdef)present|=UINT32_C(1)<<(cp-0xfdd0);i=end-1;}
    }
    stats->lone_surrogates=sur->n;if(!sur->n)return JSON_OK;
    for(unsigned i=0;i<32;i++)if(!(present&(UINT32_C(1)<<i))){sur->sentinel=0xfdd0+i;break;}
    if(!sur->sentinel)return JSON_T2_SENTINEL;
    *prepared=malloc((size_t)input.n+1);if(!*prepared)return JSON_NOMEM;memcpy(*prepared,input.p,input.n);(*prepared)[input.n]=0;
    char replacement[7];snprintf(replacement,sizeof(replacement),"\\u%04x",sur->sentinel);
    for(size_t i=0;i<sur->n;i++)memcpy(*prepared+sur->positions[i],replacement,6);
    return JSON_OK;
}
static JsonStatus walk(yyjson_doc *doc,size_t max_depth,JsonConstants constants,JsonStats *stats,Surrogates *sur) {
    Stack stack={0};JsonStatus status=JSON_OK;size_t restored=0;
    if(!push(&stack,(Node){yyjson_doc_get_root(doc),0}))return JSON_NOMEM;
    while(stack.n){Node node=stack.p[--stack.n];yyjson_val *v=node.v;
        if(yyjson_is_ctn(v)){
            if(node.depth>=max_depth){status=JSON_T2_NEST;break;}
            size_t begin=stack.n;
            if(yyjson_is_obj(v)){yyjson_obj_iter it=yyjson_obj_iter_with(v);yyjson_val *k;while((k=yyjson_obj_iter_next(&it))){if(!push(&stack,(Node){k,node.depth+1})||!push(&stack,(Node){yyjson_obj_iter_get_val(k),node.depth+1})){status=JSON_NOMEM;break;}}}
            else{yyjson_arr_iter it=yyjson_arr_iter_with(v);yyjson_val *child;while((child=yyjson_arr_iter_next(&it)))if(!push(&stack,(Node){child,node.depth+1})){status=JSON_NOMEM;break;}}
            if(status!=JSON_OK)break;
            for(size_t a=begin,b=stack.n;a<b&&a<--b;a++){Node tmp=stack.p[a];stack.p[a]=stack.p[b];stack.p[b]=tmp;}
        }else if(stats&&yyjson_is_raw(v)){
            Str raw={yyjson_get_raw(v),(uint32_t)yyjson_get_len(v)};
            if(json_number_is_integer(raw)){if(raw.n-(raw.p[0]=='-')>4300){stats->integer_digit_limit++;status=JSON_INVALID;}}
            else if(str_equal(raw,STR_LIT("NaN"))||str_equal(raw,STR_LIT("Infinity"))||str_equal(raw,STR_LIT("-Infinity"))){if(!stats->first_constant)stats->first_constant=str_equal(raw,STR_LIT("NaN"))?1:str_equal(raw,STR_LIT("Infinity"))?2:3;stats->nonfinite++;if(constants==JSON_CONSTANTS_REJECT)status=JSON_INVALID;}
            else if(raw.n&&(strchr("nNiI",raw.p[0])||(raw.p[0]=='-'&&raw.n>1&&strchr("nNiI",raw.p[1])))){stats->invalid_number_spellings++;status=JSON_INVALID;}
        }else if(sur&&sur->n&&yyjson_is_str(v)){
            char sentinel[4];size_t width=str_encode_codepoint(sur->sentinel,sentinel);char *s=(char*)yyjson_get_str(v);size_t n=yyjson_get_len(v);
            for(size_t i=0;i+width<=n;i++)if(!memcmp(s+i,sentinel,width)){if(restored==sur->n){status=JSON_INVALID;break;}str_encode_codepoint(sur->units[restored++],s+i);i+=width-1;}
        }
    }
    free(stack.p);if(status==JSON_OK&&sur&&restored!=sur->n)return JSON_INVALID;return status;
}
JsonStatus json_doc_check(yyjson_doc *doc,size_t max_depth,JsonConstants constants,JsonStats *stats){return walk(doc,max_depth,constants,stats,NULL);}
JsonStatus json_depth_check(yyjson_doc *doc,size_t max_depth){return walk(doc,max_depth,JSON_CONSTANTS_ALLOW,NULL,NULL);}
JsonRead json_read(Str input,JsonMode mode,JsonConstants constants,const char *site) {
    JsonRead read={0};read.status=wtf8_validate(input,mode,&read.stats);char *prepared=NULL;Surrogates sur={0};
    if(read.status==JSON_OK)read.status=prepare(input,&prepared,&sur,&read.stats);
    if(read.status==JSON_OK){yyjson_read_flag flags=YYJSON_READ_NUMBER_AS_RAW|YYJSON_READ_ALLOW_INF_AND_NAN|YYJSON_READ_ALLOW_INVALID_UNICODE;if(mode==BYTES)flags|=YYJSON_READ_ALLOW_BOM;
        yyjson_read_err error={0};read.doc=yyjson_read_opts(prepared?prepared:(char*)input.p,input.n,flags,NULL,&error);
        if(!read.doc)read.status=error.code==YYJSON_READ_ERROR_MEMORY_ALLOCATION?JSON_NOMEM:JSON_INVALID;
        else read.status=walk(read.doc,10000,constants,&read.stats,&sur);}
    free(prepared);free(sur.positions);free(sur.units);
    if(read.status==JSON_T2_ENCODING)event_note("tier2_encoding",site,1);
    else if(read.status==JSON_T2_NEST)event_note("tier2_nest",site,1);
    else if(read.status==JSON_T2_SENTINEL)event_note("json_sentinel_exhausted",site,1);
    if(read.status==JSON_OK){if(read.stats.lone_surrogates)event_note("lone_surrogate_escape",site,read.stats.lone_surrogates);if(read.stats.bom||read.stats.nonfinite)event_note("json_nonstandard",site,read.stats.bom+read.stats.nonfinite);}
    else{yyjson_doc_free(read.doc);read.doc=NULL;}return read;
}
void json_read_free(JsonRead *read){yyjson_doc_free(read->doc);read->doc=NULL;}

typedef struct { yyjson_val *source;yyjson_mut_val *parent;Str key;bool object; } CopyNode;
Err json_object_dict(yyjson_val *object,Omap *out) {
    if(!yyjson_is_obj(object))return err_make(ERR_INVALID,"expected JSON object");
    yyjson_obj_iter it=yyjson_obj_iter_with(object);yyjson_val *key;
    while((key=yyjson_obj_iter_next(&it))){Err error=omap_put(out,(Str){yyjson_get_str(key),(uint32_t)yyjson_get_len(key)},yyjson_obj_iter_get_val(key));if(error.code!=ERR_OK){omap_destroy(out);return error;}}
    return ERR_SUCCESS;
}
Err json_load_dict_semantics(yyjson_doc *source,yyjson_mut_doc **out) {
    if(json_depth_check(source,10000)!=JSON_OK)return err_make(ERR_INVALID,"invalid JSON depth");
    yyjson_mut_doc *doc=yyjson_mut_doc_new(NULL);size_t n=1,cap=64;CopyNode *stack=malloc(cap*sizeof(*stack));
    if(!doc||!stack){yyjson_mut_doc_free(doc);free(stack);return err_make(ERR_NOMEM,"JSON copy allocation");}
    stack[0]=(CopyNode){yyjson_doc_get_root(source),NULL,{0},false};bool ok=true;
    while(n&&ok){CopyNode node=stack[--n];yyjson_val *v=node.source;yyjson_mut_val *copy=NULL;
        if(yyjson_is_obj(v))copy=yyjson_mut_obj(doc);else if(yyjson_is_arr(v))copy=yyjson_mut_arr(doc);
        else if(yyjson_is_str(v))copy=yyjson_mut_strncpy(doc,yyjson_get_str(v),yyjson_get_len(v));
        else if(yyjson_is_raw(v))copy=yyjson_mut_rawncpy(doc,yyjson_get_raw(v),yyjson_get_len(v));
        else if(yyjson_is_bool(v))copy=yyjson_mut_bool(doc,yyjson_get_bool(v));else if(yyjson_is_null(v))copy=yyjson_mut_null(doc);
        else if(yyjson_is_sint(v))copy=yyjson_mut_sint(doc,yyjson_get_sint(v));else if(yyjson_is_uint(v))copy=yyjson_mut_uint(doc,yyjson_get_uint(v));else if(yyjson_is_real(v))copy=yyjson_mut_real(doc,yyjson_get_real(v));
        if(!copy){ok=false;break;}
        if(!node.parent)yyjson_mut_doc_set_root(doc,copy);else if(node.object){yyjson_mut_val *key=yyjson_mut_strncpy(doc,node.key.p,node.key.n);ok=key&&yyjson_mut_obj_add(node.parent,key,copy);}else ok=yyjson_mut_arr_append(node.parent,copy);
        size_t needed=yyjson_get_len(v);if(!yyjson_is_ctn(v))continue;
        if(needed>SIZE_MAX-n){ok=false;break;}
        if(n+needed>cap){size_t next=cap;while(next<n+needed&&next<=SIZE_MAX/2)next*=2;if(next<n+needed||next>SIZE_MAX/sizeof(*stack)){ok=false;break;}CopyNode *p=realloc(stack,next*sizeof(*stack));if(!p){ok=false;break;}stack=p;cap=next;}
        size_t begin=n;
        if(yyjson_is_obj(v)){Omap map={0};if(json_object_dict(v,&map).code!=ERR_OK)ok=false;
            for(OmapEntry *e=map.first;e;e=e->next){/* Key bytes must outlive the transient map. */
                yyjson_mut_val *key=yyjson_mut_strncpy(doc,e->key.p,e->key.n);if(!key){ok=false;break;}
                stack[n++]=(CopyNode){e->value,copy,{yyjson_mut_get_str(key),e->key.n},true};}
            omap_destroy(&map);
        }else{yyjson_arr_iter it=yyjson_arr_iter_with(v);yyjson_val *child;while((child=yyjson_arr_iter_next(&it)))stack[n++]=(CopyNode){child,copy,{0},false};}
        for(size_t a=begin,b=n;a<b&&a<--b;a++){CopyNode tmp=stack[a];stack[a]=stack[b];stack[b]=tmp;}
    }
    free(stack);if(!ok){yyjson_mut_doc_free(doc);return err_make(ERR_NOMEM,"JSON copy allocation");}*out=doc;return ERR_SUCCESS;
}
typedef struct { yyjson_mut_val *next; size_t left, start; } FreezeFrame;
static bool freeze_walk(yyjson_mut_val *root, yyjson_val *values, char *strings,
                        size_t *value_count, size_t *string_count) {
    FreezeFrame *frames=NULL; size_t depth=0,capacity=0, count=0, bytes=0;
    yyjson_mut_val *current=root; bool ok=true;
    for (;;) {
        if (current) {
            if (count==SIZE_MAX) {ok=false;break;}
            size_t index=count++;
            if(values) {values[index].tag=current->tag;values[index].uni=current->uni;}
            if(yyjson_mut_is_str(current)||yyjson_mut_is_raw(current)) {
                size_t length=yyjson_mut_get_len(current);
                if(length==SIZE_MAX || bytes>SIZE_MAX-length-1) {ok=false;break;}
                if(values) {
                    const char *source=yyjson_mut_is_str(current)?yyjson_mut_get_str(current):yyjson_mut_get_raw(current);
                    memcpy(strings+bytes,source,length);strings[bytes+length]=0;
                    values[index].uni.str=strings+bytes;
                }
                bytes+=length+1;
            }
            if(yyjson_mut_is_ctn(current)) {
                size_t children=yyjson_mut_get_len(current);
                bool object=yyjson_mut_is_obj(current);
                if(object) {if(children>SIZE_MAX/2){ok=false;break;}children*=2;}
                if(depth==capacity) {
                    size_t next=capacity?capacity*2:32;
                    if(next<capacity || next>SIZE_MAX/sizeof *frames){ok=false;break;}
                    FreezeFrame *grown=realloc(frames,next*sizeof *frames);
                    if(!grown){ok=false;break;}frames=grown;capacity=next;
                }
                yyjson_mut_val *first=NULL;
                if(children) {
                    yyjson_mut_val *last=current->uni.ptr;
                    first=object?last->next->next:last->next;
                }
                frames[depth++]=(FreezeFrame){first,children,index};
            }
        }
        current=NULL;
        while(depth) {
            FreezeFrame *frame=&frames[depth-1];
            if(frame->left) {
                current=frame->next;frame->next=current->next;frame->left--;break;
            }
            if(values) {
                size_t width=count-frame->start;
                if(width>SIZE_MAX/sizeof *values){ok=false;break;}
                values[frame->start].uni.ofs=width*sizeof *values;
            }
            depth--;
        }
        if(!ok || (!current&&!depth))break;
    }
    free(frames);*value_count=count;*string_count=bytes;return ok;
}
Err json_freeze(yyjson_mut_doc *source,yyjson_doc **out) {
    _Static_assert(sizeof(yyjson_val)==16,"pinned yyjson contiguous value width");
    _Static_assert(_Alignof(yyjson_val)<=16,"pinned yyjson value alignment");
    *out=NULL;
    if(!source||!source->root)return err_make(ERR_INVALID,"missing JSON root");
    size_t count=0,strings=0;
    if(!freeze_walk(source->root,NULL,NULL,&count,&strings))goto fail;
    /* Pinned yyjson allocators provide malloc alignment. Match vendor's
     * sizeof(value) header rounding, without assuming max_align_t is 16. */
    size_t alignment=sizeof(yyjson_val),header=sizeof(yyjson_doc);
    if(header>SIZE_MAX-(alignment-1))goto fail;
    header=(header+alignment-1)&~(alignment-1);
    if(count>(SIZE_MAX-header)/sizeof(yyjson_val)||strings==SIZE_MAX)goto fail;
    /* Default allocator is private in pinned yyjson.c. Acquire its callbacks
     * through the public constructor; result never borrows source context. */
    yyjson_mut_doc *default_owner=yyjson_mut_doc_new(NULL);
    if(!default_owner)goto fail;
    yyjson_alc allocator=default_owner->alc;
    yyjson_mut_doc_free(default_owner);
    yyjson_doc *doc=allocator.malloc(allocator.ctx,header+count*sizeof(yyjson_val));
    if(!doc)goto fail;
    memset(doc,0,sizeof *doc);doc->alc=allocator;
    doc->root=(yyjson_val *)((char *)doc+header);
    if(strings) {
        doc->str_pool=allocator.malloc(allocator.ctx,strings);
        if(!doc->str_pool){yyjson_doc_free(doc);goto fail;}
    }
    size_t copied=0,string_copied=0;
    if(!freeze_walk(source->root,doc->root,doc->str_pool,&copied,&string_copied)) {
        yyjson_doc_free(doc);goto fail;
    }
    doc->val_read=copied;doc->dat_read=string_copied+1;*out=doc;return ERR_SUCCESS;
fail:
    return err_make(ERR_NOMEM,"JSON freeze allocation or size overflow");
}
