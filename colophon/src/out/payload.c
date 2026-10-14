#include "payload.h"
#include "session_payload.h"
#include "price/compose.h"
#include <stdlib.h>
#include <string.h>
static void text(JsonWriter *w,const char *s){jsonw_string(w,(Str){s,(uint32_t)strlen(s)});}
void payload_empty(JsonWriter *w,const PayloadInputs *in){
    PayloadIds ids={0};Err identity_error=payload_ids_init(in->corpus,in->source_codex_home,&ids);
    if(identity_error.code){w->error=identity_error;payload_ids_destroy(&ids);return;}
    jsonw_raw(w,"{\"schema\":1,\"meta\":{\"version\":\"0.1.0\",\"generated_at_ms\":");jsonw_i64(w,in->snapshot_ms);
    jsonw_raw(w,",\"generated_tz\":");text(w,in->timezone);jsonw_raw(w,",\"codex_home\":");text(w,in->codex_home);
    jsonw_raw(w,",\"counts\":{\"logs\":");jsonw_i64(w,(int64_t)in->logs);
    jsonw_raw(w,",\"parsed\":");jsonw_i64(w,(int64_t)in->parsed);
    jsonw_raw(w,",\"cached\":");jsonw_i64(w,(int64_t)in->cached);
    size_t sessions=0,agents=0;if(in->corpus)for(OmapEntry *q=in->corpus->sessions.first;q;q=q->next){SessionModel *s=q->value;if(str_equal(s->kind,STR_LIT("subagent")))agents++;else sessions++;}
    jsonw_raw(w,",\"sessions\":");jsonw_i64(w,(int64_t)sessions);jsonw_raw(w,",\"subagents\":");jsonw_i64(w,(int64_t)agents);jsonw_raw(w,",\"orphans\":");jsonw_i64(w,in->corpus?(int64_t)in->corpus->orphaned_subagents.count:0);jsonw_raw(w,"},\"catalog\":{\"status\":");
    text(w,in->catalog?in->catalog->status:"unavailable");jsonw_raw(w,",\"fetched_at_ms\":");if(in->catalog&&in->catalog->has_fetched_at)jsonw_i64(w,in->catalog->fetched_at_ms);else jsonw_raw(w,"null");jsonw_raw(w,",\"checked_at_ms\":");if(in->catalog&&in->catalog->has_checked_at)jsonw_i64(w,in->catalog->checked_at_ms);else jsonw_raw(w,"null");jsonw_raw(w,",\"source_host\":");
    if(in->source_host)text(w,in->source_host);else jsonw_raw(w,"null");
    jsonw_raw(w,"},\"costs\":{\"available\":");jsonw_raw(w,!in->ledger||in->ledger->available?"true":"false");jsonw_raw(w,",\"reason\":");if(in->ledger&&in->ledger->reason.p)jsonw_string(w,in->ledger->reason);else jsonw_raw(w,"null");jsonw_raw(w,"},\"live_quiet_ms\":7200000,"
        "\"links\":{\"open_in_codex\":{\"live\":true,\"archived\":false,\"subagent\":true},"
        "\"continue_in_cli\":{\"live\":true,\"archived\":true,\"subagent\":false}}},"
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
    jsonw_raw(w,"],\"malformed_lines\":");payload_file_diagnostic(w,in->corpus?&in->corpus->malformed:NULL);
    jsonw_raw(w,",\"truncated_lines\":");payload_file_diagnostic(w,in->corpus?&in->corpus->truncated:NULL);
    jsonw_raw(w,",\"recovered_lines\":");payload_file_diagnostic(w,in->corpus?&in->corpus->recovered:NULL);
    jsonw_raw(w,",\"unknown_record_types\":");payload_unknown_types(w,in->corpus);
    jsonw_raw(w,",\"db_threads_without_logs\":");jsonw_i64(w,in->corpus?(int64_t)in->corpus->db_threads_without_logs:0);
    jsonw_raw(w,",\"metadata_errors\":[");if(in->metadata)for(MetadataError *p=in->metadata->errors;p;p=p->next){if(p!=in->metadata->errors)jsonw_raw(w,",");jsonw_string(w,p->text);}jsonw_raw(w,"],"
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
