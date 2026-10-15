#define _DARWIN_C_SOURCE
#include "claude/codec.h"
#include "runner.h"
#include "util/fileio.h"
#include "util/sha256.h"
#include "corpus/subagents.h"
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/wait.h>

static void parsed(ClaudeRecord *r){
  char name[1024];snprintf(name,sizeof name,"%s/synthetic-codec-XXXXXX.jsonl",getenv("TMPDIR"));int fd=mkstemps(name,6);ASSERT_TRUE(fd>=0);
  const char *bytes="{\"type\":\"user\",\"sessionId\":\" synthetic-alias \",\"cwd\":\"/synthetic/codec\",\"gitBranch\":\"synthetic-branch\",\"timestamp\":\"2026-01-02T12:00:00Z\",\"message\":{\"content\":\"<bash-input>synthetic\"}}\n"
    "{\"type\":\"assistant\",\"timestamp\":\"2026-01-02T12:00:01Z\",\"requestId\":\"synthetic-request\",\"sessionId\":\"synthetic-session\",\"message\":{\"id\":\"synthetic-message\",\"model\":\"claude-sonnet-4-6\",\"usage\":{\"input_tokens\":20,\"output_tokens\":5},\"stop_reason\":\"end_turn\",\"content\":[{\"type\":\"text\",\"text\":\"Synthetic answer\"},{\"type\":\"tool_use\",\"id\":\"synthetic-tool\",\"name\":\"mcp__synthetic__lookup\"}]}}\n"
    "{\"type\":\"synthetic-unknown\"}\n";
  ASSERT_EQ(strlen(bytes),(size_t)write(fd,bytes,strlen(bytes)));ASSERT_EQ(0,close(fd));
  DiscoveredLog key={.path={name,(uint32_t)strlen(name)},.size=(int64_t)strlen(bytes),.mtime_ns=123456789,.stat_ok=true,.device=17,.inode=19};
  ASSERT_EQ(ERR_OK,claude_parse(&key,STR_LIT("/synthetic/projects"),STR_LIT("/synthetic/config"),r).code);ASSERT_EQ(0,unlink(name));
}
TEST(claude_codec_round_trips_all_record_facts_and_raw_price_snapshots){
  ClaudeRecord r={0},decoded={0};parsed(&r);ASSERT_EQ(1,r.usage_count);
  r.parent_agent=STR_LIT("synthetic-parent");r.tool_use_id=STR_LIT("synthetic-tool");r.description=STR_LIT("Synthetic child");r.agent_type=STR_LIT("synthetic-type");
  r.custom_title=STR_LIT("Synthetic custom");r.ai_title=STR_LIT("Synthetic AI");r.has_spawn_depth=true;r.spawn_depth=3;
  r.usage_rows[0].unit.claude_price_snapshot=true;r.usage_rows[0].unit.claude_cost_priced=true;r.usage_rows[0].unit.claude_cost_nanos=0;
  r.usage_rows[0].unit.cache_write_1h=((__int128)1<<70)+7;r.tools[0].shell=((__int128)1<<80)+3;
  size_t aliases_capacity=r.aliases.capacity,usage_capacity=r.usage_capacity;
  unsigned char *bytes=NULL;size_t n;ASSERT_EQ(ERR_OK,claude_codec_encode(&r,&bytes,&n).code);ASSERT_EQ(aliases_capacity,r.aliases.capacity);ASSERT_EQ(usage_capacity,r.usage_capacity);ASSERT_EQ(ERR_OK,claude_codec_decode(bytes,n,&decoded).code);
  ASSERT_EQ(0,(uintptr_t)decoded.tools % _Alignof(CorpusTools));
  ASSERT_EQ(0,(uintptr_t)decoded.usage_rows % _Alignof(ClaudeUsageRow));
  ASSERT_TRUE(str_equal(r.key.path,decoded.key.path));ASSERT_EQ(r.key.size,decoded.key.size);ASSERT_EQ(r.key.mtime_ns,decoded.key.mtime_ns);ASSERT_EQ(r.key.inode,decoded.key.inode);ASSERT_EQ(r.key.device,decoded.key.device);
  ASSERT_TRUE(str_equal(r.id,decoded.id));ASSERT_TRUE(str_equal(r.search_root,decoded.search_root));ASSERT_TRUE(str_equal(r.config_dir,decoded.config_dir));
  ASSERT_EQ(r.aliases.count,decoded.aliases.count);ASSERT_TRUE(str_equal(r.aliases.items[0],decoded.aliases.items[0]));
  ASSERT_TRUE(str_equal(r.parent_agent,decoded.parent_agent));ASSERT_TRUE(str_equal(r.tool_use_id,decoded.tool_use_id));ASSERT_TRUE(str_equal(r.description,decoded.description));ASSERT_TRUE(str_equal(r.agent_type,decoded.agent_type));
  ASSERT_TRUE(str_equal(r.custom_title,decoded.custom_title));ASSERT_TRUE(str_equal(r.ai_title,decoded.ai_title));ASSERT_EQ(3,decoded.spawn_depth);ASSERT_TRUE(decoded.has_spawn_depth);
  ASSERT_EQ(1,decoded.turn_count);ASSERT_TRUE(str_equal(r.requests[0].text,decoded.requests[0].text));ASSERT_TRUE(str_equal(r.requests[0].kind,decoded.requests[0].kind));ASSERT_TRUE(str_equal(r.answers[0],decoded.answers[0]));
  ASSERT_TRUE(str_equal(r.turns[0]->end_kind,decoded.turns[0]->end_kind));ASSERT_EQ(r.turns[0]->start_ms.value,decoded.turns[0]->start_ms.value);ASSERT_EQ(r.tools[0].shell,decoded.tools[0].shell);
  ASSERT_EQ(1,decoded.tools[0].mcp.size);ASSERT_EQ(1,decoded.tool_turns.size);ASSERT_TRUE(str_equal(*(Str *)omap_get(&decoded.tool_turns,STR_LIT("synthetic-tool")),r.turns[0]->key));
  ASSERT_EQ(r.rows_dropped.size,decoded.rows_dropped.size);ASSERT_EQ(1,decoded.reader.unknown_types.size);ASSERT_STREQ(r.reader.tail_sha256,decoded.reader.tail_sha256);
  ASSERT_EQ(1,decoded.usage_count);ClaudeUsageRow *a=&r.usage_rows[0],*b=&decoded.usage_rows[0];ASSERT_TRUE(str_equal(a->message_id,b->message_id));ASSERT_TRUE(str_equal(a->request_id,b->request_id));ASSERT_TRUE(str_equal(a->session_id,b->session_id));ASSERT_TRUE(str_equal(a->unit.model_raw,b->unit.model_raw));ASSERT_EQ(a->unit.input,b->unit.input);ASSERT_EQ(a->unit.output,b->unit.output);ASSERT_EQ(a->unit.cache_write_1h,b->unit.cache_write_1h);ASSERT_TRUE(b->unit.claude_price_snapshot);ASSERT_TRUE(b->unit.claude_cost_priced);ASSERT_EQ(0,b->unit.claude_cost_nanos);
  unsigned char *again=NULL;size_t again_n;ASSERT_EQ(ERR_OK,claude_codec_encode(&decoded,&again,&again_n).code);ASSERT_EQ(n,again_n);ASSERT_TRUE(!memcmp(bytes,again,n));free(again);
  for(size_t length=0;length<n;length++){ClaudeRecord invalid={0};ASSERT_EQ(ERR_INVALID,claude_codec_decode(bytes,length,&invalid).code);claude_record_destroy(&invalid);}
  bytes[n-2]^=1;ClaudeRecord invalid={0};ASSERT_EQ(ERR_INVALID,claude_codec_decode(bytes,n,&invalid).code);claude_record_destroy(&invalid);
  free(bytes);claude_record_destroy(&decoded);claude_record_destroy(&r);
}
TEST(claude_codec_rejects_invalid_traversal_without_partial_owner_leaks){
  const char *bodies[]={"[]","[null]","[\"/synthetic/path\",0]","[\"/synthetic/path\",0,0,false,false,0,0,null,null]"};
  for(size_t i=0;i<sizeof bodies/sizeof *bodies;i++){
    char bytes[512];size_t n=strlen(bodies[i]);memcpy(bytes,"CLCD1\n",6);sha256_hex(bodies[i],n,bytes+6);bytes[70]='\n';memcpy(bytes+71,bodies[i],n);
    ClaudeRecord r={0};ASSERT_EQ(ERR_INVALID,claude_codec_decode(bytes,n+71,&r).code);claude_record_destroy(&r);
  }
}
TEST(claude_codec_immutable_v1_fixture_is_decoded_from_scratch){
  /* Read only the immutable source, copy to owned scratch before decoding. */
  char *bytes=NULL;size_t n=0;ASSERT_EQ(ERR_OK,file_read_all("tests/fixtures/claude_codec/synthetic-v1.rec",&bytes,&n).code);
  char path[1024];snprintf(path,sizeof path,"%s/synthetic-v1-XXXXXX.rec",getenv("TMPDIR"));int fd=mkstemps(path,4);ASSERT_TRUE(fd>=0);ASSERT_EQ(n,(size_t)write(fd,bytes,n));ASSERT_EQ(0,close(fd));free(bytes);bytes=NULL;
  ASSERT_EQ(ERR_OK,file_read_all(path,&bytes,&n).code);ClaudeRecord r={0};ASSERT_EQ(ERR_OK,claude_codec_decode(bytes,n,&r).code);
  ASSERT_TRUE(str_equal(r.id,STR_LIT("synthetic-session")));ASSERT_TRUE(str_equal(r.search_root,STR_LIT("/synthetic/config/projects")));ASSERT_TRUE(str_equal(r.config_dir,STR_LIT("/synthetic/config")));
  ASSERT_EQ(2,r.aliases.count);ASSERT_TRUE(str_equal(r.aliases.items[0],STR_LIT(" synthetic-alias ")));ASSERT_TRUE(str_equal(r.aliases.items[1],STR_LIT("synthetic-e\xcc\x81")));
  ASSERT_EQ(2,r.usage_count);ASSERT_TRUE(r.usage_rows[0].unit.claude_price_snapshot);ASSERT_TRUE(r.usage_rows[0].unit.claude_cost_priced);ASSERT_EQ(0,r.usage_rows[0].unit.claude_cost_nanos);ASSERT_TRUE(r.usage_rows[1].unit.claude_price_snapshot);ASSERT_TRUE(r.usage_rows[1].unit.claude_cost_priced);ASSERT_EQ(19,r.usage_rows[1].unit.claude_cost_nanos);
  ASSERT_EQ(r.usage_rows[0].unit.input,r.usage_rows[1].unit.input);ASSERT_TRUE(str_equal(r.usage_rows[0].message_id,r.usage_rows[1].message_id));
  claude_record_destroy(&r);free(bytes);ASSERT_EQ(0,unlink(path));
}
TEST(claude_codec_aligns_arrays_and_wide_maps_across_string_offsets){
  ClaudeRecord r={0};parsed(&r);const char text[]="Synthetic varying alignment text with fictional bytes";
  for(size_t offset=0;offset<32;offset++){
    r.description=(Str){text,(uint32_t)offset};unsigned char *bytes=NULL;size_t n=0;ClaudeRecord decoded={0};
    ASSERT_EQ(ERR_OK,claude_codec_encode(&r,&bytes,&n).code);ASSERT_EQ(ERR_OK,claude_codec_decode(bytes,n,&decoded).code);
    ASSERT_EQ(0,(uintptr_t)decoded.tools % _Alignof(CorpusTools));ASSERT_EQ(0,(uintptr_t)decoded.turns[0] % _Alignof(TurnFact));
    ASSERT_EQ(0,(uintptr_t)decoded.usage_rows % _Alignof(ClaudeUsageRow));ASSERT_EQ(0,(uintptr_t)&decoded.usage_rows[0].unit % _Alignof(UsageUnit));
    ASSERT_EQ(0,(uintptr_t)omap_get(&decoded.tools[0].mcp,STR_LIT("synthetic")) % _Alignof(__int128));
    free(bytes);claude_record_destroy(&decoded);
  }
  claude_record_destroy(&r);
}

/* Recompute the checksum after intentionally changing a well-formed traversal:
 * these tests must reach the typed map decoder rather than the checksum guard. */
static void malformed_map(const char *map_name,bool truncate,bool invalid_key){
  ClaudeRecord r={0};parsed(&r);__int128 count=1;
  Omap *map=!strcmp(map_name,"mcp")?&r.tools[0].mcp:&r.tools[0].other;
  ASSERT_EQ(ERR_OK,omap_put(map,STR_LIT("synthetic-invalid-wide-key"),&count).code);
  unsigned char *bytes=NULL;size_t n=0;ASSERT_EQ(ERR_OK,claude_codec_encode(&r,&bytes,&n).code);
  bytes=realloc(bytes,n+1);ASSERT_TRUE(bytes);bytes[n]=0;
  char *key=strstr((char *)bytes+71,"\"synthetic-invalid-wide-key\"");ASSERT_TRUE(key);
  size_t prefix=(size_t)(key-(char *)bytes),old=strlen("\"synthetic-invalid-wide-key\"");
  if(invalid_key){
    memcpy(key,"true",4);
    if(truncate){key[4]=']';n=prefix+5;}
    else {memmove(key+4,key+old,n-prefix-old);n-=old-4;}
  }else {key[old]=']';n=prefix+old+1;}
  sha256_hex(bytes+71,n-71,(char *)bytes+6);bytes[70]='\n';
  ClaudeRecord decoded={0};ASSERT_EQ(ERR_INVALID,claude_codec_decode(bytes,n,&decoded).code);
  claude_record_destroy(&decoded);free(bytes);claude_record_destroy(&r);
}
TEST(claude_codec_rejects_malformed_mcp_key_with_valid_checksum){malformed_map("mcp",false,true);}
TEST(claude_codec_rejects_malformed_other_key_with_valid_checksum){malformed_map("other",false,true);}
TEST(claude_codec_rejects_mcp_traversal_ending_at_invalid_key){malformed_map("mcp",true,true);}
TEST(claude_codec_rejects_other_traversal_ending_at_invalid_key){malformed_map("other",true,true);}
static void *readonly_copy(const void *source,size_t n,size_t *span){
  long page=sysconf(_SC_PAGESIZE);ASSERT_TRUE(page>0);*span=(n+(size_t)page-1)/(size_t)page*(size_t)page;
  void *copy=mmap(NULL,*span,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0);ASSERT_TRUE(copy!=MAP_FAILED);
  memcpy(copy,source,n);ASSERT_EQ(0,mprotect(copy,*span,PROT_READ));return copy;
}
TEST(claude_codec_encoder_accepts_physically_readonly_record_and_usage_rows){
  ClaudeRecord r={0};parsed(&r);size_t row_span,record_span;
  ClaudeUsageRow *rows=readonly_copy(r.usage_rows,r.usage_count*sizeof *rows,&row_span);
  ClaudeRecord copy=r;copy.usage_rows=rows;ClaudeRecord *protected=readonly_copy(&copy,sizeof copy,&record_span);
  pid_t child=fork();ASSERT_TRUE(child>=0);
  if(!child){unsigned char *bytes=NULL;size_t n=0;Err e=claude_codec_encode(protected,&bytes,&n);free(bytes);_exit(e.code?1:0);}
  int status=0;ASSERT_EQ(child,waitpid(child,&status,0));
  ASSERT_EQ(0,munmap(protected,record_span));ASSERT_EQ(0,munmap(rows,row_span));claude_record_destroy(&r);
  ASSERT_TRUE(WIFEXITED(status));ASSERT_EQ(0,WEXITSTATUS(status));
}
TEST(claude_codec_rejects_mcp_traversal_ending_after_valid_key){malformed_map("mcp",true,false);}
TEST(claude_codec_rejects_other_traversal_ending_after_valid_key){malformed_map("other",true,false);}
