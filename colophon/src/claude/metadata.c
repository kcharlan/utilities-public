#define _DARWIN_C_SOURCE
#include "metadata.h"
#include "corpus/subagents.h"
#include "corpus/titles.h"
#include "parse/record.h"
#include "util/fileio.h"
#include "util/json_number.h"
#include "util/sort.h"
#include "util/time.h"
#include <dirent.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#define TRY(x) do { Err e_ = (x); if (e_.code) return e_; } while (0)
struct ClaudeDesktopEntry { ClaudeDesktop value; };
static Str str(const char *s) { return (Str){s, (uint32_t)strlen(s)}; }
static yyjson_val *get(yyjson_val *v, const char *key) {
  return obj_get_last(v, str(key));
}
static Err text(Arena *a, yyjson_val *v, Str *out) {
  if (!yyjson_is_str(v)) return ERR_SUCCESS;
  Str s = {yyjson_get_str(v), (uint32_t)yyjson_get_len(v)};
  if (!metadata_text(s)) return ERR_SUCCESS;
  return str_copy(a, s, out);
}
static bool identifier(Str s) {
  if (!metadata_text(s)) return false;
  for (size_t i=0; i<s.n; i++)
    if (s.p[i]=='/' || !s.p[i]) return false;
  return true;
}
static Err read_json(Str path, JsonRead *out) {
  char *bytes=NULL; size_t n=0;
  Err e=file_read_all(path.p,&bytes,&n);
  if (!e.code) {
    if (n>UINT32_MAX) e=err_make(ERR_INVALID,"Claude metadata too large");
    else {
      *out=json_read((Str){bytes,(uint32_t)n},BYTES,JSON_CONSTANTS_REJECT,"claude.metadata");
      if(out->status!=JSON_OK) e=err_make(out->status==JSON_NOMEM?ERR_NOMEM:ERR_INVALID,"Invalid Claude metadata");
      else if(!yyjson_is_obj(yyjson_doc_get_root(out->doc))) e=err_make(ERR_INVALID,"Claude metadata is not an object");
    }
  }
  free(bytes); return e;
}
Err claude_sidecar_load(ClaudeRecord *r) {
  if(!r->parent_session.p) return ERR_SUCCESS;
  size_t n=r->key.path.n;
  if(n<6) return ERR_SUCCESS;
  char *path; TRY(arena_alloc(&r->arena,n+5,1,(void **)&path));
  memcpy(path,r->key.path.p,n-6); memcpy(path+n-6,".meta.json",11);
  struct stat st;
  if(lstat(path,&st) || !S_ISREG(st.st_mode)) return ERR_SUCCESS;
  JsonRead json={0}; Err e=read_json(str(path),&json);
  if(!e.code) {
    yyjson_val *v=yyjson_doc_get_root(json.doc);
    e=text(&r->arena,get(v,"parentAgentId"),&r->parent_agent);
    if(!identifier(r->parent_agent)) r->parent_agent=(Str){0};
    if(!e.code)e=text(&r->arena,get(v,"toolUseId"),&r->tool_use_id);
    if(!e.code)e=text(&r->arena,get(v,"description"),&r->description);
    if(!e.code)e=text(&r->arena,get(v,"agentType"),&r->agent_type);
    PyNum depth;
    if(json_number(get(v,"spawnDepth"),"claude.spawnDepth",&depth) && !depth.is_float && depth.i>=0) {
      r->has_spawn_depth=true; r->spawn_depth=depth.i;
    }
  }
  json_read_free(&json);
  return e.code==ERR_NOMEM?e:ERR_SUCCESS;
}
static MaybeMs clock_value(yyjson_val *v) {
  MaybeMs m={0};
  if(yyjson_is_str(v))
    m.present=time_parse_rfc3339((Str){yyjson_get_str(v),(uint32_t)yyjson_get_len(v)},"claude.desktop",&m.value);
  else {
    PyNum n;
    if(json_number(v,"claude.desktop",&n) && !n.is_float)
      m.present=time_ms_from_i64(n.i,true,"claude.desktop",&m.value);
  }
  return m;
}
static Err diagnostic(ClaudeScan *s, Str path) {
  char *p; TRY(arena_alloc(&s->arena,path.n+9,1,(void **)&p));
  snprintf(p,path.n+9,"claude: %.*s",(int)path.n,path.p);
  return corpus_strings_add(&s->arena,&s->metadata_errors,str(p));
}
static Err entry(ClaudeScan *s, Str path) {
  JsonRead json={0}; Err e=read_json(path,&json);
  ClaudeDesktop d={0}; bool malformed=false;
  if(!e.code) {
    yyjson_val *v=yyjson_doc_get_root(json.doc);
    e=text(&s->arena,get(v,"cliSessionId"),&d.id);
    if(!d.id.p && !e.code)e=err_make(ERR_INVALID,"Missing Claude desktop session id");
    if(!e.code)e=text(&s->arena,get(v,"title"),&d.title);
    if(!e.code)e=text(&s->arena,get(v,"cwd"),&d.cwd);
    d.has_archived=yyjson_is_bool(get(v,"isArchived"));
    d.archived=yyjson_is_true(get(v,"isArchived"));
    d.created=clock_value(get(v,"createdAt"));
    d.activity=clock_value(get(v,"lastActivityAt"));
    const char *strings[]={"title","cwd"};
    for(size_t i=0;i<2;i++) {
      yyjson_val *field=get(v,strings[i]);
      malformed|=field && !yyjson_is_str(field);
    }
    malformed|=get(v,"isArchived") && !d.has_archived;
    malformed|=get(v,"createdAt") && !d.created.present;
    malformed|=get(v,"lastActivityAt") && !d.activity.present;
  }
  json_read_free(&json);
  if(e.code==ERR_NOMEM)return e;
  if(e.code)return diagnostic(s,path);
  if(malformed)TRY(diagnostic(s,path));
  struct ClaudeDesktopEntry value={d};
  return record_append(&s->arena,(void **)&s->desktop_entries,&s->desktop_count,
                       &s->desktop_capacity,sizeof value,&value);
}
static int order(const void *a,const void *b,void *ctx) {
  (void)ctx; return str_compare(*(const Str *)a,*(const Str *)b);
}
/* Exact account/org hierarchy, regular files only; never traverse links. */
static Err walk(ClaudeScan *s, Str path, unsigned depth) {
  DIR *dir=opendir(path.p);
  if(!dir) return errno==ENOENT||errno==ENOTDIR?ERR_SUCCESS:diagnostic(s,path);
  CorpusStrings paths={0}; Err e=ERR_SUCCESS; struct dirent *d;
  errno=0;
  while((d=readdir(dir))) {
    if(d->d_name[0]=='.')continue;
    size_t n=path.n+strlen(d->d_name)+2; char *p;
    e=arena_alloc(&s->arena,n,1,(void **)&p);if(e.code)break;
    snprintf(p,n,"%s/%s",path.p,d->d_name);
    e=corpus_strings_add(&s->arena,&paths,str(p));if(e.code)break;
    errno=0;
  }
  if(!e.code && errno)e=diagnostic(s,path);
  if(closedir(dir) && !e.code)e=diagnostic(s,path);
  if(e.code)return e;
  TRY(stable_sort(paths.items,paths.count,sizeof(Str),order,NULL));
  for(size_t i=0;i<paths.count;i++) {
    Str p=paths.items[i]; struct stat st;
    if(lstat(p.p,&st)){TRY(diagnostic(s,p));continue;}
    if(depth<2 && S_ISDIR(st.st_mode))TRY(walk(s,p,depth+1));
    if(depth==2 && S_ISREG(st.st_mode)) {
      const char *name=strrchr(p.p,'/')+1; size_t n=strlen(name);
      if(n>=11 && !strncmp(name,"local_",6) && !strcmp(name+n-5,".json"))TRY(entry(s,p));
    }
  }
  return ERR_SUCCESS;
}
Err claude_metadata_load(ClaudeScan *s) {
  if(s->disabled)return ERR_SUCCESS;
  size_t n=s->desktop_dir.n+23; char *p;
  TRY(arena_alloc(&s->arena,n,1,(void **)&p));
  snprintf(p,n,"%s/claude-code-sessions",s->desktop_dir.p);
  return walk(s,str(p),0);
}
Err claude_metadata_apply(ClaudeScan *s, Corpus *c) {
  s->desktop_without_transcripts=0;
  for(size_t i=0;i<s->desktop_count;i++) {
    ClaudeDesktop *d=&s->desktop_entries[i].value;
    SessionModel *model=omap_get(&c->sessions,d->id);
    if(!model || model->provider!=PROVIDER_CLAUDE){
      bool transcript=false;
      for(size_t j=0;j<s->count;j++)transcript|=str_equal(s->records[j].id,d->id);
      if(!transcript)s->desktop_without_transcripts++;
      continue;
    }
    if(d->title.p) {
      model->title_full=d->title; model->title_source=STR_LIT("desktop");
      TRY(title_display(&c->arena,model->title_full,&model->title));
    }
    if(d->has_archived)model->archived=d->archived;
    if(d->cwd.p && (model->meta.cwd.kind!=JS_STRING || !metadata_text(model->meta.cwd.value.s)))
      model->meta.cwd=(JScalar){.kind=JS_STRING,.value.s=d->cwd};
    if(!model->start_ms.present)model->start_ms=d->created;
    if(!model->end_ms.present)model->end_ms=d->activity;
  }
  return ERR_SUCCESS;
}
