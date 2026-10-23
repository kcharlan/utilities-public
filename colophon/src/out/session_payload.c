#include "session_payload.h"
#include "corpus/provider.h"
#include "price/compose.h"
#include "corpus/titles.h"
#include "corpus/turnstatus.h"
#include "corpus/workspaces.h"
#include "parse/record.h"
#include "util/sort.h"
#include <stdlib.h>
#include <string.h>
static void string(JsonWriter *w, Str s) {
  if (s.p)
    jsonw_string(w, s);
  else
    jsonw_raw(w, "null");
}
static void number(JsonWriter *w, MaybeNum n) {
  if (!n.present)
    jsonw_raw(w, "null");
  else if (n.value.is_float)
    jsonw_double(w, n.value.f);
  else
    jsonw_i64(w, n.value.i);
}
void payload_corpus_strings(JsonWriter *w, const CorpusStrings *strings) {
  jsonw_raw(w, "[");
  for (size_t i = 0; i < strings->count; i++) {
    if (i)
      jsonw_raw(w, ",");
    string(w, strings->items[i]);
  }
  jsonw_raw(w, "]");
}
void payload_workspaces(JsonWriter *w, const Corpus *c) {
  jsonw_raw(w, "{");
  if (c)
    for (OmapEntry *q = c->workspaces.first; q; q = q->next) {
      Workspace *v = q->value;
      if (q != c->workspaces.first)
        jsonw_raw(w, ",");
      string(w, q->key);
      jsonw_raw(w, ":{\"name\":");
      string(w, v->name);
      jsonw_raw(w, ",\"kind\":");
      string(w, v->kind);
      jsonw_raw(w, ",\"keys\":");
      payload_corpus_strings(w, &v->keys);
      jsonw_raw(w, ",\"alias\":");
      string(w, v->alias);
      jsonw_raw(w, "}");
    }
  jsonw_raw(w, "}");
}
static void ms(JsonWriter *w, MaybeMs n) {
  number(w, (MaybeNum){n.present, {.i = n.value}});
}
void payload_corpus_flags(JsonWriter *w, unsigned f, bool turn) {
  const struct {
    unsigned bit;
    const char *text;
  } names[] = {{F_ABANDONED, "abandoned"},
               {F_ABORTED, "aborted"},
               {F_COLLAPSED, turn ? "collapsed" : "collapsed_timestamps"},
               {F_FORK_BASELINE, "fork_baseline_unavailable"},
               {F_RETAINED, "transcript_deleted"},
               {F_FORKED, "forked"},
               {F_HISTORY, "history_unresolved"},
               {F_INTERRUPTED, "interrupted"},
               {F_LIVE, "live"},
               {F_NO_META, "no_session_meta"},
               {F_ORPHAN, "orphaned"},
               {F_REPORTED, "reported_duration"},
               {F_START_COMPLETION, "start_from_completion"},
               {F_UNCERTAIN, "uncertain_timing"},
               {F_UNKNOWN, "unknown_duration"}};
  jsonw_raw(w, "[");
  bool first = true;
  for (size_t i = 0; i < sizeof names / sizeof *names; i++)
    if (f & names[i].bit) {
      if (!first)
        jsonw_raw(w, ",");
      first = false;
      jsonw_string(w, (Str){names[i].text, (uint32_t)strlen(names[i].text)});
    }
  jsonw_raw(w, "]");
}
static void counts(JsonWriter *w, const Omap *map) {
  jsonw_raw(w, "{");
  for (OmapEntry *p = map->first; p; p = p->next) {
    if (p != map->first)
      jsonw_raw(w, ",");
    string(w, p->key);
    jsonw_raw(w, ":");
    jsonw_i128(w, *(__int128 *)p->value);
  }
  jsonw_raw(w, "}");
}
void payload_corpus_tools(JsonWriter *w, const CorpusTools *t) {
  jsonw_raw(w, "{\"shell\":");
  jsonw_i128(w, t->shell);
  jsonw_raw(w, ",\"shell_failed\":");
  jsonw_i128(w, t->shell_failed);
  jsonw_raw(w, ",\"file_edits\":");
  jsonw_i128(w, t->file_edits);
  jsonw_raw(w, ",\"mcp\":");
  counts(w, &t->mcp);
  jsonw_raw(w, ",\"web\":");
  jsonw_i128(w, t->web);
  jsonw_raw(w, ",\"image\":");
  jsonw_i128(w, t->image);
  jsonw_raw(w, ",\"other\":");
  counts(w, &t->other);
  jsonw_raw(w, "}");
}
static void requests(JsonWriter *w, Request *const *v, size_t n) {
  jsonw_raw(w, "[");
  for (size_t i = 0; i < n; i++) {
    Request *q = v[i];
    if (i)
      jsonw_raw(w, ",");
    jsonw_raw(w, "{\"at_ms\":");
    ms(w, q->at_ms);
    jsonw_raw(w, ",\"text\":");
    string(w, q->text);
    jsonw_raw(w, ",\"kind\":");
    string(w, q->kind);
    jsonw_raw(w, q->before_turn ? ",\"before_turn\":true"
                                : ",\"before_turn\":false");
    jsonw_raw(w, ",\"images\":");
    jsonw_i64(w, (int64_t)q->images);
    jsonw_raw(w, q->time_unreliable ? ",\"time_unreliable\":true"
                                    : ",\"time_unreliable\":false");
    jsonw_raw(w, ",\"voice_reply\":");
    string(w, q->voice ? q->voice->reply : (Str){0});
    jsonw_raw(w, "}");
  }
  jsonw_raw(w, "]");
}
static void reply(JsonWriter *w, VoiceReply r) {
  jsonw_raw(w, "{\"at_ms\":");
  ms(w, r.at_ms);
  jsonw_raw(w, ",\"text\":");
  string(w, r.text);
  jsonw_raw(w, "}");
}
static void scalar(JsonWriter *w, JScalar s) {
  switch (s.kind) {
  case JS_STRING:
    string(w, s.value.s);
    break;
  case JS_BOOL:
    jsonw_raw(w, s.value.b ? "true" : "false");
    break;
  case JS_INT:
    jsonw_i64(w, s.value.i);
    break;
  case JS_FLOAT:
    jsonw_double(w, s.value.f);
    break;
  case JS_ARRAY:
    jsonw_raw(w, s.empty ? "[]" : "[null]");
    break;
  case JS_OBJECT:
    jsonw_raw(w, s.empty ? "{}" : "{\"\":null}");
    break;
  default:
    jsonw_raw(w, "null");
  }
}
static void fallback(JsonWriter *w, JScalar raw, const MetadataThread *row,
                     MetadataColumn column) {
  bool truthy = record_scalar_truthy(raw);
  if (truthy) {
    scalar(w, raw);
    return;
  }
  MetadataValue v = row ? row->values[column] : (MetadataValue){0};
  if (v.kind == META_TEXT)
    string(w, v.value.bytes);
  else if (v.kind == META_INTEGER)
    jsonw_i64(w, v.value.integer);
  else if (v.kind == META_REAL)
    jsonw_double(w, v.value.real);
  else
    jsonw_raw(w, "null");
}
static int session_order(const void *a, const void *b, void *ctx) {
  const PayloadIds *ids=ctx;
  const SessionModel *x = *(SessionModel *const *)a,
                     *y = *(SessionModel *const *)b;
  if (x->start_ms.present != y->start_ms.present)
    return x->start_ms.present ? -1 : 1;
  if (x->start_ms.present && x->start_ms.value != y->start_ms.value)
    return x->start_ms.value > y->start_ms.value ? -1 : 1;
  return str_compare(*(Str *)omap_get(&ids->ids,x->id),*(Str *)omap_get(&ids->ids,y->id));
}
Err payload_ids_init(const Corpus *corpus,const char *home,PayloadIds *out) {
  if(!corpus)return ERR_SUCCESS;
  for(OmapEntry *q=corpus->sessions.first;q;q=q->next){
    const SessionModel *s=q->value;Str *mapped;
    Err error=arena_alloc(&out->arena,sizeof *mapped,_Alignof(Str),(void **)&mapped);
    if(error.code)return error;*mapped=s->id;
    if((s->flags&F_NO_META)&&s->id.n>=5&&!memcmp(s->id.p,"file:",5)&&home){
      Str path=s->record->key.path;size_t hn=strlen(home);
      bool anchor=!strcmp(home,"/")||!strcmp(home,"//");
      bool matching_anchor=(path.n>=2&&path.p[0]=='/'&&path.p[1]=='/')==(hn>=2&&home[0]=='/'&&home[1]=='/');
      if(path.n>=hn&&matching_anchor&&!memcmp(path.p,home,hn)&&(path.n==hn||anchor||path.p[hn]=='/')){
        size_t offset=anchor?hn:hn+1;JsonWriter bytes={0};
        jsonw_bytes(&bytes,"file:",5);
        if(path.n==hn)jsonw_bytes(&bytes,".",1);
        else jsonw_bytes(&bytes,path.p+offset,path.n-offset);
        error=bytes.error;
        if(!error.code)error=str_copy(&out->arena,(Str){bytes.data,(uint32_t)bytes.length},mapped);
        jsonw_free(&bytes);if(error.code)return error;
      }
    }
    error=omap_put(&out->ids,s->id,mapped);if(error.code)return error;
  }
  return ERR_SUCCESS;
}
void payload_ids_destroy(PayloadIds *ids){omap_destroy(&ids->ids);arena_destroy(&ids->arena);*ids=(PayloadIds){0};}
void payload_reference(JsonWriter *w,const PayloadIds *ids,Str id){
  Str *mapped=id.p&&ids?omap_get(&ids->ids,id):NULL;string(w,mapped?*mapped:id);
}
void payload_references(JsonWriter *w,const PayloadIds *ids,const CorpusStrings *strings){
  jsonw_raw(w,"[");for(size_t i=0;i<strings->count;i++){if(i)jsonw_raw(w,",");payload_reference(w,ids,strings->items[i]);}jsonw_raw(w,"]");
}
size_t payload_unresolved_history(JsonWriter *w,const Corpus *c,const PayloadIds *ids) {
  size_t count=0;if(w)jsonw_raw(w,"[");
  if(c)for(OmapEntry *q=c->sessions.first;q;q=q->next){const SessionModel *s=q->value;
    if(!(s->flags&F_HISTORY))continue;
    if(w){if(count)jsonw_raw(w,",");payload_reference(w,ids,s->id);}count++;
  }
  if(w)jsonw_raw(w,"]");return count;
}
static void payload_rows(JsonWriter *w, const Corpus *c, const PayloadIds *ids,
                         bool agents) {
  jsonw_raw(w, agents ? "{" : "[");
  if (!c) {
    jsonw_raw(w, agents ? "}" : "]");
    return;
  }
  SessionModel **ordered =
      malloc((c->sessions.size ? c->sessions.size : 1) * sizeof *ordered);
  if (!ordered) {
    w->error = err_make(ERR_NOMEM, "payload sessions allocation failed");
    return;
  }
  size_t n = 0;
  for (OmapEntry *p = c->sessions.first; p; p = p->next)
    ordered[n++] = p->value;
  Err e = agents
              ? ERR_SUCCESS
              : stable_sort(ordered, n, sizeof *ordered, session_order, (void *)ids);
  if (e.code) {
    w->error = e;
    free(ordered);
    return;
  }
  size_t emitted = 0;
  for (size_t i = 0; i < n; i++) {
    SessionModel *s = ordered[i];
    bool linked = str_equal(s->kind, STR_LIT("subagent"));
    if (linked != agents)
      continue;
    if (emitted++)
      jsonw_raw(w, ",");
    if (agents) {
      payload_reference(w, ids, s->id);
      jsonw_raw(w, ":");
    }
    jsonw_raw(w, "{\"id\":");
    payload_reference(w, ids, s->id);
    jsonw_raw(w,",\"provider\":");string(w,provider_id(s->provider));
    if(s->provider==PROVIDER_ANTIGRAVITY){
      jsonw_raw(w,",\"antigravity_surface\":");string(w,s->antigravity_surface);
      jsonw_raw(w,",\"git_root\":");string(w,s->antigravity_git_root);
    }
    if(s->provider==PROVIDER_OPENCODE){
      jsonw_raw(w,",\"opencode_database\":");string(w,s->opencode_database);
    }
    if(s->provider==PROVIDER_OPENCODE||s->provider==PROVIDER_ANTIGRAVITY){
      jsonw_raw(w,",\"capabilities\":{\"copy_session_id\":true,\"copy_log_path\":false,\"open_in_codex\":false,\"continue_in_cli\":false}");
    }
    jsonw_raw(w,s->history_only?",\"history_only\":true":",\"history_only\":false");jsonw_raw(w,",\"resume_config_dir\":");string(w,s->resume_config_dir);
    if (!agents) {
      jsonw_raw(w, ",\"kind\":");
      string(w, s->kind.p ? s->kind : STR_LIT("session"));
    }
    jsonw_raw(w, ",\"title\":");
    string(w, s->title);
    jsonw_raw(w, ",\"title_full\":");
    string(w, s->title_full);
    jsonw_raw(w, ",\"title_source\":");
    string(w, s->title_source);
    jsonw_raw(w,
              s->archived ? ",\"archived\":true" : ",\"archived\":false");
    jsonw_raw(w, ",\"archive_reason\":");
    string(w, s->archive_reason);
    jsonw_raw(w, ",\"log_path\":");
    string(w, s->log_path);
    jsonw_raw(w, ",\"workspace\":");
    string(w, s->workspace);
    jsonw_raw(w, ",\"subfolder\":");
    string(w, s->subfolder);
    jsonw_raw(w, ",\"cwd\":");
    fallback(w, s->meta.cwd, s->db_info, META_CWD);
    jsonw_raw(w, ",\"branch\":");
    fallback(w, s->meta.branch, s->db_info, META_GIT_BRANCH);
    jsonw_raw(w, ",\"originator\":");
    fallback(w, s->meta.originator, s->db_info, META_ORIGINATOR);
    jsonw_raw(w, ",\"forked_from\":");
    payload_reference(w, ids, s->forked_from);
    jsonw_raw(w, ",\"start_ms\":");
    ms(w, s->start_ms);
    jsonw_raw(w, ",\"end_ms\":");
    ms(w, s->end_ms);
    jsonw_raw(w, ",\"idle_ms\":");
    number(w, s->idle_ms);
    jsonw_raw(w, ",\"user_span_ms\":");
    ms(w, s->user_span_ms);
    jsonw_raw(w, ",\"flags\":");
    payload_corpus_flags(w, s->flags, false);
    jsonw_raw(w, ",\"turns\":[");
    for (size_t j = 0; j < s->turn_count; j++) {
      TurnModel *t = &s->turns[j];
      if (j)
        jsonw_raw(w, ",");
      jsonw_raw(w, "{\"id\":");
      string(w, t->id);
      jsonw_raw(w, ",\"n\":");
      jsonw_i64(w, (int64_t)t->n);
      jsonw_raw(w, ",\"status\":");
      string(w, t->status);
      jsonw_raw(w, ",\"start_ms\":");
      number(w, t->start_ms);
      jsonw_raw(w, ",\"end_ms\":");
      number(w, t->end_ms);
      jsonw_raw(w, ",\"duration_ms\":");
      number(w, t->duration_ms);
      jsonw_raw(w, ",\"ttft_ms\":");
      number(w, t->ttft_ms);
      jsonw_raw(w, ",\"flags\":");
      payload_corpus_flags(w, t->flags, true);
      jsonw_raw(w, ",\"requests\":");
      requests(w, t->requests, t->request_count);
      jsonw_raw(w, ",\"final_answer\":");
      if (t->final_answer.p) {
        jsonw_raw(w, "{\"text\":");
        string(w, t->final_answer);
        jsonw_raw(w, t->final_voice ? ",\"voice\":true}" : ",\"voice\":false}");
      } else
        jsonw_raw(w, "null");
      jsonw_raw(w, ",\"voice_replies\":[");
      bool first = true;
      for (size_t k = 0; k < t->voice_reply_count; k++) {
        if (!first)
          jsonw_raw(w, ",");
        first = false;
        reply(w, t->voice_replies[k]);
      }
      jsonw_raw(w, "],\"tools\":");
      payload_corpus_tools(w, &t->tools);
      jsonw_raw(w, ",\"usage\":");
      compose_summary_json(w,t->usage);
      jsonw_raw(w, ",\"spawned\":");
      payload_references(w, ids, &t->spawned);
      jsonw_raw(w, ",\"used\":");
      payload_references(w, ids, &t->used);
      jsonw_raw(w, "}");
    }
    jsonw_raw(w, "],\"session_voice\":{\"requests\":");
    requests(w, s->voice_requests, s->voice_request_count);
    jsonw_raw(w, ",\"replies\":[");
    if (!s->turn_count)
      for (size_t j = 0; j < s->voice_reply_count; j++) {
        if (j)
          jsonw_raw(w, ",");
        reply(w, s->voice_replies[j]);
      }
    jsonw_raw(w, "]},\"own_usage\":");
    compose_summary_json(w,s->own_usage);
    jsonw_raw(w, ",\"outside_usage\":");
    compose_summary_json(w,s->outside_usage);
    jsonw_raw(w, ",\"buckets\":");compose_buckets_json(w,s);
    jsonw_raw(w, ",\"tools\":");
    payload_corpus_tools(w, &s->tools);
    jsonw_raw(w, ",\"children\":");
    payload_references(w, ids, &s->children);
    if (agents || (s->provider != PROVIDER_CODEX && s->is_subagent)) {
      jsonw_raw(w, ",\"parent_id\":");
      payload_reference(w, ids, s->parent_id);
      jsonw_raw(w, ",\"depth\":");
      if (s->has_depth)
        jsonw_i128(w, s->depth);
      else
        jsonw_raw(w, "null");
      jsonw_raw(w, ",\"agent_path\":");
      string(w, s->agent_path);
      Arena label_arena = {0};
      Str label = {0};
      e = title_humanize(&label_arena, s->agent_path, &label);
      if (s->provider != PROVIDER_CODEX)
        label = s->agent_label;
      if (e.code)
        w->error = e;
      jsonw_raw(w, ",\"label\":");
      string(w, label);
      arena_destroy(&label_arena);
      jsonw_raw(w, ",\"nickname\":");
      fallback(w, s->meta.agent_nickname, s->db_info, META_AGENT_NICKNAME);
      jsonw_raw(w, (s->flags & F_FORKED) ? ",\"forked\":true"
                                         : ",\"forked\":false");
      jsonw_raw(w, ",\"spawn_turn\":");
      string(w, s->spawn_turn);
      jsonw_raw(w, ",\"interaction_turns\":");
      payload_corpus_strings(w, &s->interaction_turns);
      jsonw_raw(w, ",\"link_method\":");
      string(w, s->link_method);
    }
    jsonw_raw(w, "}");
  }
  free(ordered);
  jsonw_raw(w, agents ? "}" : "]");
}
void payload_sessions(JsonWriter *w, const Corpus *c, const PayloadIds *ids) {
  payload_rows(w, c, ids, false);
}
void payload_subagents(JsonWriter *w, const Corpus *c, const PayloadIds *ids) {
  payload_rows(w, c, ids, true);
}
void payload_file_diagnostic(JsonWriter *w, const FileDiagnostic *d) {
  jsonw_raw(w, "{\"total\":");
  jsonw_i128(w, d ? d->total : 0);
  jsonw_raw(w, ",\"files\":[");
  if (d)
    for (size_t i = 0; i < d->count; i++) {
      if (i)
        jsonw_raw(w, ",");
      jsonw_raw(w, "{\"path\":");
      string(w, d->files[i].path);
      jsonw_raw(w, ",\"count\":");
      jsonw_i64(w, (int64_t)d->files[i].count);
      jsonw_raw(w, "}");
    }
  jsonw_raw(w, "]}");
}
void payload_unknown_types(JsonWriter *w, const Corpus *c) {
  if (c)
    counts(w, &c->unknown_types);
  else
    jsonw_raw(w, "{}");
}
