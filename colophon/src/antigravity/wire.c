#include "wire.h"
#include <string.h>
#include <stdlib.h>
static bool varint(Str s,size_t *offset,uint64_t *value){
    uint64_t n=0;
    for(unsigned i=0;i<10;i++){
        if(*offset>=s.n)return false;unsigned char b=(unsigned char)s.p[(*offset)++];
        if(i==9&&b>1)return false;
        n|=(uint64_t)(b&127)<<(7*i);
        if(!(b&128)){if(i&&!(b&127))return false;*value=n;return true;}
    }
    return false;
}
AgResult ag_wire_next(AgCursor *c,AgField *f){
    *f=(AgField){0};
    if(c->input.n>AG_WIRE_MAX_BYTES||c->offset>c->input.n)return AG_MALFORMED;
    if(c->offset==c->input.n)return AG_ABSENT;
    f->position=c->input.p+c->offset;
    if(++c->fields>AG_WIRE_MAX_FIELDS)return AG_MALFORMED;
    uint64_t tag=0,length=0;
    if(!varint(c->input,&c->offset,&tag)||!(tag>>3)||(tag>>3)>0x1fffffff)return AG_MALFORMED;
    f->number=(uint32_t)(tag>>3);f->wire=tag&7;
    if(!f->wire)return varint(c->input,&c->offset,&f->integer)?AG_FOUND:AG_MALFORMED;
    if(f->wire==1)length=8;else if(f->wire==5)length=4;
    else if(f->wire==2){if(!varint(c->input,&c->offset,&length))return AG_MALFORMED;}
    else return AG_MALFORMED;
    if(length>c->input.n-c->offset)return AG_MALFORMED;
    f->bytes=(Str){c->input.p+c->offset,(uint32_t)length};c->offset+=(size_t)length;
    return AG_FOUND;
}
AgResult ag_wire_last(Str input,uint32_t number,AgField *out){
    AgCursor c={.input=input};AgField f={0};AgResult result,found=AG_ABSENT;*out=f;
    while((result=ag_wire_next(&c,&f))==AG_FOUND)if(f.number==number){*out=f;found=AG_FOUND;}
    return result==AG_MALFORMED?result:found;
}
AgResult ag_wire_integer_next(AgCursor *c,uint32_t number,uint64_t *value){
    for(;;){
        if(c->packed_offset<c->packed.n)return varint(c->packed,&c->packed_offset,value)?AG_FOUND:AG_MALFORMED;
        AgField f;AgResult r=ag_wire_next(c,&f);if(r!=AG_FOUND)return r;
        if(f.number!=number)continue;
        if(!f.wire){*value=f.integer;return AG_FOUND;}
        if(f.wire!=2)return AG_MALFORMED;c->packed=f.bytes;c->packed_offset=0;
    }
}
AgResult ag_wire_validate(Str input){AgCursor c={.input=input};AgField f;AgResult r;while((r=ag_wire_next(&c,&f))==AG_FOUND){}return r==AG_MALFORMED?r:AG_FOUND;}
void ag_wire_mismatch(AgMismatches *m,AgMessageType type,uint32_t number,const char *position){
    if(!m||m->error.code)return;
    for(size_t i=m->range_count;i>0;i--){AgWireRange *r=&m->ranges[i-1];uintptr_t p=(uintptr_t)position,b=(uintptr_t)r->copy;if(p>=b&&p-b<r->length)position=r->source+(p-b);}
    struct {const char *position;uint32_t type,number;} key={0};key.position=position;key.type=(uint32_t)type;key.number=number;
    Str k={(const char *)&key,sizeof key};if(omap_get(&m->seen,k))return;
    m->error=omap_put(&m->seen,k,(void *)1);
    if(!m->error.code&&(unsigned)type<20&&number<256)m->counts[type][number]++;
}
void ag_wire_copy_range(AgMismatches *m,const char *copy,const char *source,size_t length){
    if(!m||!length||m->error.code)return;
    if(m->range_count==m->range_capacity){size_t cap=m->range_capacity?m->range_capacity*2:32;if(cap<m->range_capacity||cap>SIZE_MAX/sizeof *m->ranges){m->error=err_make(ERR_NOMEM,"Antigravity wire range overflow");return;}void *p=realloc(m->ranges,cap*sizeof *m->ranges);if(!p){m->error=err_make(ERR_NOMEM,"Antigravity wire range allocation failed");return;}m->ranges=p;m->range_capacity=cap;}
    m->ranges[m->range_count++]=(AgWireRange){copy,source,length};
}
void ag_wire_mismatches_destroy(AgMismatches *m){if(m){omap_destroy(&m->seen);arena_destroy(&m->arena);free(m->ranges);}}
bool ag_wire_message_field(AgMismatches *m,AgMessageType type,const AgField *f){
    if(f->wire==2&&ag_wire_validate(f->bytes)==AG_FOUND)return true;
    ag_wire_mismatch(m,type,f->number,f->position);return false;
}
AgResult ag_wire_integer_next_typed(AgMismatches *m,AgMessageType type,AgCursor *c,uint32_t n,uint64_t *v){
    for(;;){
        if(c->packed_offset<c->packed.n){if(varint(c->packed,&c->packed_offset,v))return AG_FOUND;ag_wire_mismatch(m,type,n,c->packed.p);c->packed_offset=c->packed.n;continue;}
        AgField f;size_t start=c->offset;AgResult r=ag_wire_next(c,&f);if(r!=AG_FOUND)return r;
        if(f.number!=n)continue;
        if(!f.wire){*v=f.integer;return AG_FOUND;}
        if(f.wire!=2){ag_wire_mismatch(m,type,n,c->input.p+start);continue;}
        size_t off=0,count=0;uint64_t ignored=0;bool valid=true;
        while(off<f.bytes.n)if(++count>AG_WIRE_MAX_FIELDS||!varint(f.bytes,&off,&ignored)){valid=false;break;}
        if(!valid){ag_wire_mismatch(m,type,n,f.position);continue;}
        c->packed=f.bytes;c->packed_offset=0;
    }
}
static AgResult typed(AgMismatches *m,AgMessageType type,Str input,uint32_t number,unsigned wire,bool text,AgField *out){
    AgCursor c={.input=input};AgField f;AgResult r,found=AG_ABSENT;
    while((r=ag_wire_next(&c,&f))==AG_FOUND)if(f.number==number){
        bool valid=f.wire==wire&&(!text||(str_utf8_scalar_valid(f.bytes)&&!memchr(f.bytes.p,0,f.bytes.n)));
        if(!valid){ag_wire_mismatch(m,type,number,f.position);continue;}
        *out=f;found=AG_FOUND;
    }
    return r==AG_MALFORMED?r:found;
}
AgResult ag_wire_uint(AgMismatches *m,AgMessageType type,Str input,uint32_t n,uint64_t *v){AgField f={0};AgResult r=typed(m,type,input,n,0,false,&f);if(r==AG_FOUND)*v=f.integer;return r;}
AgResult ag_wire_bytes(AgMismatches *m,AgMessageType type,Str input,uint32_t n,Str *v){AgField f={0};AgResult r=typed(m,type,input,n,2,false,&f);if(r==AG_FOUND)*v=f.bytes;return r;}
AgResult ag_wire_text(AgMismatches *m,AgMessageType type,Str input,uint32_t n,Str *v){AgField f={0};AgResult r=typed(m,type,input,n,2,true,&f);if(r==AG_FOUND)*v=f.bytes;return r;}
const char *ag_wire_type_name(AgMessageType type){
    static const char *names[]={"opaque",".exa.cortex_pb.CortexTrajectoryMetadata",".exa.cortex_pb.CortexWorkspaceMetadata",".exa.cortex_pb.CortexStepMetadata",".gemini_coder.Step",".exa.cortex_pb.CortexStepGeneratorMetadata",".exa.cortex_pb.ChatModelMetadata",".exa.cortex_pb.RetryInfo",".exa.codeium_common_pb.ModelUsageStats",".exa.codeium_common_pb.ModelInfo",".exa.codeium_common_pb.ChatToolCall",".exa.cortex_pb.CortexStepUserInput",".exa.cortex_pb.CortexStepPlannerResponse",".exa.codeium_common_pb.TextOrScopeItem",".exa.codeium_common_pb.Media",".google.protobuf.Timestamp",".google.protobuf.Duration",".exa.jetski_cortex_pb.ConversationAnnotations",".exa.jetski_cortex_pb.CascadeTrajectorySummary",".exa.cortex_pb.ChatStartMetadata"};
    return (unsigned)type<sizeof names/sizeof *names?names[type]:"unknown";
}
