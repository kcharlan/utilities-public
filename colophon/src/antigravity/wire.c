#include "wire.h"
#include <string.h>
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
/* Public descriptor projection. Fully qualified names and the producing binary
 * SHA-256 are pinned in tests/fixtures/antigravity/schema.json. Omitted fields
 * remain opaque unknown fields; no heuristic recursive byte decoding. */
typedef struct { AgMessageType owner;uint32_t number;unsigned type;bool repeated;AgMessageType child; } Rule;
#include "schema.inc"
static unsigned wire_type(unsigned type){
    return type==1||type==6||type==16?1:type==2||type==7||type==15?5:type==9||type==11||type==12?2:0;
}
static AgResult validate(Str input,AgMessageType type,unsigned depth,size_t *budget){
    if(depth>AG_WIRE_MAX_DEPTH)return AG_MALFORMED;
    AgCursor c={.input=input};AgField f;AgResult r;
    while((r=ag_wire_next(&c,&f))==AG_FOUND){
        if(!*budget)return AG_MALFORMED;--*budget;
        for(size_t i=0;i<sizeof rules/sizeof *rules;i++)if(rules[i].owner==type&&rules[i].number==f.number){
            const Rule *rule=&rules[i];unsigned expected=wire_type(rule->type);
            if(f.wire==2&&expected!=2&&rule->repeated){
                size_t off=0;uint64_t n;
                if(expected){if(f.bytes.n%(expected==1?8:4))return AG_MALFORMED;}
                else while(off<f.bytes.n){if(!*budget||!varint(f.bytes,&off,&n))return AG_MALFORMED;--*budget;}
            }else if(f.wire!=expected)return AG_MALFORMED;
            if(rule->type==11&&validate(f.bytes,rule->child,depth+1,budget)==AG_MALFORMED)return AG_MALFORMED;
            if(rule->type==9&&!str_utf8_scalar_valid(f.bytes))return AG_MALFORMED;
            break;
        }
    }
    return r==AG_MALFORMED?r:AG_FOUND;
}
AgResult ag_wire_validate(Str input,AgMessageType type){size_t budget=AG_WIRE_MAX_FIELDS;return validate(input,type,0,&budget);}
const char *ag_wire_type_name(AgMessageType type){
    static const char *names[]={"opaque",".exa.cortex_pb.CortexTrajectoryMetadata",".exa.cortex_pb.CortexWorkspaceMetadata",".exa.cortex_pb.CortexStepMetadata",".gemini_coder.Step",".exa.cortex_pb.CortexStepGeneratorMetadata",".exa.cortex_pb.ChatModelMetadata",".exa.cortex_pb.RetryInfo",".exa.codeium_common_pb.ModelUsageStats",".exa.codeium_common_pb.ModelInfo",".exa.codeium_common_pb.ChatToolCall",".exa.cortex_pb.CortexStepUserInput",".exa.cortex_pb.CortexStepPlannerResponse",".exa.codeium_common_pb.TextOrScopeItem",".exa.codeium_common_pb.Media",".google.protobuf.Timestamp",".google.protobuf.Duration",".exa.jetski_cortex_pb.ConversationAnnotations",".exa.jetski_cortex_pb.CascadeTrajectorySummary"};
    return (unsigned)type<sizeof names/sizeof *names?names[type]:"unknown";
}
