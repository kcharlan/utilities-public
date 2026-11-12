#define _DARWIN_C_SOURCE
#include "claude/store.h"
#include "claude/codec.h"
#include "cli/run.h"
#include "runner.h"
#include "util/fileio.h"
#include "cache/cache.h"
#include <dirent.h>

#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>

typedef struct {char base[1024],root[1200],runtime[1200],one[1400],two[1400];} Fixture;
static Str str(const char *s){return (Str){s,(uint32_t)strlen(s)};}
static void write_text(const char *path,const char *text){FILE *f=fopen(path,"w");ASSERT_TRUE(f);ASSERT_TRUE(fputs(text,f)>=0);ASSERT_EQ(0,fclose(f));}
static void source(const char *path){write_text(path,"{\"type\":\"user\",\"sessionId\":\"  synthetic-alias  \",\"message\":{\"content\":\"Synthetic store request\"}}\n");}
static void fixture(Fixture *f){
  snprintf(f->base,sizeof f->base,"%s/synthetic-claude-store-XXXXXX",getenv("TMPDIR"));ASSERT_TRUE(mkdtemp(f->base));
  char *real=realpath(f->base,NULL);ASSERT_TRUE(real);snprintf(f->base,sizeof f->base,"%s",real);free(real);
  snprintf(f->root,sizeof f->root,"%s/projects",f->base);ASSERT_EQ(0,mkdir(f->root,0700));
  snprintf(f->runtime,sizeof f->runtime,"%s/runtime",f->base);
  snprintf(f->one,sizeof f->one,"%s/synthetic-one.jsonl",f->root);snprintf(f->two,sizeof f->two,"%s/synthetic-two.jsonl",f->root);
  source(f->one);source(f->two);
}
static void snapshot(Fixture *f,bool rebuild,ClaudeScan *s,ClaudeStore *store){
  *s=(ClaudeScan){0};ClaudeRoot *r=NULL;
  ASSERT_EQ(ERR_OK,arena_alloc(&s->arena,sizeof *r,_Alignof(ClaudeRoot),(void **)&r).code);
  Str root;ASSERT_EQ(ERR_OK,str_copy(&s->arena,str(f->root),&root).code);
  struct stat st;bool present=!stat(f->root,&st)&&S_ISDIR(st.st_mode)&&!access(f->root,R_OK|X_OK);
  *r=(ClaudeRoot){.path=root,.present=present,.complete=true};s->roots=r;s->root_count=1;s->present=present;
  ASSERT_EQ(ERR_OK,claude_store_inspect(f->runtime,s,rebuild,store).code);s->store=store;
  ASSERT_EQ(ERR_OK,claude_scan(s,NULL).code);
  ASSERT_EQ(ERR_OK,claude_store_reconcile(store,s,NULL).code);
}
static void close_snapshot(ClaudeScan *s,ClaudeStore *store){claude_scan_destroy(s);claude_store_destroy(store);}
static void seed(Fixture *f){ClaudeScan s={0};ClaudeStore store={0};snapshot(f,false,&s,&store);ASSERT_EQ(ERR_OK,claude_store_commit(&store,&s,NULL).code);close_snapshot(&s,&store);}
static void record_path(Fixture *f,const char *source_path,const char *kind,char out[1600]){char root[69],key[69];cache_entry_name(str(f->root),root);root[64]=0;cache_entry_name(str(source_path),key);snprintf(out,1600,"%s/%s/%s/%s",f->runtime,kind,root,key);}
static void installed(Fixture *f,const char *source_path,char out[1600]){record_path(f,source_path,"cache-claude",out);}
static char *read_bytes(const char *path,size_t *n){char *bytes=NULL;ASSERT_EQ(ERR_OK,file_read_all(path,&bytes,n).code);return bytes;}
static void same_bytes(const char *path,const char *before,size_t n){size_t after_n;char *after=read_bytes(path,&after_n);ASSERT_EQ(n,after_n);ASSERT_TRUE(!memcmp(before,after,n));free(after);}
static bool recovery_bytes(Fixture *f,const char *source_path,const char *before,size_t n){
  char live[1600],retained[1600];installed(f,source_path,live);record_path(f,source_path,"claude-retained",retained);
  struct stat a,b;bool has_live=!stat(live,&a),has_retained=!stat(retained,&b);ASSERT_TRUE(has_live!=has_retained);
  const char *path=has_live?live:retained;same_bytes(path,before,n);ASSERT_EQ(0600,(has_live?a.st_mode:b.st_mode)&0777);
  char directory[1600];snprintf(directory,sizeof directory,"%s",path);*strrchr(directory,'/')=0;struct stat d;ASSERT_EQ(0,stat(directory,&d));ASSERT_EQ(0700,d.st_mode&0777);
  return has_retained;
}
static void fault(const char *point){ASSERT_EQ(0,setenv("COLOPHON_TEST_FAULT",point,1));}
static void clear_fault(void){ASSERT_EQ(0,unsetenv("COLOPHON_TEST_FAULT"));}
TEST(claude_store_all_candidate_rechecks_precede_root_mutations){
  Fixture f;fixture(&f);seed(&f);char one[1600],two[1600];installed(&f,f.one,one);installed(&f,f.two,two);
  size_t n1,n2;char *b1=read_bytes(one,&n1),*b2=read_bytes(two,&n2);
  ASSERT_EQ(0,unlink(f.one));ASSERT_EQ(0,unlink(f.two));ClaudeScan s={0};ClaudeStore store={0};snapshot(&f,true,&s,&store);
  ASSERT_EQ(2,s.retained);source(f.two); /* Last candidate changed; first must not move. */
  ASSERT_EQ(ERR_OK,claude_store_commit(&store,&s,NULL).code);
  same_bytes(one,b1,n1);same_bytes(two,b2,n2);close_snapshot(&s,&store);
  snapshot(&f,true,&s,&store);ASSERT_EQ(1,s.retained);ASSERT_EQ(ERR_OK,claude_store_commit(&store,&s,NULL).code);close_snapshot(&s,&store);
  free(b1);free(b2);
}
TEST(claude_store_interruption_boundaries_recover_every_record){
  const char *points[]={"claude_commit_before_move","claude_commit_after_move:1","claude_commit_after_move:2"};
  for(size_t i=0;i<sizeof points/sizeof *points;i++){
    Fixture f;fixture(&f);seed(&f);char path[1600],second[1600];installed(&f,f.one,path);installed(&f,f.two,second);size_t n,n2;char *before=read_bytes(path,&n),*before2=read_bytes(second,&n2);
    ASSERT_EQ(0,unlink(f.one));ASSERT_EQ(0,unlink(f.two));ClaudeScan s={0};ClaudeStore store={0};snapshot(&f,true,&s,&store);
    fault(points[i]);ASSERT_EQ(ERR_IO,claude_store_commit(&store,&s,NULL).code);clear_fault();
    size_t moved=recovery_bytes(&f,f.one,before,n)+recovery_bytes(&f,f.two,before2,n2);ASSERT_EQ(i,moved);
    close_snapshot(&s,&store);
    snapshot(&f,true,&s,&store);ASSERT_EQ(2,s.retained);ASSERT_EQ(2,s.count);
    for(size_t j=0;j<s.count;j++){ASSERT_EQ(1,s.records[j].turn_count);ASSERT_EQ(1,s.records[j].aliases.count);}
    ASSERT_EQ(ERR_OK,claude_store_commit(&store,&s,NULL).code);close_snapshot(&s,&store);
    ASSERT_TRUE(recovery_bytes(&f,f.one,before,n));ASSERT_TRUE(recovery_bytes(&f,f.two,before2,n2));
    free(before);free(before2);
  }
}
TEST(claude_store_supersession_interruptions_keep_decodable_copy){
  const char *points[]={"claude_commit_before_install","claude_commit_after_install","claude_commit_before_retained_remove"};
  for(size_t i=0;i<sizeof points/sizeof *points;i++){
    Fixture f;fixture(&f);seed(&f);ASSERT_EQ(0,unlink(f.one));
    ClaudeScan s={0};ClaudeStore store={0};snapshot(&f,false,&s,&store);ASSERT_EQ(ERR_OK,claude_store_commit(&store,&s,NULL).code);close_snapshot(&s,&store);
    source(f.one);snapshot(&f,true,&s,&store);ASSERT_EQ(0,s.retained);
    fault(points[i]);ASSERT_EQ(ERR_IO,claude_store_commit(&store,&s,NULL).code);clear_fault();close_snapshot(&s,&store);
    snapshot(&f,false,&s,&store);ASSERT_EQ(2,s.count);ASSERT_EQ(0,s.retained);ASSERT_EQ(ERR_OK,claude_store_commit(&store,&s,NULL).code);close_snapshot(&s,&store);
    ASSERT_EQ(0,unlink(f.one));snapshot(&f,true,&s,&store);ASSERT_EQ(1,s.retained);close_snapshot(&s,&store);
  }
}
TEST(claude_store_traversal_interruption_has_no_moves){
  Fixture f;fixture(&f);seed(&f);char path[1600];installed(&f,f.one,path);size_t n;char *before=read_bytes(path,&n);
  ASSERT_EQ(0,unlink(f.one));ClaudeScan s={0};ClaudeStore store={0};snapshot(&f,true,&s,&store);
  volatile sig_atomic_t stop=1;ASSERT_EQ(ERR_IO,claude_store_reconcile(&store,&s,&stop).code);ASSERT_EQ(ERR_IO,claude_store_commit(&store,&s,&stop).code);
  same_bytes(path,before,n);close_snapshot(&s,&store);free(before);
}
TEST(claude_deletion_proof_rejects_other_errors_and_unreadable_ancestors){
  Fixture f;fixture(&f);ASSERT_FALSE(claude_path_deleted(f.one));ASSERT_EQ(0,unlink(f.one));ASSERT_TRUE(claude_path_deleted(f.one));
  ASSERT_EQ(0,chmod(f.root,0));ASSERT_FALSE(claude_path_deleted(f.one));ASSERT_EQ(0,chmod(f.root,0700));
  ASSERT_EQ(0,unlink(f.two));ASSERT_EQ(0,rmdir(f.root));ASSERT_TRUE(claude_path_deleted(f.one));
  write_text(f.root,"synthetic ancestor is a file");ASSERT_FALSE(claude_path_deleted(f.one));
}
TEST(claude_store_recovery_copy_of_same_path_is_replayed_once){
  Fixture f;fixture(&f);seed(&f);ASSERT_EQ(0,unlink(f.one));ClaudeScan s={0};ClaudeStore store={0};snapshot(&f,false,&s,&store);ASSERT_EQ(ERR_OK,claude_store_commit(&store,&s,NULL).code);close_snapshot(&s,&store);
  source(f.one);snapshot(&f,true,&s,&store);fault("claude_commit_before_retained_remove");ASSERT_EQ(ERR_IO,claude_store_commit(&store,&s,NULL).code);clear_fault();close_snapshot(&s,&store);
  ASSERT_EQ(0,unlink(f.one));snapshot(&f,true,&s,&store);
  ASSERT_EQ(2,s.count);ASSERT_EQ(1,s.retained); /* No duplicate same-path replay. */
  ASSERT_EQ(ERR_OK,claude_store_commit(&store,&s,NULL).code);close_snapshot(&s,&store);
}
TEST(claude_store_changed_evidence_preserves_live_updates_in_same_root){
  Fixture f;fixture(&f);char third[1400],cache[1600];snprintf(third,sizeof third,"%s/synthetic-third.jsonl",f.root);source(third);seed(&f);installed(&f,third,cache);size_t n;char *before=read_bytes(cache,&n);
  ASSERT_EQ(0,unlink(f.one));ASSERT_EQ(0,unlink(f.two));write_text(third,"{\"type\":\"user\",\"message\":{\"content\":\"Synthetic changed live transcript\"}}\n");
  ClaudeScan s={0};ClaudeStore store={0};snapshot(&f,true,&s,&store);ASSERT_EQ(2,s.retained);source(f.two);
  ASSERT_EQ(ERR_OK,claude_store_commit(&store,&s,NULL).code);same_bytes(cache,before,n);close_snapshot(&s,&store);free(before);
}
TEST(claude_store_aliases_remain_available_for_collision_skipped_candidates){
  Fixture f;fixture(&f);seed(&f);ASSERT_EQ(0,unlink(f.one));ClaudeScan s={0};ClaudeStore store={0};snapshot(&f,true,&s,&store);
  ASSERT_EQ(ERR_OK,claude_scan_aliases(&s).code);CorpusStrings *owners=omap_get(&s.history_aliases,STR_LIT("  synthetic-alias  "));ASSERT_TRUE(owners);ASSERT_EQ(2,owners->count);
  Corpus c={0};SessionModel codex={.id=STR_LIT("synthetic-one")};ASSERT_EQ(ERR_OK,omap_put(&c.sessions,codex.id,&codex).code);CorpusStrings collisions={0};
  ASSERT_EQ(ERR_OK,claude_corpus_add(s.records,s.count,0,&c,&collisions).code);ASSERT_EQ(1,collisions.count);ASSERT_EQ(2,owners->count);
  corpus_destroy(&c);close_snapshot(&s,&store);
}
TEST(claude_cli_failed_output_does_not_commit_candidates_during_rebuild){
  Fixture f;fixture(&f);seed(&f);char path[1600];installed(&f,f.one,path);size_t n;char *before=read_bytes(path,&n);
  ASSERT_EQ(0,unlink(f.one));char *prior=strdup(getenv("COLOPHON_HOME"));ASSERT_TRUE(prior);ASSERT_EQ(0,setenv("COLOPHON_HOME",f.runtime,1));
  Args args={.codex_home="/synthetic/absent-codex",.claude_home=f.base,.rebuild=true,.offline=true,.no_open=true};
  fault("original_page_failure");ASSERT_EQ(1,cli_run(&args));clear_fault();same_bytes(path,before,n);
  ASSERT_EQ(0,setenv("COLOPHON_HOME",prior,1));free(prior);free(before);
  ClaudeScan s={0};ClaudeStore store={0};snapshot(&f,true,&s,&store);ASSERT_EQ(1,s.retained);close_snapshot(&s,&store);
}
TEST(claude_store_live_deletion_after_reconciliation_waits_for_next_scan){
  Fixture f;fixture(&f);ClaudeScan s={0};ClaudeStore store={0};snapshot(&f,true,&s,&store);ASSERT_EQ(0,s.retained);ASSERT_EQ(0,unlink(f.one));
  ASSERT_EQ(ERR_OK,claude_store_commit(&store,&s,NULL).code);close_snapshot(&s,&store);
  snapshot(&f,true,&s,&store);ASSERT_EQ(1,s.retained);ASSERT_EQ(2,s.count);ASSERT_EQ(ERR_OK,claude_store_commit(&store,&s,NULL).code);close_snapshot(&s,&store);
}
TEST(claude_store_fingerprint_error_initializes_output_ownership){
  Fixture f;fixture(&f);seed(&f);ClaudeScan s={0};ClaudeStore store={0};snapshot(&f,false,&s,&store);
  ClaudeRecord output;memset(&output,0xa5,sizeof output);DiscoveredLog key=s.records[0].key;
  ASSERT_EQ(0,chmod(key.path.p,0));bool hit=false;
  Err e=claude_store_get(&store,&key,&output,&hit);ASSERT_EQ(0,chmod(key.path.p,0600));
  ASSERT_EQ(ERR_IO,e.code);ASSERT_FALSE(hit);ASSERT_TRUE(output.arena.head==NULL);ASSERT_TRUE(output.tools==NULL);ASSERT_EQ(0,output.turn_count);
  claude_record_destroy(&output);close_snapshot(&s,&store);
}
TEST(claude_store_legacy_live_records_reparse_without_losing_retained_facts){
  Fixture f; fixture(&f); seed(&f);
  char path[1600]; installed(&f,f.one,path);
  size_t n; char *bytes=read_bytes(path,&n); ClaudeRecord r={0};
  ASSERT_EQ(ERR_OK,claude_codec_decode(bytes,n,&r).code); free(bytes);
  r.reader_facts=false;
  unsigned char *old=NULL; size_t old_n=0;
  ASSERT_EQ(ERR_OK,claude_codec_encode(&r,&old,&old_n).code);
  FILE *file=fopen(path,"wb"); ASSERT_TRUE(file);
  ASSERT_EQ(old_n,fwrite(old,1,old_n,file)); ASSERT_EQ(0,fclose(file));
  claude_record_destroy(&r);
  ClaudeScan s={0}; ClaudeStore store={0}; snapshot(&f,false,&s,&store);
  ASSERT_EQ(1,s.parsed); ASSERT_EQ(1,s.cached);
  close_snapshot(&s,&store);
  ASSERT_EQ(0,unlink(f.one)); snapshot(&f,false,&s,&store);
  ASSERT_EQ(1,s.retained);
  bool found=false;
  for(size_t i=0;i<s.count;i++)if(str_equal(s.records[i].key.path,str(f.one))){
    found=true; ASSERT_EQ(1,s.records[i].turn_count); ASSERT_FALSE(s.records[i].reader_facts);
  }
  ASSERT_TRUE(found); ASSERT_EQ(ERR_OK,claude_store_commit(&store,&s,NULL).code);
  ASSERT_TRUE(recovery_bytes(&f,f.one,(const char *)old,old_n));
  close_snapshot(&s,&store); free(old);
}
TEST(claude_store_newly_corrupt_retained_copy_is_not_removed_at_live_commit){
  Fixture f;fixture(&f);seed(&f);ASSERT_EQ(0,unlink(f.one));ClaudeScan s={0};ClaudeStore store={0};snapshot(&f,false,&s,&store);ASSERT_EQ(ERR_OK,claude_store_commit(&store,&s,NULL).code);close_snapshot(&s,&store);
  char root[69],key[69],retained[1600];cache_entry_name(str(f.root),root);root[64]=0;cache_entry_name(str(f.one),key);snprintf(retained,sizeof retained,"%s/claude-retained/%s/%s",f.runtime,root,key);
  source(f.one);snapshot(&f,false,&s,&store);const char *bad="synthetic corruption after reconciliation";write_text(retained,bad);
  ASSERT_EQ(ERR_OK,claude_store_commit(&store,&s,NULL).code);same_bytes(retained,bad,strlen(bad));close_snapshot(&s,&store);
}

/* A path index must retain all entries, not overwrite earlier same-path copies. */
TEST(claude_store_path_index_covers_large_inventory){
  Fixture f;fixture(&f);
  char path[1400];
  for(int i=0;i<240;i++){snprintf(path,sizeof path,"%s/synthetic-%03d.jsonl",f.root,i);source(path);}
  seed(&f);
  ClaudeScan s={0};ClaudeStore store={0};snapshot(&f,false,&s,&store);
  ASSERT_EQ(242,store.path_index.size);
  for(size_t i=0;i<s.count;i++){
    ClaudeRecord out={0};bool hit=false;DiscoveredLog key=s.records[i].key;
    ASSERT_EQ(ERR_OK,claude_store_get(&store,&key,&out,&hit).code);ASSERT_TRUE(hit);claude_record_destroy(&out);
    key.size++;ASSERT_EQ(ERR_OK,claude_store_get(&store,&key,&out,&hit).code);ASSERT_FALSE(hit);
    key=s.records[i].key;key.mtime_ns++;ASSERT_EQ(ERR_OK,claude_store_get(&store,&key,&out,&hit).code);ASSERT_FALSE(hit);
  }
  DiscoveredLog original=s.records[0].key;size_t n;char *bytes=read_bytes(original.path.p,&n);
  ASSERT_TRUE(n>0);bytes[n-1]^=1;FILE *changed=fopen(original.path.p,"wb");ASSERT_TRUE(changed);
  ASSERT_EQ(n,fwrite(bytes,1,n,changed));ASSERT_EQ(0,fclose(changed));
  ClaudeRecord out={0};bool hit=true;ASSERT_EQ(ERR_OK,claude_store_get(&store,&original,&out,&hit).code);ASSERT_FALSE(hit);
  free(bytes);
  close_snapshot(&s,&store);
}

typedef struct { ClaudeRecord record; bool retained, candidate; char location[1800]; } RefEntry;
static void ref_inventory(const char *dir,bool retained,RefEntry *entries,size_t *count){
  struct dirent **names=NULL;int n=scandir(dir,&names,NULL,alphasort);ASSERT_TRUE(n>=0);
  for(int i=0;i<n;i++){
    const char *name=names[i]->d_name;size_t len=strlen(name);
    if(len>=4&&!strcmp(name+len-4,".rec")){
      RefEntry *e=&entries[(*count)++];snprintf(e->location,sizeof e->location,"%s/%s",dir,name);
      size_t size;char *bytes=read_bytes(e->location,&size);e->retained=retained;e->candidate=false;
      ASSERT_EQ(ERR_OK,claude_codec_decode(bytes,size,&e->record).code);free(bytes);
    }
    free(names[i]);
  }
  free(names);
}
static bool ref_live(const ClaudeScan *s,Str path){
  for(size_t i=0;i<s->count;i++)if(!s->records[i].retained&&str_equal(s->records[i].key.path,path))return true;
  return false;
}
static void ref_write(const char *path,ClaudeRecord *record){
  unsigned char *bytes=NULL;size_t n=0;ASSERT_EQ(ERR_OK,claude_codec_encode(record,&bytes,&n).code);
  FILE *f=fopen(path,"wb");ASSERT_TRUE(f);ASSERT_EQ(n,fwrite(bytes,1,n,f));ASSERT_EQ(0,fclose(f));free(bytes);
}
TEST(claude_store_index_matches_linear_reconciliation){
  Fixture f;fixture(&f);char path[1800],missing[1400];
  for(int i=0;i<240;i++){snprintf(path,sizeof path,"%s/synthetic-%03d.jsonl",f.root,i);source(path);}
  seed(&f);
  char live_file[1600],root_hash[69],live_dir[1600],retained_base[1600],retained_dir[1600];
  installed(&f,f.one,live_file);cache_entry_name(str(f.root),root_hash);root_hash[64]=0;
  snprintf(live_dir,sizeof live_dir,"%s/cache-claude/%s",f.runtime,root_hash);
  snprintf(retained_base,sizeof retained_base,"%s/claude-retained",f.runtime);ASSERT_EQ(0,mkdir(retained_base,0700));
  snprintf(retained_dir,sizeof retained_dir,"%s/claude-retained/%s",f.runtime,root_hash);ASSERT_EQ(0,mkdir(retained_dir,0700));
  size_t size;char *bytes=read_bytes(live_file,&size);ClaudeRecord duplicate={0};
  ASSERT_EQ(ERR_OK,claude_codec_decode(bytes,size,&duplicate).code);free(bytes);
  duplicate.key.mtime_ns-=2;snprintf(path,sizeof path,"%s/first.rec",retained_dir);ref_write(path,&duplicate);
  duplicate.key.mtime_ns++;snprintf(path,sizeof path,"%s/second.rec",retained_dir);ref_write(path,&duplicate);
  snprintf(missing,sizeof missing,"%s/synthetic-retained-only.jsonl",f.root);duplicate.key.path=str(missing);
  duplicate.key.mtime_ns-=2;snprintf(path,sizeof path,"%s/third.rec",retained_dir);ref_write(path,&duplicate);
  duplicate.key.mtime_ns++;snprintf(path,sizeof path,"%s/fourth.rec",retained_dir);ref_write(path,&duplicate);claude_record_destroy(&duplicate);
  RefEntry *entries=calloc(300,sizeof *entries);ASSERT_TRUE(entries);size_t count=0;
  ref_inventory(live_dir,false,entries,&count);ref_inventory(retained_dir,true,entries,&count);ASSERT_EQ(246,count);
  ASSERT_EQ(0,unlink(f.one));
  for(int i=0;i<12;i++){snprintf(path,sizeof path,"%s/synthetic-%03d.jsonl",f.root,i);ASSERT_EQ(0,unlink(path));}
  ClaudeScan s={0};ClaudeStore store={0};ClaudeRoot root={.path=str(f.root),.present=true,.complete=true};s.roots=&root;s.root_count=1;
  ASSERT_EQ(ERR_OK,claude_store_inspect(f.runtime,&s,false,&store).code);s.store=&store;ASSERT_EQ(ERR_OK,claude_scan(&s,NULL).code);
  for(size_t i=0;i<s.count;i++){
    DiscoveredLog key=s.records[i].key;bool reference=false;
    for(size_t j=0;j<count;j++){ClaudeRecord *r=&entries[j].record;
      if(!entries[j].retained&&r->reader_facts&&str_equal(r->key.path,key.path)&&r->key.size==key.size&&r->key.mtime_ns==key.mtime_ns){reference=true;break;}
    }
    ClaudeRecord output={0};bool hit=false;ASSERT_EQ(ERR_OK,claude_store_get(&store,&key,&output,&hit).code);
    ASSERT_EQ(reference,hit);if(hit)ASSERT_TRUE(str_equal(key.path,output.key.path));claude_record_destroy(&output);
  }
  ClaudeRecord *expected[300];size_t expected_count=0;
  for(unsigned pass=0;pass<2;pass++)for(size_t i=0;i<count;i++){
    RefEntry *e=&entries[i];ClaudeRecord *r=&e->record;
    if(e->retained!=(pass==1)||ref_live(&s,r->key.path))continue;
    if(e->retained){
      bool seen=false;for(size_t j=0;j<s.count;j++)seen|=str_equal(s.records[j].key.path,r->key.path);
      for(size_t j=0;j<expected_count;j++)seen|=str_equal(expected[j]->key.path,r->key.path);
      for(size_t j=0;j<count;j++)if(entries[j].retained&&str_equal(entries[j].record.key.path,r->key.path)&&entries[j].record.key.mtime_ns>r->key.mtime_ns)seen=true;
      if(!seen)expected[expected_count++]=r;
    }else if(claude_path_deleted(r->key.path.p)){e->candidate=true;expected[expected_count++]=r;}
  }
  size_t initial=s.count;ASSERT_EQ(ERR_OK,claude_store_reconcile(&store,&s,NULL).code);ASSERT_EQ(14,expected_count);ASSERT_EQ(initial+expected_count,s.count);
  for(size_t i=0;i<expected_count;i++){ASSERT_TRUE(s.records[initial+i].retained);ASSERT_TRUE(str_equal(expected[i]->key.path,s.records[initial+i].key.path));ASSERT_EQ(expected[i]->key.mtime_ns,s.records[initial+i].key.mtime_ns);}
  ASSERT_EQ(ERR_OK,claude_store_commit(&store,&s,NULL).code);
  for(size_t i=0;i<count;i++)if(!entries[i].retained)ASSERT_EQ(entries[i].candidate,access(entries[i].location,F_OK)!=0);
  close_snapshot(&s,&store);for(size_t i=0;i<count;i++)claude_record_destroy(&entries[i].record);free(entries);
}
