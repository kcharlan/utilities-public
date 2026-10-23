#include "payload.h"
#include "session_payload.h"
#include "price/compose.h"
#include "opencode/scan.h"
#include "antigravity/scan.h"
#include "opencode/compose.h"
#include <stdlib.h>
#include <string.h>
static void text(JsonWriter *w,const char *s){jsonw_string(w,(Str){s,(uint32_t)strlen(s)});}
static void antigravity_source(JsonWriter *w,const PayloadInputs *in){
    const AntigravityStore *s=in->antigravity;
    jsonw_raw(w,",\"antigravity\":{\"status\":");text(w,antigravity_status(s));
    jsonw_raw(w,",\"home\":");if(s&&s->home.p)jsonw_string(w,s->home);else jsonw_raw(w,"null");
    jsonw_raw(w,",\"databases\":[");
    if(s)for(size_t i=0;i<s->database_count;i++){
        const AntigravityDatabase *d=&s->databases[i];if(i)jsonw_raw(w,",");
        jsonw_raw(w,"{\"path\":");jsonw_string(w,d->path);jsonw_raw(w,",\"surface\":");jsonw_string(w,d->surface);
        jsonw_raw(w,",\"status\":");text(w,antigravity_database_status(d->status));jsonw_raw(w,",\"reason\":");if(d->reason.n)jsonw_string(w,d->reason);else jsonw_raw(w,"null");
        jsonw_raw(w,",\"accepted_sessions\":");jsonw_i128(w,d->accepted_sessions);jsonw_raw(w,",\"accepted_steps\":");jsonw_i128(w,d->accepted_steps);jsonw_raw(w,"}");
    }
    size_t sessions=0,subagents=0,archived=0;
    if(in->corpus)for(OmapEntry *q=in->corpus->sessions.first;q;q=q->next){const SessionModel *row=q->value;if(row->provider!=PROVIDER_ANTIGRAVITY)continue;if(row->is_subagent)subagents++;else sessions++;archived+=row->archived;}
    jsonw_raw(w,"],\"sessions\":");jsonw_i128(w,sessions);jsonw_raw(w,",\"subagents\":");jsonw_i128(w,subagents);jsonw_raw(w,",\"archived\":");jsonw_i128(w,archived);
    jsonw_raw(w,",\"legacy_encrypted\":");jsonw_i128(w,s?s->legacy_encrypted:0);jsonw_raw(w,",\"ignored_environment\":[");
    if(s)for(size_t i=0;i<s->ignored_environment_count;i++){if(i)jsonw_raw(w,",");jsonw_string(w,s->ignored_environment[i]);}
    jsonw_raw(w,"],\"logs\":0,\"cached\":0,\"costs\":{\"available\":true,\"reason\":null}}");
}
static void antigravity_diagnostics(JsonWriter *w,const AntigravityStore *s){
    const char *keys[]={"antigravity_schema_errors","antigravity_unreadable_databases"};
    for(size_t k=0;k<2;k++){
        jsonw_raw(w,",");text(w,keys[k]);jsonw_raw(w,":[");bool first=true;
        if(s)for(size_t i=0;i<s->database_count;i++){const AntigravityDatabase *d=&s->databases[i];if(d->status!=(k?AG_DB_UNREADABLE:AG_DB_UNSUPPORTED))continue;
            if(!first)jsonw_raw(w,",");first=false;jsonw_raw(w,"{\"path\":");jsonw_string(w,d->path);jsonw_raw(w,",\"surface\":");jsonw_string(w,d->surface);jsonw_raw(w,",\"reason\":");jsonw_string(w,d->reason);jsonw_raw(w,"}");}
        jsonw_raw(w,"]");
    }
    jsonw_raw(w,",\"antigravity_duplicate_sessions\":");jsonw_i128(w,s?s->duplicate_sessions:0);
    jsonw_raw(w,",\"antigravity_archive_disagreements\":");jsonw_i128(w,s?s->archive_disagreements:0);
    jsonw_raw(w,",\"antigravity_malformed_blobs\":");jsonw_i128(w,s?s->malformed_blobs:0);
    jsonw_raw(w,",\"antigravity_malformed_rows\":");jsonw_i128(w,s?s->malformed_rows:0);
    jsonw_raw(w,",\"antigravity_annotation_errors\":");jsonw_i128(w,s?s->annotation_errors:0);
    jsonw_raw(w,",\"antigravity_cross_session_duplicates\":");jsonw_i128(w,s?s->cross_session_duplicates:0);
    jsonw_raw(w,",\"antigravity_requests_without_usage\":");jsonw_i128(w,s?s->requests_without_usage:0);
    jsonw_raw(w,",\"antigravity_invalid_numbers\":");jsonw_i128(w,s?s->invalid_numbers:0);
    jsonw_raw(w,",\"antigravity_unknown_clocks\":");jsonw_i128(w,s?s->unknown_clocks:0);
    jsonw_raw(w,",\"antigravity_orphaned_subagents\":");payload_corpus_strings(w,s?&s->orphaned_subagents:&(CorpusStrings){0});
    jsonw_raw(w,",\"antigravity_session_id_collisions\":");payload_corpus_strings(w,s?&s->corpus_collisions:&(CorpusStrings){0});
    jsonw_raw(w,",\"antigravity_source_diagnostics\":[");
    if(s)for(size_t i=0;i<s->diagnostic_count;i++){const AntigravityDiagnostic *d=&s->diagnostics[i];if(i)jsonw_raw(w,",");
        jsonw_raw(w,"{\"database\":");jsonw_string(w,d->database);jsonw_raw(w,",\"session\":");jsonw_string(w,d->session);jsonw_raw(w,",\"surface\":");jsonw_string(w,d->surface);jsonw_raw(w,",\"context\":");jsonw_string(w,d->context);jsonw_raw(w,",\"idx\":");jsonw_i64(w,d->idx);jsonw_raw(w,",\"reason\":");jsonw_string(w,d->reason);jsonw_raw(w,"}");
    }
    jsonw_raw(w,"]");
}
static void opencode_source(JsonWriter *w,const PayloadInputs *in){
    const OpencodeStore *s=in->opencode;const OpencodeUsageReport *u=s?s->usage:NULL;
    jsonw_raw(w,",\"opencode\":{\"status\":");text(w,opencode_status(s));
    jsonw_raw(w,",\"data_dir\":");if(s&&s->data_dir.p)jsonw_string(w,s->data_dir);else jsonw_raw(w,"null");
    jsonw_raw(w,",\"databases\":[");
    if(s)for(size_t i=0;i<s->database_count;i++){
        const OpencodeDatabase *d=&s->databases[i];if(i)jsonw_raw(w,",");
        jsonw_raw(w,"{\"path\":");jsonw_string(w,d->path);jsonw_raw(w,",\"status\":");text(w,opencode_database_status(d->status));
        jsonw_raw(w,",\"reason\":");if(d->reason.p)jsonw_string(w,d->reason);else jsonw_raw(w,"null");
        jsonw_raw(w,d->primary?",\"primary\":true":",\"primary\":false");
        jsonw_raw(w,d->untested?",\"untested\":true":",\"untested\":false");
        jsonw_raw(w,",\"latest_migration\":");if(d->latest_migration.p)jsonw_string(w,d->latest_migration);else jsonw_raw(w,"null");
        jsonw_raw(w,",\"accepted_sessions\":");jsonw_i128(w,d->accepted_sessions);
        jsonw_raw(w,",\"accepted_messages\":");jsonw_i128(w,d->accepted_messages);jsonw_raw(w,"}");
    }
    size_t sessions=0,subagents=0,archived=0;
    if(in->corpus)for(OmapEntry *q=in->corpus->sessions.first;q;q=q->next){const SessionModel *row=q->value;if(row->provider!=PROVIDER_OPENCODE)continue;if(row->is_subagent)subagents++;else sessions++;if(row->archived)archived++;}
    jsonw_raw(w,"],\"sessions\":");jsonw_i128(w,sessions);jsonw_raw(w,",\"subagents\":");jsonw_i128(w,subagents);
    jsonw_raw(w,",\"archived\":");jsonw_i128(w,archived);jsonw_raw(w,",\"requests\":");jsonw_i128(w,u?u->requests:0);
    jsonw_raw(w,",\"requests_without_usage\":");jsonw_i128(w,u?u->missing_usage:0);jsonw_raw(w,",\"residual_sessions\":");jsonw_i128(w,u?u->residual_count:0);
    /* Legacy snapshot consumers sum logs across source entries. Databases do
     * not add log files; keep that additive consumer contract numeric. */
    jsonw_raw(w,",\"logs\":0,\"cached\":0,\"costs\":{\"available\":true,\"reason\":null}}");
}
static void sources(JsonWriter *w,const PayloadInputs *in){
    const ClaudeScan *c=in->claude;jsonw_raw(w,",\"sources\":{\"codex\":{\"status\":");text(w,in->codex_present?"ok":"absent");jsonw_raw(w,",\"home\":");text(w,in->source_codex_home?in->source_codex_home:in->codex_home);
    jsonw_raw(w,",\"logs\":");jsonw_i64(w,in->scan?(int64_t)(in->scan->count+in->scan->unreadable_count):0);jsonw_raw(w,",\"parsed\":");jsonw_i64(w,in->scan?(int64_t)in->scan->parsed:0);jsonw_raw(w,",\"cached\":");jsonw_i64(w,in->scan?(int64_t)in->scan->cached:0);jsonw_raw(w,",\"costs\":{\"available\":");jsonw_raw(w,!in->ledger||in->ledger->available?"true":"false");jsonw_raw(w,",\"reason\":");if(in->ledger&&in->ledger->reason.p)jsonw_string(w,in->ledger->reason);else jsonw_raw(w,"null");jsonw_raw(w,"}},\"claude\":{\"status\":");text(w,c&&c->disabled?"disabled":c&&c->present?"ok":"absent");jsonw_raw(w,",\"roots\":[");
    if(c)for(size_t i=0;i<c->root_count;i++){if(i)jsonw_raw(w,",");jsonw_string(w,c->roots[i].path);}jsonw_raw(w,"],\"history_path\":");if(c)jsonw_string(w,c->history_path);else jsonw_raw(w,"null");jsonw_raw(w,",\"logs\":");jsonw_i64(w,c?(int64_t)c->logs:0);jsonw_raw(w,",\"parsed\":");jsonw_i64(w,c?(int64_t)c->parsed:0);jsonw_raw(w,",\"cached\":");jsonw_i128(w,c?c->cached:0);jsonw_raw(w,",\"retained\":");jsonw_i128(w,c?c->retained:0);jsonw_raw(w,",\"history_only\":");jsonw_i128(w,c?c->history_only:0);jsonw_raw(w,",\"token_data_from_ms\":");if(c&&c->token_data_from_ms.present)jsonw_i64(w,c->token_data_from_ms.value);else jsonw_raw(w,"null");jsonw_raw(w,",\"costs\":{\"available\":true,\"reason\":null}}");opencode_source(w,in);antigravity_source(w,in);jsonw_raw(w,"}");
}
static uint64_t lines(const ClaudeRecord *r,int kind){return kind==0?r->reader.malformed:kind==1?r->reader.partial_final_line:r->reader.recovered;}
static void oc_map(JsonWriter *w,const Omap *map){
    jsonw_raw(w,"{");if(map)for(OmapEntry *q=map->first;q;q=q->next){if(q!=map->first)jsonw_raw(w,",");jsonw_string(w,q->key);jsonw_raw(w,":");jsonw_i128(w,*(uint64_t *)q->value);}jsonw_raw(w,"}");
}
static void oc_context(JsonWriter *w,Str id,Str database,const char *reason){
    jsonw_raw(w,"{\"session\":");jsonw_string(w,id);jsonw_raw(w,",\"database\":");jsonw_string(w,database);jsonw_raw(w,",\"reason\":");text(w,reason);
}
static void oc_contexts(JsonWriter *w,const OpencodeStore *s,const CorpusStrings *ids,const char *reason){
    jsonw_raw(w,"[");if(s&&ids)for(size_t i=0;i<ids->count;i++){const OpencodeSession *row=omap_get(&s->session_ids,ids->items[i]);if(i)jsonw_raw(w,",");oc_context(w,ids->items[i],row?row->database:(Str){0},reason);jsonw_raw(w,"}");}jsonw_raw(w,"]");
}
static void oc_difference(JsonWriter *w,const OpencodeUsageDifference *d,const char *reason){
    const OpencodeTokens *t=&d->tokens;
    jsonw_raw(w,"{\"session\":");jsonw_string(w,d->session->id);jsonw_raw(w,",\"database\":");jsonw_string(w,d->session->database);
    if(reason){jsonw_raw(w,",\"reason\":");text(w,reason);}
    jsonw_raw(w,",\"input\":");jsonw_i128(w,t->input);jsonw_raw(w,",\"output\":");jsonw_i128(w,t->output);
    jsonw_raw(w,",\"reasoning\":");jsonw_i128(w,t->reasoning);jsonw_raw(w,",\"cache_read\":");jsonw_i128(w,t->cache_read);jsonw_raw(w,",\"cache_write\":");jsonw_i128(w,t->cache_write);
    jsonw_raw(w,",\"cost\":");if(d->has_cost)jsonw_double(w,d->cost);else jsonw_raw(w,"null");
    jsonw_raw(w,",\"date\":");if(d->date.present)jsonw_i64(w,d->date.value);else jsonw_raw(w,"null");jsonw_raw(w,",\"date_basis\":\"session_start\"}");
}
static void opencode_diagnostics(JsonWriter *w,const OpencodeStore *s){
    const OpencodeUsageReport *u=s?s->usage:NULL;
    const char *keys[]={"opencode_schema_errors","opencode_unreadable_databases","opencode_untested_schema"};
    for(int k=0;k<3;k++){
        jsonw_raw(w,",");text(w,keys[k]);jsonw_raw(w,":[");bool first=true;
        if(s)for(size_t i=0;i<s->database_count;i++){const OpencodeDatabase *d=&s->databases[i];if(!(k==0?d->status==OC_DB_UNSUPPORTED:k==1?d->status==OC_DB_UNREADABLE:d->untested))continue;
            if(!first)jsonw_raw(w,",");first=false;jsonw_raw(w,"{\"path\":");jsonw_string(w,d->path);jsonw_raw(w,k==2?",\"latest_migration\":":",\"reason\":");jsonw_string(w,k==2?d->latest_migration:d->reason);jsonw_raw(w,"}");}
        jsonw_raw(w,"]");
    }
    jsonw_raw(w,",\"opencode_session_id_collisions\":");oc_contexts(w,s,s?&s->corpus_collisions:NULL,"session id belongs to another provider");
    jsonw_raw(w,",\"opencode_orphaned_subagents\":");oc_contexts(w,s,s?&s->orphaned_subagents:NULL,"parent missing or cyclic");
    jsonw_raw(w,",\"opencode_spawn_conflicts\":");oc_contexts(w,s,s?&s->ambiguous_spawns:NULL,"multiple parent tool spawns");
    jsonw_raw(w,",\"opencode_unknown_clocks\":");oc_contexts(w,s,s?&s->unknown_clocks:NULL,"message clock unavailable");
    jsonw_raw(w,",\"opencode_duplicate_sessions\":[");if(s)for(size_t i=0;i<s->duplicate_count;i++){const OpencodeDiagnostic *d=&s->duplicates[i];if(i)jsonw_raw(w,",");oc_context(w,d->session,d->database,d->reason.p);jsonw_raw(w,"}");}jsonw_raw(w,"]");
    jsonw_raw(w,",\"opencode_rollup_shortfalls\":[");if(u)for(size_t i=0;i<u->shortfall_count;i++){if(i)jsonw_raw(w,",");oc_difference(w,&u->shortfalls[i],"message totals exceed session rollup");}jsonw_raw(w,"]");
    jsonw_raw(w,",\"opencode_invalid_numbers\":[");bool first=true;
    if(s)for(size_t i=0;i<s->session_count;i++){const OpencodeSession *row=s->sessions[i];if(!row->invalid_numbers)continue;if(!first)jsonw_raw(w,",");first=false;oc_context(w,row->id,row->database,"invalid source numeric fields");jsonw_raw(w,",\"count\":");jsonw_i128(w,row->invalid_numbers);jsonw_raw(w,"}");}
    const char *reasons[]={"invalid rollup tokens","invalid rollup cost","message token sum overflow","message cost sum overflow","residual cost arithmetic overflow"};
    if(u)for(size_t i=0;i<u->invalid_count;i++){const OpencodeUsageInvalid *d=&u->invalid[i];if(!first)jsonw_raw(w,",");first=false;oc_context(w,d->session->id,d->session->database,reasons[d->context]);jsonw_raw(w,"}");}jsonw_raw(w,"]");
    jsonw_raw(w,",\"opencode_unknown_message_types\":");oc_map(w,s?&s->unknown_message_types:NULL);
    jsonw_raw(w,",\"opencode_unknown_content_types\":");oc_map(w,s?&s->unknown_content_types:NULL);
    jsonw_raw(w,",\"opencode_requests_without_usage\":");oc_map(w,u?&u->missing_by_provider:NULL);
    jsonw_raw(w,",\"opencode_rollup_residuals\":{");if(u)for(size_t i=0;i<u->residual_count;i++){if(i)jsonw_raw(w,",");jsonw_string(w,u->residuals[i].session->id);jsonw_raw(w,":");oc_difference(w,&u->residuals[i],NULL);}jsonw_raw(w,"}");
    jsonw_raw(w,",\"opencode_malformed_messages\":");jsonw_i128(w,s?s->malformed_messages:0);
    jsonw_raw(w,",\"opencode_inherited_messages\":");jsonw_i128(w,u?u->inherited:0);
    jsonw_raw(w,",\"opencode_cost_without_tokens\":");jsonw_i128(w,u?u->cost_only:0);
}
static void line_diagnostic(JsonWriter *w,const FileDiagnostic *d,const ClaudeScan *c,int kind){
    __int128 total=d?d->total:0;if(c&&!c->disabled){if(!kind)total+=c->history_malformed;for(size_t i=0;i<c->count;i++)total+=lines(&c->records[i],kind);}jsonw_raw(w,"{\"total\":");jsonw_i128(w,total);jsonw_raw(w,",\"files\":[");bool first=true;
    if(d)for(size_t i=0;i<d->count;i++){if(!first)jsonw_raw(w,",");first=false;jsonw_raw(w,"{\"path\":");jsonw_string(w,d->files[i].path);jsonw_raw(w,",\"count\":");jsonw_i64(w,(int64_t)d->files[i].count);jsonw_raw(w,"}");}
    if(c&&!c->disabled)for(size_t i=0;i<=c->count;i++){uint64_t n=i==c->count?(!kind?c->history_malformed:0):lines(&c->records[i],kind);if(!n)continue;if(!first)jsonw_raw(w,",");first=false;jsonw_raw(w,"{\"path\":");jsonw_string(w,i==c->count?c->history_path:c->records[i].key.path);jsonw_raw(w,",\"count\":");jsonw_i64(w,(int64_t)n);jsonw_raw(w,"}");}jsonw_raw(w,"]}");
}
static const Omap *claude_map(const ClaudeRecord *r,bool dropped){return dropped?&r->rows_dropped:&r->reader.unknown_types;}
static void claude_map_json(JsonWriter *w,const ClaudeScan *c,bool dropped){
    jsonw_raw(w,"{");Omap seen={0};bool first=true;
    if(c)for(size_t i=0;i<c->count;i++)for(OmapEntry *p=claude_map(&c->records[i],dropped)->first;p;p=p->next){if(omap_get(&seen,p->key))continue;Err e=omap_put(&seen,p->key,(void *)1);if(e.code){w->error=e;break;}__int128 n=0;for(size_t j=0;j<c->count;j++){uint64_t *v=omap_get(claude_map(&c->records[j],dropped),p->key);if(v)n+=*v;}if(!first)jsonw_raw(w,",");first=false;jsonw_string(w,p->key);jsonw_raw(w,":");jsonw_i128(w,n);}omap_destroy(&seen);jsonw_raw(w,"}");
}
static void claude_diagnostics(JsonWriter *w,const ClaudeScan *c){
    jsonw_raw(w,",\"claude_history_alias_conflicts\":{");
    if(c)for(OmapEntry *q=c->history_conflicts.first;q;q=q->next){if(q!=c->history_conflicts.first)jsonw_raw(w,",");jsonw_string(w,q->key);jsonw_raw(w,":");payload_corpus_strings(w,q->value);}jsonw_raw(w,"}");
    jsonw_raw(w,",\"claude_session_id_collisions\":");CorpusStrings empty={0};payload_corpus_strings(w,c?&c->collisions:&empty);
    jsonw_raw(w,",\"claude_retained_unreadable\":");payload_corpus_strings(w,c?&c->retained_unreadable:&empty);
    jsonw_raw(w,",\"claude_unknown_record_types\":");claude_map_json(w,c,false);
    jsonw_raw(w,",\"claude_rows_dropped\":");claude_map_json(w,c,true);
    jsonw_raw(w,",\"claude_duplicate_responses\":{\"key_count\":");jsonw_i128(w,c?c->duplicate_keys:0);jsonw_raw(w,",\"row_count\":");jsonw_i128(w,c?c->duplicate_rows:0);jsonw_raw(w,"},\"claude_incomplete_requests\":");jsonw_i128(w,c?c->incomplete_requests:0);
}
void payload_empty(JsonWriter *w,const PayloadInputs *in){
    PayloadIds ids={0};Err identity_error=payload_ids_init(in->corpus,in->source_codex_home,&ids);
    if(identity_error.code){w->error=identity_error;payload_ids_destroy(&ids);return;}
    jsonw_raw(w,"{\"schema\":1,\"meta\":{\"version\":\"0.5.1\",\"generated_at_ms\":");jsonw_i64(w,in->snapshot_ms);
    jsonw_raw(w,",\"generated_tz\":");text(w,in->timezone);jsonw_raw(w,",\"codex_home\":");text(w,in->codex_home);
    jsonw_raw(w,",\"counts\":{\"logs\":");jsonw_i64(w,(int64_t)in->logs);
    jsonw_raw(w,",\"parsed\":");jsonw_i64(w,(int64_t)in->parsed);
    jsonw_raw(w,",\"cached\":");jsonw_i64(w,(int64_t)in->cached);
    size_t sessions=0,agents=0,orphans=0;if(in->corpus)for(OmapEntry *q=in->corpus->sessions.first;q;q=q->next){SessionModel *s=q->value;if(s->provider!=PROVIDER_CODEX)continue;if(str_equal(s->kind,STR_LIT("subagent")))agents++;else sessions++;if(s->flags&F_ORPHAN)orphans++;}
    jsonw_raw(w,",\"sessions\":");jsonw_i64(w,(int64_t)sessions);jsonw_raw(w,",\"subagents\":");jsonw_i64(w,(int64_t)agents);jsonw_raw(w,",\"orphans\":");jsonw_i64(w,(int64_t)orphans);jsonw_raw(w,"},\"catalog\":{\"status\":");
    text(w,in->catalog?in->catalog->status:"unavailable");jsonw_raw(w,",\"fetched_at_ms\":");if(in->catalog&&in->catalog->has_fetched_at)jsonw_i64(w,in->catalog->fetched_at_ms);else jsonw_raw(w,"null");jsonw_raw(w,",\"checked_at_ms\":");if(in->catalog&&in->catalog->has_checked_at)jsonw_i64(w,in->catalog->checked_at_ms);else jsonw_raw(w,"null");jsonw_raw(w,",\"source_host\":");
    if(in->source_host)text(w,in->source_host);else jsonw_raw(w,"null");
    jsonw_raw(w,"}");sources(w,in);jsonw_raw(w,",\"costs\":{\"available\":");jsonw_raw(w,!in->ledger||in->ledger->available?"true":"false");jsonw_raw(w,",\"reason\":");if(in->ledger&&in->ledger->reason.p)jsonw_string(w,in->ledger->reason);else jsonw_raw(w,"null");jsonw_raw(w,"},\"live_quiet_ms\":7200000,"
        "\"links\":{\"open_in_codex\":{\"live\":true,\"archived\":false,\"subagent\":true},"
        "\"continue_in_cli\":{\"live\":true,\"archived\":true,\"subagent\":false},\"claude_continue_in_cli\":{\"live\":true,\"archived\":true,\"subagent\":false}}},"
        "\"sessions\":");payload_sessions(w,in->corpus,&ids);jsonw_raw(w,",\"subagents\":");payload_subagents(w,in->corpus,&ids);jsonw_raw(w,",\"workspaces\":");payload_workspaces(w,in->corpus);jsonw_raw(w,",\"models\":");
    if(in->pricing)pricing_models_json(w,in->pricing);else jsonw_raw(w,"{}");jsonw_raw(w,",\"diagnostics\":{\"skipped_files\":[");
    bool skipped_first=true;
    if(in->corpus)for(size_t i=0;i<in->corpus->skipped_file_count;i++){
        if(!skipped_first)jsonw_raw(w,",");skipped_first=false;const SkippedFile *r=&in->corpus->skipped_files[i];jsonw_raw(w,"{\"path\":");jsonw_string(w,r->path);jsonw_raw(w,",\"reason\":");jsonw_string(w,r->reason);jsonw_raw(w,"}");
    }
    if(in->scan)for(size_t i=0;i<in->scan->unreadable_count;i++){
        if(!skipped_first)jsonw_raw(w,",");skipped_first=false;jsonw_raw(w,"{\"path\":");jsonw_string(w,in->scan->unreadable[i].path);
        jsonw_raw(w,",\"reason\":\"unreadable\"}");
    }
    if(in->claude)for(size_t i=0;i<in->claude->skipped_count;i++){if(!skipped_first)jsonw_raw(w,",");skipped_first=false;jsonw_raw(w,"{\"path\":");jsonw_string(w,in->claude->skipped[i].path);jsonw_raw(w,",\"reason\":\"unreadable\"}");}
    jsonw_raw(w,"],\"malformed_lines\":");line_diagnostic(w,in->corpus?&in->corpus->malformed:NULL,in->claude,0);
    jsonw_raw(w,",\"truncated_lines\":");line_diagnostic(w,in->corpus?&in->corpus->truncated:NULL,in->claude,1);
    jsonw_raw(w,",\"recovered_lines\":");line_diagnostic(w,in->corpus?&in->corpus->recovered:NULL,in->claude,2);
    jsonw_raw(w,",\"unknown_record_types\":");payload_unknown_types(w,in->corpus);
    claude_diagnostics(w,in->claude);
    opencode_diagnostics(w,in->opencode);antigravity_diagnostics(w,in->antigravity);
    jsonw_raw(w,",\"claude_desktop_sessions_without_transcripts\":");jsonw_i128(w,in->claude?in->claude->desktop_without_transcripts:0);
    jsonw_raw(w,",\"claude_orphaned_subagents\":");CorpusStrings claude_empty={0};payload_corpus_strings(w,in->corpus?&in->corpus->claude_orphaned_subagents:&claude_empty);
    jsonw_raw(w,",\"db_threads_without_logs\":");jsonw_i64(w,in->corpus?(int64_t)in->corpus->db_threads_without_logs:0);
    jsonw_raw(w,",\"metadata_errors\":[");bool metadata_first=true;if(in->metadata)for(MetadataError *p=in->metadata->errors;p;p=p->next){if(!metadata_first)jsonw_raw(w,",");metadata_first=false;jsonw_string(w,p->text);}if(in->claude)for(size_t i=0;i<in->claude->metadata_errors.count;i++){if(!metadata_first)jsonw_raw(w,",");metadata_first=false;jsonw_string(w,in->claude->metadata_errors.items[i]);}jsonw_raw(w,"],"
        "\"orphaned_subagents\":");CorpusStrings empty={0};payload_references(w,&ids,in->corpus?&in->corpus->orphaned_subagents:&empty);jsonw_raw(w,",\"inferred_links\":");payload_references(w,&ids,in->corpus?&in->corpus->inferred_links:&empty);jsonw_raw(w,",\"unresolved_history_boundaries\":");
    payload_unresolved_history(w,in->corpus,&ids);
    jsonw_raw(w,",\"fork_baseline_unavailable\":");payload_references(w,&ids,in->corpus?&in->corpus->fork_baselines:&empty);
    jsonw_raw(w,",\"duplicate_session_ids\":");if(in->corpus)compose_duplicate_ids_json(w,in->corpus);else jsonw_raw(w,"[]");jsonw_raw(w,",\"unpriced_models\":");
    Omap no_map={0};const PricingReport *p=in->pricing;
    pricing_diagnostic_json(w,p?&p->unpriced:&no_map,"tokens",false,false);
    jsonw_raw(w,",\"history_begins\":");pricing_diagnostic_json(w,p?&p->history_begins:&no_map,"from_ms",true,false);
    jsonw_raw(w,",\"priority_without_multiplier\":");pricing_diagnostic_json(w,p?&p->priority_without_multiplier:&no_map,"input_tokens",false,false);
    jsonw_raw(w,",\"unrecorded_catalog_rates\":");pricing_diagnostic_json(w,p?&p->unrecorded:&no_map,NULL,false,true);
    jsonw_raw(w,",\"ledger\":");if(in->ledger)runtime_ledger_json(w,in->ledger);else jsonw_raw(w,"[]");
    jsonw_raw(w,",\"untimed_usage\":");pricing_diagnostic_json(w,p?&p->untimed:&no_map,"tokens",false,false);
    jsonw_raw(w,",\"workspaces_file\":");payload_corpus_strings(w,in->workspace_errors?in->workspace_errors:&empty);jsonw_raw(w,",\"catalog\":[");
    if(in->catalog)for(CatalogMessage *message=in->catalog->messages;message;message=message->next){if(message!=in->catalog->messages)jsonw_raw(w,",");jsonw_string(w,message->text);}jsonw_raw(w,"],\"trace_db\":");payload_corpus_strings(w,in->corpus?&in->corpus->trace_messages:&empty);jsonw_raw(w,",\"page_size_bytes\":");
    jsonw_i64(w,(int64_t)in->page_size);jsonw_raw(w,",\"page_size_over_limit\":");jsonw_raw(w,in->over_limit?"true":"false");jsonw_raw(w,"}}");payload_ids_destroy(&ids);
}
