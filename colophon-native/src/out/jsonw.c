#include "jsonw.h"
#include "yyjson.h"
#include "util/json_number.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
void jsonw_bytes(JsonWriter *w,const void *bytes,size_t n) {
    if(w->error.code!=ERR_OK)return;
    if(n>SIZE_MAX-w->length-1){w->error=err_make(ERR_NOMEM,"output too large");return;}
    size_t wanted=w->length+n+1;
    if(wanted>w->capacity){size_t cap=w->capacity?w->capacity:1024;
        while(cap<wanted){if(cap>SIZE_MAX/2){cap=wanted;break;}cap*=2;}
        char *p=realloc(w->data,cap);if(!p){w->error=err_make(ERR_NOMEM,"output allocation failed");return;}w->data=p;w->capacity=cap;}
    if(n)memcpy(w->data+w->length,bytes,n);
    w->length+=n;w->data[w->length]=0;
}
void jsonw_raw(JsonWriter *w,const char *s){jsonw_bytes(w,s,strlen(s));}
static void codeunit(JsonWriter *w,uint32_t c){char b[7];snprintf(b,sizeof b,"\\u%04x",c);jsonw_bytes(w,b,6);}
void jsonw_string(JsonWriter *w,Str s) {
    jsonw_raw(w,"\"");size_t pos=0;uint32_t c;
    while(pos<s.n){if(!str_decode_next(s,&pos,&c)){w->error=err_make(ERR_INVALID,"invalid WTF-8 output");return;}
        switch(c){case '"':jsonw_raw(w,"\\\"");break;case '\\':jsonw_raw(w,"\\\\");break;
        case '\b':jsonw_raw(w,"\\b");break;case '\f':jsonw_raw(w,"\\f");break;case '\n':jsonw_raw(w,"\\n");break;
        case '\r':jsonw_raw(w,"\\r");break;case '\t':jsonw_raw(w,"\\t");break;
        default:if(c<32||c>=127||c=='<'){if(c>0xffff){c-=0x10000;codeunit(w,0xd800+(c>>10));codeunit(w,0xdc00+(c&1023));}else codeunit(w,c);}else{char b=(char)c;jsonw_bytes(w,&b,1);}}
    }jsonw_raw(w,"\"");
}
void jsonw_i64(JsonWriter *w,int64_t v){char b[32];snprintf(b,sizeof b,"%lld",(long long)v);jsonw_raw(w,b);}
void jsonw_i128(JsonWriter *w,__int128 value) {
    char buffer[41];size_t end=sizeof buffer,position=end;
    unsigned __int128 magnitude=(unsigned __int128)value;
    if(value<0)magnitude=0-magnitude;
    do {buffer[--position]=(char)('0'+magnitude%10);magnitude/=10;} while(magnitude);
    if(value<0)buffer[--position]='-';
    jsonw_bytes(w,buffer+position,end-position);
}
void jsonw_double(JsonWriter *w,double v){
    if(!isfinite(v)){w->error=err_make(ERR_INVALID,"non-finite output number");return;}
    yyjson_val number={0};yyjson_set_real(&number,v);char b[64];char *end=yyjson_write_number(&number,b);
    if(!end){w->error=err_make(ERR_INVALID,"number output failed");return;}jsonw_bytes(w,b,(size_t)(end-b));
}
void jsonw_free(JsonWriter *w){free(w->data);*w=(JsonWriter){0};}
void jsonw_value(JsonWriter *w,yyjson_val *value){
    typedef struct {yyjson_val *value;bool begun,comma;yyjson_arr_iter array;yyjson_obj_iter object;} Frame;
    size_t count=1,capacity=32;Frame *stack=calloc(capacity,sizeof *stack);
    if(!stack){w->error=err_make(ERR_NOMEM,"writer stack allocation failed");return;}stack[0].value=value;
    while(count&&w->error.code==ERR_OK){Frame *f=&stack[count-1];yyjson_val *v=f->value;
        if(!v||yyjson_is_null(v)){jsonw_raw(w,"null");count--;continue;}
        if(yyjson_is_str(v)){jsonw_string(w,(Str){yyjson_get_str(v),(uint32_t)yyjson_get_len(v)});count--;continue;}
        if(yyjson_is_bool(v)){jsonw_raw(w,yyjson_get_bool(v)?"true":"false");count--;continue;}
        if(yyjson_is_num(v)||yyjson_is_raw(v)){PyNum n;if(!json_number(v,"payload:number",&n))w->error=err_make(ERR_INVALID,"invalid output number");else if(n.is_float)jsonw_double(w,n.f);else jsonw_i64(w,n.i);count--;continue;}
        bool object=yyjson_is_obj(v);if(!f->begun){f->begun=true;jsonw_raw(w,object?"{":"[");if(object)f->object=yyjson_obj_iter_with(v);else f->array=yyjson_arr_iter_with(v);}
        yyjson_val *child=object?yyjson_obj_iter_next(&f->object):yyjson_arr_iter_next(&f->array);
        if(!child){jsonw_raw(w,object?"}":"]");count--;continue;}
        if(f->comma)jsonw_raw(w,",");f->comma=true;
        if(object){jsonw_string(w,(Str){yyjson_get_str(child),(uint32_t)yyjson_get_len(child)});jsonw_raw(w,":");child=yyjson_obj_iter_get_val(child);}
        if(count==capacity){if(capacity>SIZE_MAX/(2*sizeof *stack)){w->error=err_make(ERR_NOMEM,"writer stack too large");break;}capacity*=2;Frame *grown=realloc(stack,capacity*sizeof *stack);if(!grown){w->error=err_make(ERR_NOMEM,"writer stack allocation failed");break;}stack=grown;}
        stack[count++]=(Frame){.value=child};
    }free(stack);
}
