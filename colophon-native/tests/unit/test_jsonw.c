#include "runner.h"
#include "out/jsonw.h"
#include "util/json_read.h"
#include <math.h>
#include <stdlib.h>
TEST(jsonw_exact_wide_integer_boundaries) {
    const __int128 maximum=(__int128)(((unsigned __int128)1<<127)-1);
    const __int128 values[]={0,INT64_MIN,INT64_MAX,UINT64_MAX,(__int128)UINT64_MAX+1,-maximum-1,maximum};
    const char *expected[]={"0","-9223372036854775808","9223372036854775807","18446744073709551615","18446744073709551616","-170141183460469231731687303715884105728","170141183460469231731687303715884105727"};
    for(size_t i=0;i<sizeof values/sizeof *values;i++){
        JsonWriter w={0};jsonw_i128(&w,values[i]);ASSERT_EQ(ERR_OK,w.error.code);
        ASSERT_STREQ(expected[i],w.data);jsonw_free(&w);
    }
}
TEST(jsonw_ascii_surrogates_and_injection) {
    JsonWriter w={0};
    jsonw_string(&w,STR_LIT("<\"\n\t\\\x7f\xc3\xa9\xf0\x9f\x98\x80\xed\xa0\x80"));
    ASSERT_EQ(ERR_OK,w.error.code);
    ASSERT_STREQ("\"\\u003c\\\"\\n\\t\\\\\\u007f\\u00e9\\ud83d\\ude00\\ud800\"",w.data);
    jsonw_free(&w);
}
TEST(jsonw_shortest_and_nonfinite) {
    JsonWriter w={0};jsonw_double(&w,1.001);
    ASSERT_STREQ("1.001",w.data);jsonw_free(&w);
    jsonw_double(&w,-0.0);ASSERT_STREQ("-0.0",w.data);jsonw_free(&w);
    jsonw_double(&w,INFINITY);ASSERT_EQ(ERR_INVALID,w.error.code);jsonw_free(&w);
}
TEST(jsonw_tree_order_types_and_escaping) {
    JsonRead r=json_read(STR_LIT("{\"s\":\"<\\u00e9\\ud83d\\ude00\\u0000\",\"n\":1.0,\"a\":[null,false,2]}"),BYTES,JSON_CONSTANTS_REJECT,"test.writer");
    ASSERT_EQ(JSON_OK,r.status);JsonWriter w={0};jsonw_value(&w,yyjson_doc_get_root(r.doc));
    ASSERT_EQ(ERR_OK,w.error.code);
    ASSERT_STREQ("{\"s\":\"\\u003c\\u00e9\\ud83d\\ude00\\u0000\",\"n\":1.0,\"a\":[null,false,2]}",w.data);
    jsonw_free(&w);json_read_free(&r);
}
TEST(jsonw_iterative_deep_tree) {
    size_t depth=9999,n=2*depth+1;char *input=malloc(n+1);ASSERT_TRUE(input);
    memset(input,'[',depth);input[depth]='0';memset(input+depth+1,']',depth);input[n]=0;
    JsonRead r=json_read((Str){input,(uint32_t)n},BYTES,JSON_CONSTANTS_REJECT,"test.writer");
    ASSERT_EQ(JSON_OK,r.status);JsonWriter w={0};jsonw_value(&w,yyjson_doc_get_root(r.doc));
    ASSERT_EQ(ERR_OK,w.error.code);ASSERT_EQ(n,w.length);ASSERT_STREQ(input,w.data);
    jsonw_free(&w);json_read_free(&r);free(input);
}
