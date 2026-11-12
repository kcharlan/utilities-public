#include "antigravity/wire.h"
#include "antigravity/corpus.h"
#include "runner.h"
#include <stdlib.h>

/* Catches accepting invalid wire encodings and conflating absent with zero. */
TEST(antigravity_wire_boundaries_and_last_wins) {
    const unsigned char bytes[]={8,0,8,127,16,255,255,255,255,255,255,255,255,255,1,29,1,2,3,4};
    Str input={(const char *)bytes,sizeof bytes}; AgField f={0};
    ASSERT_EQ(AG_FOUND,ag_wire_last(input,1,&f)); ASSERT_EQ(127,f.integer);
    ASSERT_EQ(AG_FOUND,ag_wire_last(input,2,&f)); ASSERT_EQ(UINT64_MAX,f.integer);
    ASSERT_EQ(AG_ABSENT,ag_wire_last(input,4,&f));
    const unsigned char *bad[]={ (const unsigned char *)"\0", (const unsigned char *)"\10\200",(const unsigned char *)"\12\4x",(const unsigned char *)"\13",(const unsigned char *)"\10\200\0"};
    const size_t lengths[]={1,2,3,1,3};
    for(size_t i=0;i<5;i++)ASSERT_EQ(AG_MALFORMED,ag_wire_last((Str){(const char *)bad[i],lengths[i]},1,&f));
}
TEST(antigravity_summary_archive_descriptor) {
    /* .exa.jetski_cortex_pb.CascadeTrajectorySummary.annotations = 15;
     * .exa.jetski_cortex_pb.ConversationAnnotations.archived = 4.
     * The unrelated Cortex annotation's archived=3 must not be used. */
    Str summary=STR_LIT("\172\5\32\1x\40\0");
    AgField annotations={0},archived={0};
    ASSERT_EQ(AG_FOUND,ag_wire_last(summary,15,&annotations));
    ASSERT_EQ(AG_FOUND,ag_wire_last(annotations.bytes,4,&archived));
    ASSERT_EQ(0,archived.integer);
    ASSERT_EQ(AG_FOUND,ag_wire_validate(summary));
}
TEST(antigravity_wire_typed_nested_and_limits) {
    ASSERT_EQ(AG_FOUND,ag_wire_validate(STR_LIT("\12\1\200")));
    ASSERT_EQ(AG_FOUND,ag_wire_validate(STR_LIT("\12\2\12\0")));
    ASSERT_EQ(AG_FOUND,ag_wire_validate(STR_LIT("\12\1\200")));
    Str oversized={"",AG_WIRE_MAX_BYTES+1};
    ASSERT_EQ(AG_MALFORMED,ag_wire_validate(oversized));
    AgCursor c={.input=STR_LIT("\10\1\22\2\2\3\10\4")}; uint64_t v=0;
    ASSERT_EQ(AG_FOUND,ag_wire_integer_next(&c,1,&v));ASSERT_EQ(1,v);
    ASSERT_EQ(AG_FOUND,ag_wire_integer_next(&c,1,&v));ASSERT_EQ(4,v);
    ASSERT_EQ(AG_ABSENT,ag_wire_integer_next(&c,1,&v));
    c=(AgCursor){.input=STR_LIT("\22\2\2\3")};
    ASSERT_EQ(AG_FOUND,ag_wire_integer_next(&c,2,&v));ASSERT_EQ(2,v);
    ASSERT_EQ(AG_FOUND,ag_wire_integer_next(&c,2,&v));ASSERT_EQ(3,v);
}
TEST(antigravity_wire_structure_ignores_nested_types_and_packed_tail) {
    ASSERT_EQ(AG_FOUND,ag_wire_validate(STR_LIT("\42\1x")));
    ASSERT_EQ(AG_FOUND,ag_wire_validate(STR_LIT("\12\1\377")));
    ASSERT_EQ(AG_FOUND,ag_wire_validate(STR_LIT("\22\1\200")));
    ASSERT_EQ(AG_FOUND,ag_wire_validate(STR_LIT("\22\2\1\2\20\3")));
    ASSERT_EQ(AG_FOUND,ag_wire_validate(STR_LIT("\241\6abcdefgh\255\6abcd\260\6\1\272\6\3xyz")));
}
TEST(antigravity_wire_typed_fields_ignore_mismatches) {
    AgMismatches m={0};uint64_t v=0;Str text={0};
    Str input=STR_LIT("\12\1x\20\7\32\1\377\42\1\0");
    ASSERT_EQ(AG_ABSENT,ag_wire_uint(&m,AG_USAGE,input,1,&v));
    ASSERT_EQ(AG_FOUND,ag_wire_uint(&m,AG_USAGE,input,2,&v));ASSERT_EQ(7,v);
    ASSERT_EQ(AG_ABSENT,ag_wire_text(&m,AG_USAGE,input,3,&text));
    ASSERT_EQ(AG_ABSENT,ag_wire_text(&m,AG_USAGE,input,4,&text));
    ASSERT_EQ(AG_FOUND,ag_wire_bytes(&m,AG_USAGE,input,3,&text));
    ASSERT_EQ(1,m.counts[AG_USAGE][1]);ASSERT_EQ(1,m.counts[AG_USAGE][3]);ASSERT_EQ(1,m.counts[AG_USAGE][4]);
    ASSERT_EQ(AG_ABSENT,ag_wire_uint(&m,AG_USAGE,input,1,&v));ASSERT_EQ(1,m.counts[AG_USAGE][1]);
    ag_wire_mismatches_destroy(&m);
}
TEST(antigravity_wire_mismatches_keep_identity_across_merges) {
    AgMismatches m={0};Arena a={0};uint64_t value=0;Str merged={0};
    Str input=STR_LIT("\112\3\12\1x\112\2\20\1");
    for(size_t i=0;i<2;i++){
        ASSERT_EQ(ERR_OK,antigravity_message_merge_typed(&m,AG_CHAT_MODEL,&a,input,9,&merged).code);
        ASSERT_EQ(AG_ABSENT,ag_wire_uint(&m,AG_TIMESTAMP,merged,1,&value));
        ASSERT_EQ(AG_FOUND,ag_wire_uint(&m,AG_TIMESTAMP,merged,2,&value));ASSERT_EQ(1,value);
    }
    ASSERT_EQ(1,m.counts[AG_TIMESTAMP][1]);
    AgCursor c={.input=STR_LIT("\22\2\1\200")};
    ASSERT_EQ(AG_ABSENT,ag_wire_integer_next_typed(&m,AG_GENERATOR,&c,2,&value));
    ASSERT_EQ(1,m.counts[AG_GENERATOR][2]);
    ag_wire_mismatches_destroy(&m);arena_destroy(&a);
}
TEST(antigravity_wire_field_budget_overflow_and_fixed_truncation){
    size_t n=2*(AG_WIRE_MAX_FIELDS+1);char *data=malloc(n);ASSERT_TRUE(data);
    for(size_t i=0;i<n;i+=2){data[i]=8;data[i+1]=0;}
    ASSERT_EQ(AG_MALFORMED,ag_wire_validate((Str){data,(uint32_t)n}));free(data);
    const unsigned char overflow[]={8,255,255,255,255,255,255,255,255,255,2};
    ASSERT_EQ(AG_MALFORMED,ag_wire_validate((Str){(const char *)overflow,sizeof overflow}));
    ASSERT_EQ(AG_MALFORMED,ag_wire_validate(STR_LIT("\11short")));
    ASSERT_EQ(AG_MALFORMED,ag_wire_validate(STR_LIT("\15xx")));
}
TEST(antigravity_wire_chat_start_timestamp_is_typed) {
    ASSERT_EQ(AG_FOUND,ag_wire_validate(STR_LIT("\12\5\112\3\42\1\200")));
    ASSERT_EQ(AG_FOUND,ag_wire_validate(STR_LIT("\12\7\112\5\42\3\12\1x")));
    ASSERT_EQ(AG_FOUND,ag_wire_validate(STR_LIT("\12\4\112\2\42\0")));
    ASSERT_EQ(AG_FOUND,ag_wire_validate(STR_LIT("\12\6\112\4\42\2\10\0")));
    /* Unknown field99 bytes are opaque, even when not themselves a message. */
    ASSERT_EQ(AG_FOUND,ag_wire_validate(STR_LIT("\12\6\112\4\232\6\1\200")));
}
