#define _DARWIN_C_SOURCE
#include "claude/metadata.h"
#include "corpus/subagents.h"
#include "runner.h"
#include "util/fileio.h"
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>
static void write_file(const char *path,const char *bytes) {
  FILE *f=fopen(path,"w"); ASSERT_TRUE(f);
  ASSERT_TRUE(fputs(bytes,f)>=0); ASSERT_EQ(0,fclose(f));
}
static void scratch(char *out,size_t n) {
  snprintf(out,n,"%s/synthetic-metadata-XXXXXX",getenv("COLOPHON_HOME"));
  ASSERT_TRUE(mkdtemp(out));
}
TEST(claude_children_share_stable_chronological_ordering) {
  Corpus c={0};SessionModel parent={0};
  SessionModel a={.id=STR_LIT("synthetic-a"),.start_ms={true,20}},
    b={.id=STR_LIT("synthetic-b"),.start_ms={true,10}},
    d={.id=STR_LIT("synthetic-d"),.start_ms={true,10}},
    unknown={.id=STR_LIT("synthetic-unknown")};
  SessionModel *children[]={&unknown,&a,&b,&d};
  for(size_t i=0;i<4;i++) {
    ASSERT_EQ(ERR_OK,omap_put(&c.sessions,children[i]->id,children[i]).code);
    ASSERT_EQ(ERR_OK,corpus_strings_add(&c.arena,&parent.children,children[i]->id).code);
  }
  ASSERT_EQ(ERR_OK,corpus_children_order(&parent,&c.sessions).code);
  ASSERT_TRUE(str_equal(parent.children.items[0],b.id));
  ASSERT_TRUE(str_equal(parent.children.items[1],d.id));
  ASSERT_TRUE(str_equal(parent.children.items[2],a.id));
  ASSERT_TRUE(str_equal(parent.children.items[3],unknown.id));
  corpus_destroy(&c);
}
TEST(claude_sidecar_fields_are_independent_and_prefix_is_ignored) {
  char root[1024],directory[1200],path[1400],sidecar[1400];scratch(root,sizeof root);
  snprintf(directory,sizeof directory,"%s/synthetic-parent/subagents",root);
  ASSERT_EQ(ERR_OK,file_mkdir_parents(directory).code);
  snprintf(path,sizeof path,"%s/agent-synthetic-child.jsonl",directory);
  snprintf(sidecar,sizeof sidecar,"%s/agent-synthetic-child.meta.json",directory);
  write_file(path,"{\"type\":\"user\",\"message\":{\"content\":\"Synthetic prompt\"}}\n");
  const char *cases[]={
    "{\"parentAgentId\":42,\"toolUseId\":\"synthetic-tool\",\"spawnDepth\":3,\"description\":false,\"agentType\":\"synthetic-worker\"}",
    "{\"parentAgentId\":\"synthetic-parent-agent\",\"toolUseId\":false,\"spawnDepth\":1.5,\"description\":\"Synthetic label\",\"agentType\":[]}",
    "{\"parentAgentId\":\"synthetic/invalid\",\"spawnDepth\":-1}","{"};
  for(size_t i=0;i<4;i++) {
    write_file(sidecar,cases[i]); ClaudeRecord r={0};
    DiscoveredLog key={.path={path,(uint32_t)strlen(path)}};
    ASSERT_EQ(ERR_OK,claude_parse(&key,(Str){0},(Str){0},&r).code);
    if(i==0) {
      ASSERT_FALSE(r.parent_agent.p); ASSERT_TRUE(r.has_spawn_depth);
      ASSERT_EQ(3,r.spawn_depth); ASSERT_FALSE(r.description.p);
      ASSERT_TRUE(str_equal(r.tool_use_id,STR_LIT("synthetic-tool")));
      ASSERT_TRUE(str_equal(r.agent_type,STR_LIT("synthetic-worker")));
    } else if(i==1) {
      ASSERT_TRUE(str_equal(r.parent_agent,STR_LIT("synthetic-parent-agent")));
      ASSERT_TRUE(str_equal(r.description,STR_LIT("Synthetic label")));
      ASSERT_FALSE(r.tool_use_id.p); ASSERT_FALSE(r.has_spawn_depth);
      ASSERT_FALSE(r.agent_type.p);
    } else { ASSERT_FALSE(r.parent_agent.p); ASSERT_FALSE(r.has_spawn_depth); }
    claude_record_destroy(&r);
  }
  ASSERT_EQ(0,unlink(sidecar));
  snprintf(sidecar,sizeof sidecar,"%s/agent-synthetic-child.prefix.json",directory);
  write_file(sidecar,"{\"parentAgentId\":\"synthetic-missing\",\"spawnDepth\":9}");
  ClaudeRecord r={0};DiscoveredLog key={.path={path,(uint32_t)strlen(path)}};
  ASSERT_EQ(ERR_OK,claude_parse(&key,(Str){0},(Str){0},&r).code);
  ASSERT_FALSE(r.parent_agent.p); ASSERT_FALSE(r.has_spawn_depth);
  claude_record_destroy(&r);
}
TEST(claude_graph_breaks_cycles_and_infers_depth_without_codex_records) {
  ClaudeRecord r[6]={0};
  const Str ids[]={STR_LIT("synthetic-root"),STR_LIT("synthetic-root/agent-a"),
    STR_LIT("synthetic-root/agent-b"),STR_LIT("synthetic-root/agent-c"),
    STR_LIT("synthetic-root/agent-d"),STR_LIT("synthetic-root/agent-e")};
  for(size_t i=0;i<6;i++){r[i].id=ids[i];if(i)r[i].parent_session=ids[0];}
  r[2].parent_agent=STR_LIT("a");r[3].parent_agent=STR_LIT("d");r[4].parent_agent=STR_LIT("c");
  r[5].parent_agent=STR_LIT("missing");
  r[1].first_ms=(MaybeMs){true,20};r[2].first_ms=(MaybeMs){true,10};
  Corpus c={0};CorpusStrings collisions={0};
  ASSERT_EQ(ERR_OK,claude_corpus_add(r,6,0,&c,&collisions).code);
  SessionModel *root=omap_get(&c.sessions,ids[0]),*a=omap_get(&c.sessions,ids[1]),*b=omap_get(&c.sessions,ids[2]);
  ASSERT_EQ(1,root->children.count);ASSERT_EQ(1,a->children.count);
  ASSERT_TRUE(b->has_depth);ASSERT_EQ(2,b->depth);
  ASSERT_EQ(3,c.claude_orphaned_subagents.count);ASSERT_EQ(0,c.orphaned_subagents.count);
  for(size_t i=3;i<6;i++){SessionModel *s=omap_get(&c.sessions,ids[i]);ASSERT_TRUE(s->flags&F_ORPHAN);}
  corpus_destroy(&c);
}
TEST(claude_titles_choose_last_custom_then_ai_then_prompt) {
  char root[1024],path[1200];scratch(root,sizeof root);
  snprintf(path,sizeof path,"%s/synthetic-title.jsonl",root);
  const char *parts[]={
    "{\"type\":\"user\",\"message\":{\"content\":\"Synthetic prompt\"}}\n",
    "{\"type\":\"ai-title\",\"aiTitle\":\"Synthetic AI old\"}\n{\"type\":\"ai-title\",\"aiTitle\":\"Synthetic AI last\"}\n",
    "{\"type\":\"custom-title\",\"customTitle\":\"Synthetic custom old\"}\n{\"type\":\"custom-title\",\"customTitle\":\"Synthetic custom last\"}\n"};
  const char *titles[]={"Synthetic prompt","Synthetic AI last","Synthetic custom last"};
  char bytes[2048]="";
  for(size_t i=0;i<3;i++) {
    strcat(bytes,parts[i]);write_file(path,bytes);
    ClaudeRecord r={0};DiscoveredLog key={.path={path,(uint32_t)strlen(path)},.size=(int64_t)strlen(bytes)};
    ASSERT_EQ(ERR_OK,claude_parse(&key,(Str){0},(Str){0},&r).code);
    Corpus c={0};CorpusStrings collisions={0};
    ASSERT_EQ(ERR_OK,claude_corpus_add(&r,1,0,&c,&collisions).code);
    SessionModel *s=c.sessions.first->value;
    ASSERT_STREQ(titles[i],s->title.p);
    corpus_destroy(&c);claude_record_destroy(&r);
  }
}
TEST(claude_latest_empty_invalid_or_missing_titles_clear_earlier_candidates) {
  char root[1024],path[1200];scratch(root,sizeof root);
  snprintf(path,sizeof path,"%s/synthetic-title-clear.jsonl",root);
  const char *suffixes[]={
    "{\"type\":\"custom-title\",\"customTitle\":\"\"}\n",
    "{\"type\":\"custom-title\",\"customTitle\":false}\n",
    "{\"type\":\"custom-title\"}\n",
    "{\"type\":\"custom-title\",\"customTitle\":\"  \"}\n",
    "{\"type\":\"custom-title\"}\n{\"type\":\"ai-title\"}\n",
    "{\"type\":\"custom-title\"}\n{\"type\":\"ai-title\",\"aiTitle\":false}\n",
    "{\"type\":\"custom-title\"}\n{\"type\":\"ai-title\",\"aiTitle\":\"\"}\n"};
  for(size_t i=0;i<7;i++) {
    char bytes[2048]="{\"type\":\"user\",\"message\":{\"content\":\"Synthetic prompt\"}}\n"
      "{\"type\":\"ai-title\",\"aiTitle\":\"Synthetic AI\"}\n"
      "{\"type\":\"custom-title\",\"customTitle\":\"Synthetic old custom\"}\n";
    strcat(bytes,suffixes[i]);write_file(path,bytes);
    ClaudeRecord r={0};DiscoveredLog key={.path={path,(uint32_t)strlen(path)},.size=(int64_t)strlen(bytes)};
    ASSERT_EQ(ERR_OK,claude_parse(&key,(Str){0},(Str){0},&r).code);
    Corpus c={0};CorpusStrings collisions={0};
    ASSERT_EQ(ERR_OK,claude_corpus_add(&r,1,0,&c,&collisions).code);
    SessionModel *s=c.sessions.first->value;
    ASSERT_STREQ(i<4?"Synthetic AI":"Synthetic prompt",s->title.p);
    corpus_destroy(&c);claude_record_destroy(&r);
  }
}
TEST(claude_desktop_independent_fields_clocks_fallback_and_disabled) {
  char root[1024],directory[1400],path[1600];scratch(root,sizeof root);
  snprintf(directory,sizeof directory,"%s/claude-code-sessions/synthetic-account/synthetic-org",root);
  ASSERT_EQ(ERR_OK,file_mkdir_parents(directory).code);
  snprintf(path,sizeof path,"%s/local_.json",directory);
  write_file(path,"{\"cliSessionId\":\"synthetic-metadata\",\"title\":false,\"isArchived\":true,\"cwd\":\"/synthetic/metadata\",\"createdAt\":\"2026-01-02T12:00:00Z\",\"lastActivityAt\":1767355203000}");
  ClaudeScan scan={.desktop_dir={root,(uint32_t)strlen(root)}};
  ASSERT_EQ(ERR_OK,claude_metadata_load(&scan).code);ASSERT_EQ(1,scan.desktop_count);
  ASSERT_EQ(1,scan.metadata_errors.count);
  ClaudeRecord r={.id=STR_LIT("synthetic-metadata")};Corpus c={0};CorpusStrings collisions={0};
  ASSERT_EQ(ERR_OK,claude_corpus_add(&r,1,0,&c,&collisions).code);
  ASSERT_EQ(ERR_OK,claude_metadata_apply(&scan,&c).code);
  SessionModel *s=c.sessions.first->value;ASSERT_TRUE(s->archived);
  ASSERT_TRUE(str_equal(s->meta.cwd.value.s,STR_LIT("/synthetic/metadata")));
  ASSERT_TRUE(s->start_ms.present);ASSERT_TRUE(s->end_ms.present);
  ASSERT_EQ(1767355200000,s->start_ms.value);ASSERT_EQ(1767355203000,s->end_ms.value);
  ASSERT_EQ(0,scan.desktop_without_transcripts);
  corpus_destroy(&c);claude_scan_destroy(&scan);
  scan=(ClaudeScan){.desktop_dir={root,(uint32_t)strlen(root)},.disabled=true};
  ASSERT_EQ(ERR_OK,claude_metadata_load(&scan).code);ASSERT_EQ(0,scan.desktop_count);
  claude_scan_destroy(&scan);
}
