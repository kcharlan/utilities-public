#define _DARWIN_C_SOURCE
#include "store.h"
#include "codec.h"
#include "corpus/subagents.h"
#include "cache/cache.h"
#include "parse/record.h"
#include "testing/hooks.h"
#include "util/atomic.h"
#include "util/fileio.h"
#include "util/sort.h"
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#define TRY(x) do { Err e_=(x);if(e_.code)return e_; } while(0)
struct ClaudeStored {
  Str location;
  ClaudeRecord record;
  bool retained, candidate;
  struct ClaudeStored *next_same_path;
};
static Str str(const char *s){return (Str){s,(uint32_t)strlen(s)};}
static Err join(Arena *a,Str parent,const char *name,Str *out){
  size_t n=parent.n+strlen(name)+2;char *p;TRY(arena_alloc(a,n,1,(void **)&p));
  snprintf(p,n,"%s/%s",parent.p,name);*out=str(p);return ERR_SUCCESS;
}
static Err io(const char *what){char text[256];return err_make(ERR_IO,"Claude store %s: %s",what,err_system(errno,text));}
static bool stopped(volatile sig_atomic_t *p){return p&&*p;}
bool claude_path_deleted(const char *path){
  struct stat st;
  if(!lstat(path,&st)||errno!=ENOENT)return false;
  char *parent=strdup(path);if(!parent)return false;
  bool proved=false;
  for(;;){
    char *slash=strrchr(parent,'/');if(!slash)break;
    if(slash==parent)slash[1]=0;else *slash=0;
    if(!stat(parent,&st)){proved=S_ISDIR(st.st_mode)&&!access(parent,R_OK|X_OK);break;}
    if(errno!=ENOENT||slash==parent)break;
  }
  free(parent);return proved;
}
static ClaudeRoot *selected(ClaudeScan *s,Str path){
  for(size_t i=0;i<s->root_count;i++)if(str_equal(s->roots[i].path,path))return &s->roots[i];
  return NULL;
}
static Err unreadable(ClaudeScan *s,Str path){return corpus_strings_add(&s->arena,&s->retained_unreadable,path);}
static int order(const void *a,const void *b,void *ctx){(void)ctx;return str_compare(*(const Str *)a,*(const Str *)b);}
/* Only physical regular records and directories, in stable order. Store
 * corruption/unreadability remains in place; no recovery sweep deletes data. */
static Err inventory(ClaudeStore *store,ClaudeScan *s,Str dir,bool retained,unsigned depth){
  DIR *d=opendir(dir.p);
  if(!d){if(errno==ENOENT)return ERR_SUCCESS;return retained?unreadable(s,dir):ERR_SUCCESS;}
  CorpusStrings names={0};Err e=ERR_SUCCESS;struct dirent *q;
  for(;;){errno=0;q=readdir(d);if(!q){if(errno&&retained)e=unreadable(s,dir);break;}
    if(q->d_name[0]=='.')continue;Str p;e=join(&store->arena,dir,q->d_name,&p);if(e.code)break;
    e=corpus_strings_add(&store->arena,&names,p);if(e.code)break;
  }
  if(closedir(d)&&!e.code&&retained)e=unreadable(s,dir);
  if(!e.code)e=stable_sort(names.items,names.count,sizeof(Str),order,NULL);
  for(size_t i=0;i<names.count&&!e.code;i++){
    Str path=names.items[i];struct stat st;
    if(lstat(path.p,&st)){if(retained)e=unreadable(s,path);continue;}
    if(S_ISDIR(st.st_mode)&&depth==0){e=inventory(store,s,path,retained,1);continue;}
    if(!S_ISREG(st.st_mode)||path.n<4||strcmp(path.p+path.n-4,".rec"))continue;
    char *bytes=NULL;size_t n=0;ClaudeRecord r={0};
    e=file_read_all(path.p,&bytes,&n);if(!e.code)e=claude_codec_decode(bytes,n,&r);free(bytes);
    if(e.code){claude_record_destroy(&r);if(e.code==ERR_NOMEM)break;e=retained?unreadable(s,path):ERR_SUCCESS;continue;}
    if(!retained&&!selected(s,r.search_root)){claude_record_destroy(&r);continue;}
    ClaudeStored entry={.location=path,.record=r,.retained=retained};
    e=record_append(&store->arena,(void **)&store->entries,&store->count,&store->capacity,sizeof entry,&entry);
    if(e.code)claude_record_destroy(&r);
  }
  return e;
}
Err claude_store_inspect(const char *home,ClaudeScan *s,bool rebuild,ClaudeStore *store){
  *store=(ClaudeStore){.rebuild=rebuild,.inspected=true};
  TRY(str_copy(&store->arena,str(home),&store->home));
  if(s->disabled)return ERR_SUCCESS;
  Str path;TRY(join(&store->arena,store->home,"cache-claude",&path));TRY(inventory(store,s,path,false,0));
  TRY(join(&store->arena,store->home,"claude-retained",&path));TRY(inventory(store,s,path,true,0));
  for(size_t i=store->count;i>0;i--){
    ClaudeStored *entry=&store->entries[i-1];
    ClaudeStored **head=omap_get(&store->path_index,entry->record.key.path);
    if(!head){
      TRY(arena_alloc(&store->arena,sizeof *head,_Alignof(ClaudeStored *),(void **)&head));
      *head=NULL;TRY(omap_put(&store->path_index,entry->record.key.path,head));
    }
    entry->next_same_path=*head;*head=entry;
  }
  return ERR_SUCCESS;
}
Err claude_store_get(ClaudeStore *store,const DiscoveredLog *key,ClaudeRecord *out,bool *hit){
  *out=(ClaudeRecord){0};*hit=false;if(!store||store->rebuild)return ERR_SUCCESS;
  ClaudeStored **head=omap_get(&store->path_index,key->path);
  for(ClaudeStored *entry=head?*head:NULL;entry;entry=entry->next_same_path){
    ClaudeRecord *r=&entry->record;
    if(entry->retained||!r->reader_facts||r->key.size!=key->size||r->key.mtime_ns!=key->mtime_ns)continue;
    int fd=open(key->path.p,O_RDONLY|O_NONBLOCK);if(fd<0)return io("fingerprint open");
    char tail[65];Err e=reader_fingerprint(fd,key->size,tail);close(fd);if(e.code)return e;
    if(memcmp(tail,r->reader.tail_sha256,65))continue;
    unsigned char *bytes=NULL;size_t n=0;e=claude_codec_encode(r,&bytes,&n);if(!e.code)e=claude_codec_decode(bytes,n,out);free(bytes);
    if(e.code)return e;out->key.device=key->device;out->key.inode=key->inode;*hit=true;return ERR_SUCCESS;
  }
  return ERR_SUCCESS;
}
static Err append(ClaudeScan *s,const ClaudeRecord *r){
  if(s->count==s->capacity){size_t n=s->capacity?s->capacity*2:16;void *p=realloc(s->records,n*sizeof *s->records);if(!p)return err_make(ERR_NOMEM,"Claude records allocation failed");s->records=p;s->capacity=n;}
  unsigned char *bytes=NULL;size_t n=0;TRY(claude_codec_encode(r,&bytes,&n));
  Err e=claude_codec_decode(bytes,n,&s->records[s->count]);free(bytes);
  if(!e.code){s->records[s->count++].retained=true;s->retained++;s->present=true;}
  return e;
}
Err claude_store_reconcile(ClaudeStore *store,ClaudeScan *s,volatile sig_atomic_t *flag){
  if(s->disabled)return ERR_SUCCESS;
  Omap live={0},all={0};Err result=ERR_SUCCESS;
  if(stopped(flag)){result=err_make(ERR_IO,"interrupted");goto done;}
  for(size_t i=0;i<s->count;i++){
    ClaudeRecord *r=&s->records[i];
    if(!omap_get(&all,r->key.path)){result=omap_put(&all,r->key.path,s);if(result.code)goto done;}
    if(!r->retained&&!omap_get(&live,r->key.path)){result=omap_put(&live,r->key.path,s);if(result.code)goto done;}
  }
  /* Live paths (including zero-byte snapshots) supersede retained at composition
   * time, but their stored copies are removed only by successful commit. */
  for(unsigned pass=0;pass<2;pass++)for(size_t i=0;i<store->count;i++){
    if(stopped(flag)){result=err_make(ERR_IO,"interrupted");goto done;}
    ClaudeStored *entry=&store->entries[i];ClaudeRecord *r=&entry->record;
    if(entry->retained!=(pass==1)||omap_get(&live,r->key.path))continue;
    if(entry->retained){
      bool seen=omap_get(&all,r->key.path)!=NULL;
      ClaudeStored **head=omap_get(&store->path_index,r->key.path);
      for(ClaudeStored *other=head?*head:NULL;other;other=other->next_same_path)
        if(other->retained&&other->record.key.mtime_ns>r->key.mtime_ns)seen=true;
      if(!seen){
        result=append(s,r);if(result.code)goto done;
        if(!omap_get(&all,r->key.path)){result=omap_put(&all,r->key.path,s);if(result.code)goto done;}
      }
      continue;
    }
    ClaudeRoot *root=selected(s,r->search_root);
    if(root&&root->complete&&claude_path_deleted(r->key.path.p)){
      entry->candidate=true;result=append(s,r);if(result.code)goto done;
      if(!omap_get(&all,r->key.path)){result=omap_put(&all,r->key.path,s);if(result.code)goto done;}
    }
  }
done:
  omap_destroy(&all);omap_destroy(&live);return result;
}
static Err directory(ClaudeStore *store,const char *kind,Str root,Str *out){
  Str base;TRY(join(&store->arena,store->home,kind,&base));TRY(ensure_runtime_home(base.p));
  char name[69];cache_entry_name(root,name);name[64]=0;TRY(join(&store->arena,base,name,out));return ensure_runtime_home(out->p);
}
static Err install(ClaudeStore *store,ClaudeRecord *r){
  Str dir,path;TRY(directory(store,"cache-claude",r->search_root,&dir));char name[69];cache_entry_name(r->key.path,name);TRY(join(&store->arena,dir,name,&path));
  unsigned char *bytes=NULL;size_t n=0;TRY(claude_codec_encode(r,&bytes,&n));
  bool same=false;int fd=open(path.p,O_RDONLY|O_NONBLOCK|O_NOFOLLOW);
  if(fd>=0){
    struct stat st;size_t at=0;unsigned char chunk[8192];
    if(!fstat(fd,&st)&&S_ISREG(st.st_mode)&&st.st_size>=0&&(uint64_t)st.st_size==n){
      same=true;
      while(at<n){size_t want=n-at<sizeof chunk?n-at:sizeof chunk;ssize_t got=read(fd,chunk,want);
        if(got<0&&errno==EINTR)continue;
        if(got<=0||memcmp(chunk,bytes+at,(size_t)got)){same=false;break;}at+=(size_t)got;
      }
      if(same&&read(fd,chunk,1)!=0)same=false;
    }
    close(fd);
  }
  Err e=same?ERR_SUCCESS:atomic_write(path.p,bytes,n);free(bytes);return e;
}
static Err retain(ClaudeStore *store,ClaudeStored *entry){
  Str dir,path;TRY(directory(store,"claude-retained",entry->record.search_root,&dir));char key[69];cache_entry_name(entry->record.key.path,key);
  /* Existing retained records, even corrupt ones, are never overwritten. A
   * unique sibling keeps every recovery copy readable by the next inventory. */
  struct stat st;size_t suffix=0;
  do {char name[112];if(!suffix)snprintf(name,sizeof name,"%s",key);else snprintf(name,sizeof name,"%.64s-%zu.rec",key,suffix);TRY(join(&store->arena,dir,name,&path));suffix++;}while(!lstat(path.p,&st));
  if(errno!=ENOENT)return io("retained stat");
  if(rename(entry->location.p,path.p))return io("retained rename");
  return ERR_SUCCESS;
}
/* An earlier successful decode does not authorize deleting a retained file
 * changed or made unreadable before commit. A fresh successful live install
 * exists before this runs, but corrupt retained bytes must still be kept. */
static Err supersede(ClaudeStored *entry,Str original){
  struct stat st;
  if(lstat(entry->location.p,&st)||!S_ISREG(st.st_mode))return ERR_SUCCESS;
  char *bytes=NULL;size_t n=0;ClaudeRecord current={0};
  Err e=file_read_all(entry->location.p,&bytes,&n);
  if(!e.code)e=claude_codec_decode(bytes,n,&current);
  free(bytes);
  bool matched=!e.code&&str_equal(current.key.path,original);
  claude_record_destroy(&current);
  if(e.code==ERR_NOMEM)return e;
  if(matched&&unlink(entry->location.p)&&errno!=ENOENT)return io("retained supersession");
  return ERR_SUCCESS;
}
Err claude_store_commit(ClaudeStore *store,ClaudeScan *s,volatile sig_atomic_t *flag){
  if(s->disabled)return ERR_SUCCESS;
  if(stopped(flag))return err_make(ERR_IO,"interrupted");
  for(size_t root_index=0;root_index<s->root_count;root_index++){
    ClaudeRoot *root=&s->roots[root_index];bool eligible=true;
    /* Recheck every candidate before the first mutation for this root. Changed
     * evidence aborts the entire root, leaving its earlier page snapshot. */
    for(size_t i=0;i<store->count;i++){
      ClaudeStored *entry=&store->entries[i];
      if(entry->candidate&&str_equal(entry->record.search_root,root->path)&&!claude_path_deleted(entry->record.key.path.p))eligible=false;
    }
    if(!eligible)continue;
    for(size_t i=0;i<store->count;i++){
      ClaudeStored *entry=&store->entries[i];if(!entry->candidate||!str_equal(entry->record.search_root,root->path))continue;
      if(stopped(flag)||cp_fault("claude_commit_before_move"))return err_make(ERR_IO,"interrupted before Claude retention move");
      TRY(retain(store,entry));
      if(cp_fault("claude_commit_after_move"))return err_make(ERR_IO,"interrupted after Claude retention move");
    }
    for(size_t i=0;i<s->count;i++){
      ClaudeRecord *r=&s->records[i];if(r->retained||!str_equal(r->search_root,root->path))continue;
      if(stopped(flag)||cp_fault("claude_commit_before_install"))return err_make(ERR_IO,"interrupted before Claude cache installation");
      TRY(install(store,r));
      if(cp_fault("claude_commit_after_install"))return err_make(ERR_IO,"interrupted after Claude cache installation");
      for(size_t j=0;j<store->count;j++){
        ClaudeStored *entry=&store->entries[j];
        if(!entry->retained||!str_equal(entry->record.key.path,r->key.path))continue;
        if(stopped(flag)||cp_fault("claude_commit_before_retained_remove"))return err_make(ERR_IO,"interrupted before Claude retained supersession");
        TRY(supersede(entry,r->key.path));
      }
    }
  }
  store->committed=true;return ERR_SUCCESS;
}
void claude_store_destroy(ClaudeStore *store){
  for(size_t i=0;i<store->count;i++)claude_record_destroy(&store->entries[i].record);
  omap_destroy(&store->path_index);arena_destroy(&store->arena);*store=(ClaudeStore){0};
}
