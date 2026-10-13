#include "acct/resolver.h"
#include "parse/record.h"
#include "runner.h"
#include "testing/codec_roundtrip.h"
#include <stdint.h>
#include <stdlib.h>

TEST(accounting_rejects_unrepresentable_observation_capacity_before_access) {
  TokenStream stream={.count=SIZE_MAX};AccountingResult result={0};
  ASSERT_EQ(ERR_NOMEM,accounting_parse(&stream,NULL,&result).code);
  ASSERT_TRUE(result.arena.head==NULL);accounting_result_destroy(&result);
}

TEST(accounting_normalization_memo_owns_results_after_input_teardown) {
  char first[]="synthetic-unknown",second[]="synthetic-unknown";
  TokenObservation observations[]={
    {.tag=TOKEN_B,.timestamp=STR_LIT("2030-01-07T12:00:00Z"),.model={first,sizeof first-1}},
    {.tag=TOKEN_B,.timestamp=STR_LIT("2030-01-07T12:00:00Z"),.model={second,sizeof second-1}}};
  TokenStream stream={.observations=observations,.count=2};AccountingResult result={0};
  InheritedResolver resolver={0};
  ASSERT_EQ(ERR_OK,accounting_parse(&stream,&resolver,&result).code);ASSERT_EQ(2,result.row_count);
  resolver_destroy(&resolver);
  ASSERT_TRUE(result.rows[0].model.p==result.rows[1].model.p);
  memset(first,'x',sizeof first-1);memset(second,'y',sizeof second-1);
  ASSERT_TRUE(str_equal(result.rows[0].model,STR_LIT("synthetic-unknown")));
  accounting_result_destroy(&result);
}

TEST(accounting_replay_reset_and_unresolved_provenance_survive_scratch_teardown) {
  TokenObservation observation={.tag=TOKEN_T,.line=2,.uidx=1,.ordinal={true,1},
    .timestamp=STR_LIT("2030-01-07T12:00:00Z"),.last={true,false,5,0,1,0},.total={true,false,5,0,1,0}};
  TokenStream stream={.observations=&observation,.count=1,.has_prepass=true,
    .prepass={.session_id=STR_LIT("synthetic-child"),.is_subagent=true,
      .history_start_ordinal={true,1}}};
  AccountingResult result={0};
  ASSERT_EQ(ERR_OK,accounting_parse(&stream,NULL,&result).code);
  ASSERT_EQ(1,result.row_count);ASSERT_EQ(1,result.snapshot_count);ASSERT_EQ(1,result.timeline_count);
  ASSERT_EQ(1.5,result.timeline[0].position);ASSERT_EQ(5,result.rows[0].tokens.input);
  accounting_result_destroy(&result);
  stream.prepass=(TokenMeta){.session_id=STR_LIT("synthetic-child"),
    .forked_from_id=STR_LIT("synthetic-missing"),.fork_ts=STR_LIT("2030-01-07T12:00:00Z")};
  InheritedResolver resolver={0};
  ASSERT_EQ(ERR_OK,accounting_parse(&stream,&resolver,&result).code);resolver_destroy(&resolver);
  ASSERT_TRUE(result.unresolved);ASSERT_EQ(1,result.buffered_count);
  ASSERT_TRUE(result.buffered_sources[0]==&observation);
  ASSERT_EQ(0,memcmp(result.buffered,&observation,sizeof observation));
  ASSERT_EQ(1,result.snapshot_count);accounting_result_destroy(&result);
}

TEST(accounting_empty_kind_arrays_do_not_scale_with_control_observations) {
  const size_t count=4096;
  TokenObservation *observations=calloc(count,sizeof *observations);ASSERT_TRUE(observations);
  for(size_t i=0;i<count;i++)observations[i].tag=TOKEN_S;
  TokenStream stream={.observations=observations,.count=count};
  AccountingResult result={0};ASSERT_EQ(ERR_OK,accounting_parse(&stream,NULL,&result).code);
  ASSERT_EQ(0,result.row_count);ASSERT_EQ(0,result.snapshot_count);ASSERT_EQ(0,result.timeline_count);
  ASSERT_TRUE(result.rows==NULL);ASSERT_TRUE(result.snapshots==NULL);
  ASSERT_TRUE(result.buffered==NULL);ASSERT_TRUE(result.buffered_sources==NULL);
  ASSERT_TRUE(cp_test_arena_capacity(&result.arena)<=65536);
  accounting_result_destroy(&result);free(observations);
}

TEST(
    accounting_cached_stream_is_immutable_and_results_have_independent_owners) {
  Intern intern;
  ASSERT_EQ(0, intern_init(&intern).code);
  TokenObservation observations[] = {
      {.tag = TOKEN_T,
       .line = 1,
       .uidx = 1,
       .ordinal = {true, 1},
       .timestamp = STR_LIT("2030-01-07T12:00:00Z"),
       .last = {true, false, 5, 0, 1, 0},
       .total = {true, false, 5, 0, 1, 0}}};
  LogRecord record = {.identifiers = &intern};
  record.key.path = STR_LIT("/synthetic/cached");
  record.token_stream =
      (TokenStream){.arena = &record.arena,
                    .identifiers = &intern,
                    .has_prepass = true,
                    .prepass = {.session_id = STR_LIT("synthetic")},
                    .observations = observations,
                    .count = 1,
                    .capacity = 1};
  ASSERT_EQ(0, test_codec_roundtrip(&record).code);
  TokenObservation before = record.token_stream.observations[0];
  AccountingResult first = {0}, second = {0};
  InheritedResolver resolver = {0};
  ASSERT_EQ(
      0,
      resolver_add(&resolver, STR_LIT("synthetic"), &record.token_stream).code);
  SnapshotResolution *memo = NULL, *repeat = NULL;
  ASSERT_EQ(0, resolver_snapshot(&resolver, STR_LIT("synthetic"), &memo).code);
  ASSERT_EQ(0,
            resolver_snapshot(&resolver, STR_LIT("synthetic"), &repeat).code);
  ASSERT_TRUE(memo == repeat);
  ASSERT_EQ(0, (uintptr_t)memo % _Alignof(SnapshotResolution));
  ASSERT_EQ(0, accounting_parse(&record.token_stream, &resolver, &first).code);
  ASSERT_EQ(0, accounting_parse(&record.token_stream, &resolver, &second).code);
  ASSERT_TRUE(first.rows != second.rows);
  ASSERT_EQ(0, (uintptr_t)first.rows % _Alignof(AccountingRow));
  ASSERT_EQ(
      0, memcmp(&before, &record.token_stream.observations[0], sizeof before));
  resolver_destroy(&resolver);
  accounting_result_destroy(&first);
  ASSERT_EQ(5, second.rows[0].tokens.input);
  ASSERT_TRUE(str_equal(second.session_id, STR_LIT("synthetic")));
  accounting_result_destroy(&second);
  record_destroy(&record);
  intern_destroy(&intern);
}
