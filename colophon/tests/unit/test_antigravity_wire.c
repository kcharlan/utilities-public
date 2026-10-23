#include "antigravity/wire.h"
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
    ASSERT_EQ(AG_FOUND,ag_wire_validate(summary,AG_SUMMARY));
}
TEST(antigravity_wire_typed_nested_and_limits) {
    ASSERT_EQ(AG_MALFORMED,ag_wire_validate(STR_LIT("\12\1\200"),AG_TRAJECTORY));
    ASSERT_EQ(AG_FOUND,ag_wire_validate(STR_LIT("\12\2\12\0"),AG_TRAJECTORY));
    ASSERT_EQ(AG_MALFORMED,ag_wire_validate(STR_LIT("\12\1\200"),AG_GENERATOR));
    Str oversized={"",AG_WIRE_MAX_BYTES+1};
    ASSERT_EQ(AG_MALFORMED,ag_wire_validate(oversized,AG_STEP));
    AgCursor c={.input=STR_LIT("\10\1\22\2\2\3\10\4")}; uint64_t v=0;
    ASSERT_EQ(AG_FOUND,ag_wire_integer_next(&c,1,&v));ASSERT_EQ(1,v);
    ASSERT_EQ(AG_FOUND,ag_wire_integer_next(&c,1,&v));ASSERT_EQ(4,v);
    ASSERT_EQ(AG_ABSENT,ag_wire_integer_next(&c,1,&v));
    c=(AgCursor){.input=STR_LIT("\22\2\2\3")};
    ASSERT_EQ(AG_FOUND,ag_wire_integer_next(&c,2,&v));ASSERT_EQ(2,v);
    ASSERT_EQ(AG_FOUND,ag_wire_integer_next(&c,2,&v));ASSERT_EQ(3,v);
}
TEST(antigravity_wire_rejects_known_field_wire_mismatch_and_bad_packed_tail) {
    ASSERT_EQ(AG_MALFORMED,ag_wire_validate(STR_LIT("\42\1x"),AG_ANNOTATIONS));
    ASSERT_EQ(AG_MALFORMED,ag_wire_validate(STR_LIT("\12\1\377"),AG_ANNOTATIONS));
    ASSERT_EQ(AG_MALFORMED,ag_wire_validate(STR_LIT("\22\1\200"),AG_GENERATOR));
    ASSERT_EQ(AG_FOUND,ag_wire_validate(STR_LIT("\22\2\1\2\20\3"),AG_GENERATOR));
    ASSERT_EQ(AG_FOUND,ag_wire_validate(STR_LIT("\241\6abcdefgh\255\6abcd\260\6\1\272\6\3xyz"),AG_ANNOTATIONS));
}
TEST(antigravity_wire_field_budget_overflow_and_fixed_truncation){
    size_t n=2*(AG_WIRE_MAX_FIELDS+1);char *data=malloc(n);ASSERT_TRUE(data);
    for(size_t i=0;i<n;i+=2){data[i]=8;data[i+1]=0;}
    ASSERT_EQ(AG_MALFORMED,ag_wire_validate((Str){data,(uint32_t)n},AG_OPAQUE));free(data);
    const unsigned char overflow[]={8,255,255,255,255,255,255,255,255,255,2};
    ASSERT_EQ(AG_MALFORMED,ag_wire_validate((Str){(const char *)overflow,sizeof overflow},AG_OPAQUE));
    ASSERT_EQ(AG_MALFORMED,ag_wire_validate(STR_LIT("\11short"),AG_OPAQUE));
    ASSERT_EQ(AG_MALFORMED,ag_wire_validate(STR_LIT("\15xx"),AG_OPAQUE));
}
