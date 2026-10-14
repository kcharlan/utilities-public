#include "runner.h"
#include "util/json_read.h"
#include "util/json_number.h"
#include "util/pynum.h"
#include <pthread.h>
#include <stdlib.h>
#include <math.h>

TEST(json_freeze_owned_order_raw_and_embedded_nul) {
    JsonRead r=json_read(STR_LIT("{\"x\":[{},[],{\"n\":9007199254740993,\"s\":\"a\\u0000b\"}],\"x\":2,\"z\":false}"),BYTES,JSON_CONSTANTS_ALLOW,"test.freeze");
    ASSERT_EQ(JSON_OK,r.status);
    yyjson_mut_doc *mutable=yyjson_mut_doc_new(NULL);
    yyjson_mut_doc_set_root(mutable,yyjson_val_mut_copy(mutable,yyjson_doc_get_root(r.doc)));
    yyjson_doc *frozen=NULL;
    ASSERT_EQ(ERR_OK,json_freeze(mutable,&frozen).code);
    yyjson_mut_doc_free(mutable);json_read_free(&r);
    yyjson_val *root=yyjson_doc_get_root(frozen);
    ASSERT_EQ(3,yyjson_obj_size(root));
    yyjson_obj_iter it=yyjson_obj_iter_with(root);
    yyjson_val *key=yyjson_obj_iter_next(&it);
    ASSERT_STREQ("x",yyjson_get_str(key));
    yyjson_val *arr=yyjson_obj_iter_get_val(key);
    ASSERT_EQ(0,yyjson_obj_size(yyjson_arr_get(arr,0)));
    ASSERT_EQ(0,yyjson_arr_size(yyjson_arr_get(arr,1)));
    yyjson_val *obj=yyjson_arr_get(arr,2);
    ASSERT_STREQ("9007199254740993",yyjson_get_raw(obj_get_last(obj,STR_LIT("n"))));
    yyjson_val *s=obj_get_last(obj,STR_LIT("s"));
    ASSERT_EQ(3,yyjson_get_len(s));ASSERT_TRUE(!memcmp("a\0b",yyjson_get_str(s),3));
    key=yyjson_obj_iter_next(&it);ASSERT_STREQ("x",yyjson_get_str(key));
    ASSERT_STREQ("2",yyjson_get_raw(yyjson_obj_iter_get_val(key)));
    yyjson_doc_free(frozen);
}
static void *freeze_deep(void *unused) {
    (void)unused;
    yyjson_mut_doc *mutable=yyjson_mut_doc_new(NULL);
    yyjson_mut_val *root=yyjson_mut_arr(mutable),*parent=root;
    yyjson_mut_doc_set_root(mutable,root);
    for(size_t i=0;i<9999;i++) {yyjson_mut_val *next=yyjson_mut_arr(mutable);ASSERT_TRUE(yyjson_mut_arr_append(parent,next));parent=next;}
    ASSERT_TRUE(yyjson_mut_arr_append(parent,yyjson_mut_null(mutable)));
    yyjson_doc *frozen=NULL;ASSERT_EQ(ERR_OK,json_freeze(mutable,&frozen).code);
    yyjson_mut_doc_free(mutable);
    ASSERT_EQ(JSON_OK,json_depth_check(frozen,10000));
    yyjson_doc_free(frozen);return NULL;
}
TEST(json_freeze_deep_on_catalog_stack) {
    pthread_attr_t attr;ASSERT_EQ(0,pthread_attr_init(&attr));
    ASSERT_EQ(0,pthread_attr_setstacksize(&attr,512*1024));
    pthread_t thread;ASSERT_EQ(0,pthread_create(&thread,&attr,freeze_deep,NULL));
    ASSERT_EQ(0,pthread_join(thread,NULL));pthread_attr_destroy(&attr);
}
static void *freeze_custom_malloc(void *context,size_t bytes) {(void)context;return malloc(bytes);}
static void *freeze_custom_realloc(void *context,void *ptr,size_t old,size_t bytes) {(void)context;(void)old;return realloc(ptr,bytes);}
static void freeze_custom_free(void *context,void *ptr) {(void)context;free(ptr);}
TEST(json_freeze_does_not_retain_source_allocator_context) {
    int context=1;
    yyjson_alc allocator={freeze_custom_malloc,freeze_custom_realloc,freeze_custom_free,&context};
    yyjson_mut_doc *source=yyjson_mut_doc_new(&allocator);
    yyjson_mut_doc_set_root(source,yyjson_mut_strcpy(source,"synthetic allocator owner"));
    yyjson_doc *frozen=NULL;ASSERT_EQ(ERR_OK,json_freeze(source,&frozen).code);
    yyjson_mut_doc_free(source);
    ASSERT_TRUE(frozen->alc.ctx!=&context);
    ASSERT_STREQ("synthetic allocator owner",yyjson_get_str(yyjson_doc_get_root(frozen)));
    yyjson_doc_free(frozen);
}
TEST(pricing_direct_context_decimal_boundary) {
    ASSERT_FALSE(pynum_context_int((PyNum){.is_float=true,.f=-0x1p63}));
    ASSERT_TRUE(pynum_context_int((PyNum){.is_float=true,.f=128000.0}));
    ASSERT_FALSE(pynum_context_int((PyNum){.is_float=true,.f=128000.5}));
    ASSERT_TRUE(pynum_context_int((PyNum){.i=INT64_MIN}));
}

TEST(json_modes_duplicates_and_surrogates) {
    JsonRead r=json_read(STR_LIT("{\"x\":1,\"x\":{},\"x\":2,\"s\":\"\\ud800\\ud801\\udc00\"}"),BYTES,JSON_CONSTANTS_ALLOW,"test.json");
    ASSERT_EQ(JSON_OK,r.status);
    yyjson_val *root=yyjson_doc_get_root(r.doc);
    ASSERT_STREQ("2",yyjson_get_raw(obj_get_last(root,STR_LIT("x"))));
    ASSERT_TRUE(yyjson_is_obj(obj_get_first_typed(root,STR_LIT("x"),YYJSON_TYPE_OBJ)));
    ASSERT_TRUE(str_equal((Str){yyjson_get_str(obj_get_last(root,STR_LIT("s"))),7},STR_LIT("\xed\xa0\x80\xf0\x90\x90\x80")));
    yyjson_mut_doc *dict=NULL;ASSERT_EQ(ERR_OK,json_load_dict_semantics(r.doc,&dict).code);
    ASSERT_EQ(2,yyjson_mut_obj_size(yyjson_mut_doc_get_root(dict)));
    yyjson_mut_doc_free(dict);json_read_free(&r);
    r=json_read(STR_LIT("\xef\xbb\xbf{}"),BYTES,JSON_CONSTANTS_ALLOW,"test.json");ASSERT_EQ(JSON_OK,r.status);json_read_free(&r);
    r=json_read(STR_LIT("\xef\xbb\xbf{}"),STR,JSON_CONSTANTS_ALLOW,"test.json");ASSERT_EQ(JSON_INVALID,r.status);json_read_free(&r);
    r=json_read(STR_LIT("\"\xed\xa0\x80\xed\xb0\x80\""),STRICT,JSON_CONSTANTS_ALLOW,"test.json");ASSERT_EQ(JSON_INVALID,r.status);json_read_free(&r);
    r=json_read(STR_LIT("\"\xed\xa0\x80\xed\xb0\x80\""),STR,JSON_CONSTANTS_ALLOW,"test.json");ASSERT_EQ(JSON_OK,r.status);ASSERT_EQ(6,yyjson_get_len(yyjson_doc_get_root(r.doc)));json_read_free(&r);
}
TEST(json_whole_document_checks_and_consumed_integer) {
    JsonRead r=json_read(STR_LIT("{\"ignored\":nan}"),BYTES,JSON_CONSTANTS_ALLOW,"test.json");ASSERT_EQ(JSON_INVALID,r.status);ASSERT_EQ(1,r.stats.invalid_number_spellings);json_read_free(&r);
    r=json_read(STR_LIT("{\"ignored\":9223372036854775808}"),BYTES,JSON_CONSTANTS_ALLOW,"test.json");ASSERT_EQ(JSON_OK,r.status);
    PyNum value;ASSERT_FALSE(json_number(obj_get_last(yyjson_doc_get_root(r.doc),STR_LIT("ignored")),"test.integer",&value));json_read_free(&r);
    char *s=malloc(4302);memset(s,'9',4301);s[4301]=0;
    r=json_read((Str){s,4301},BYTES,JSON_CONSTANTS_ALLOW,"test.json");ASSERT_EQ(JSON_INVALID,r.status);ASSERT_EQ(1,r.stats.integer_digit_limit);json_read_free(&r);free(s);
}
static void *deep_thread(void *arg) {
    size_t depth=*(size_t*)arg;char *s=malloc(depth*2+1);memset(s,'[',depth);s[depth]='0';memset(s+depth+1,']',depth);
    bool ok=true;
    for(JsonMode mode=BYTES;mode<=STR;mode++){
        JsonRead r=json_read((Str){s,(uint32_t)(depth*2+1)},mode,JSON_CONSTANTS_ALLOW,"test.deep");
        ok=ok&&r.status==(depth<=10000?JSON_OK:JSON_T2_NEST);
        if(ok&&r.doc){yyjson_mut_doc *dict=NULL;ok=json_load_dict_semantics(r.doc,&dict).code==ERR_OK;yyjson_mut_doc_free(dict);}
        json_read_free(&r);
    }
    free(s);return (void*)(uintptr_t)ok;
}
TEST(json_deep_walkers_small_stack) {
    pthread_attr_t attr;ASSERT_EQ(0,pthread_attr_init(&attr));ASSERT_EQ(0,pthread_attr_setstacksize(&attr,512*1024));
    for(size_t depth=9999;depth<=10001;depth++){pthread_t t;void *result;ASSERT_EQ(0,pthread_create(&t,&attr,deep_thread,&depth));ASSERT_EQ(0,pthread_join(t,&result));ASSERT_TRUE((uintptr_t)result);}
    pthread_attr_destroy(&attr);
}
TEST(pynum_exact_equality_floor_and_epoch) {
    int64_t q;ASSERT_TRUE(floordiv_i64(-7,3,&q));ASSERT_EQ(-3,q);ASSERT_FALSE(floordiv_i64(INT64_MIN,-1,&q));
    ASSERT_FALSE(pynum_equal((PyNum){false,INT64_C(9007199254740993),0},(PyNum){true,0,9007199254740992.0}));
    ASSERT_FALSE(pynum_equal((PyNum){false,INT64_MAX,0},(PyNum){true,0,0x1p63}));
    PyNum result;ASSERT_TRUE(pynum_add((PyNum){false,2,0},(PyNum){true,0,0.5},"test.timing",&result));ASSERT_TRUE(result.is_float);ASSERT_EQ(2.5,result.f);
    ASSERT_FALSE(pynum_add((PyNum){false,INT64_MAX,0},(PyNum){false,1,0},"test.timing",&result));
    int64_t ms;ASSERT_TRUE(pynum_epoch_ms((PyNum){true,0,1.001},false,"test.epoch",&ms));ASSERT_EQ(1001,ms);
    ASSERT_TRUE(pynum_epoch_ms((PyNum){true,0,-1.001},false,"test.epoch",&ms));ASSERT_EQ(-1001,ms);
}
TEST(pynum_direct_float_timing_validation) {
    PyNum out={false,17,0};
    ASSERT_TRUE(pynum_timing((PyNum){true,0,1.5},"test.timing",&out));ASSERT_TRUE(out.is_float);ASSERT_EQ(1.5,out.f);
    ASSERT_FALSE(pynum_timing((PyNum){true,0,0x1p63},"test.timing",&out));ASSERT_EQ(1.5,out.f);
    ASSERT_FALSE(pynum_timing((PyNum){true,0,NAN},"test.timing",&out));
}
TEST(json_dict_owned_spans_and_order) {
    JsonRead r=json_read(STR_LIT("{\"a\\u0000b\":{\"x\":\"first\",\"x\":\"last\"},\"z\":[1e2],\"a\\u0000b\":{\"s\":\"\\ud800\"}}"),BYTES,JSON_CONSTANTS_ALLOW,"test.dict");
    ASSERT_EQ(JSON_OK,r.status);yyjson_mut_doc *copy=NULL;ASSERT_EQ(ERR_OK,json_load_dict_semantics(r.doc,&copy).code);json_read_free(&r);
    yyjson_mut_val *root=yyjson_mut_doc_get_root(copy);ASSERT_EQ(2,yyjson_mut_obj_size(root));yyjson_mut_obj_iter it=yyjson_mut_obj_iter_with(root);
    yyjson_mut_val *key=yyjson_mut_obj_iter_next(&it);ASSERT_EQ(3,yyjson_mut_get_len(key));ASSERT_TRUE(!memcmp("a\0b",yyjson_mut_get_str(key),3));
    yyjson_mut_val *v=yyjson_mut_obj_get(yyjson_mut_obj_iter_get_val(key),"s");ASSERT_TRUE(!memcmp("\xed\xa0\x80",yyjson_mut_get_str(v),3));
    key=yyjson_mut_obj_iter_next(&it);ASSERT_STREQ("z",yyjson_mut_get_str(key));v=yyjson_mut_arr_get(yyjson_mut_obj_iter_get_val(key),0);ASSERT_STREQ("1e2",yyjson_mut_get_raw(v));
    yyjson_mut_doc_free(copy);
}
