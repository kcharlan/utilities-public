#include "summary.h"
#include "corpus/provider.h"
#include <stdio.h>
#include <math.h>
#include <stdlib.h>
#include "util/events.h"
#include "util/sort.h"
#include "out/session_payload.h"
#include "opencode/scan.h"
#include "antigravity/scan.h"
#include "opencode/compose.h"
#include <string.h>
static void decimal(FILE *stream,__int128 value,bool grouped) {
    unsigned __int128 magnitude=value<0?(unsigned __int128)(-(value+1))+1:(unsigned __int128)value;
    char reversed[48];size_t n=0;do{reversed[n++]=(char)('0'+magnitude%10);magnitude/=10;}while(magnitude);
    if(value<0)fputc('-',stream);
    while(n){fputc(reversed[--n],stream);if(grouped&&n&&n%3==0)fputc(',',stream);}
}
static void diagnostic(const char *name,__int128 count,bool *first) {
    if(!count)return;
    if(*first)fputs("colophon: diagnostics: ",stderr);else fputs(", ",stderr);
    *first=false;fprintf(stderr,"%s=",name);decimal(stderr,count,false);
}
static int keys_order(const void *a,const void *b,void *unused){(void)unused;return str_compare(*(const Str *)a,*(const Str *)b);}
static void provider_summary(Provider provider,const PayloadInputs *in) {
    size_t sessions=0,agents=0,units=0;__int128 tokens=0;double sum=0.0,correction=0.0;bool overflow=false,available=provider!=PROVIDER_CODEX||in->ledger->available;
    const Corpus *corpus=in->corpus;
    for(OmapEntry *entry=corpus->sessions.first;entry;entry=entry->next) {
        const SessionModel *session=entry->value;if(session->provider!=provider)continue;if(str_equal(session->kind,STR_LIT("subagent"))||(provider==PROVIDER_OPENCODE&&session->is_subagent))agents++;else sessions++;
        units+=session->unit_count;
        for(size_t i=0;i<session->unit_count;i++) {
            const UsageUnit *unit=&session->units[i];tokens+=unit->input+unit->output;
            if(!unit->has_cost){available=false;continue;}
            if(overflow)continue;
            double value=unit->cost_usd,next=sum+value,adjustment=fabs(sum)>=fabs(value)?(sum-next)+value:(value-next)+sum;
            double corrected=correction+adjustment;
            if(!isfinite(value)||!isfinite(next)||!isfinite(corrected)||!isfinite(next+corrected)){
                overflow=true;available=false;Str id=provider_id(provider);
                event_note("cost_aggregate_overflow",id.p,1);
                fprintf(stderr,"colophon: cost_aggregate_overflow: provider summary %.*s; costs unavailable\n",(int)id.n,id.p);
            }else{sum=next;correction=corrected;}
        }
    }
    if(tokens<INT64_MIN||tokens>INT64_MAX)event_note("int128_payload_sum","summary.tokens",1);
    size_t logs=0,parsed=0,cached=0;
    switch(provider) {
    case PROVIDER_CODEX: logs=in->logs;parsed=in->parsed;cached=in->cached;break;
    case PROVIDER_CLAUDE: if(in->claude){logs=in->claude->logs;parsed=in->claude->parsed;cached=in->claude->cached;}break;
    case PROVIDER_OPENCODE: if(in->opencode){logs=in->opencode->database_count;for(size_t i=0;i<logs;i++)if(in->opencode->databases[i].status==OC_DB_OK)parsed++;}break;
    case PROVIDER_ANTIGRAVITY: if(in->antigravity){sessions=in->antigravity->session_count;logs=in->antigravity->database_count;for(size_t i=0;i<logs;i++)if(in->antigravity->databases[i].status==AG_DB_OK)parsed++;}break;
    }
    Str id=provider_id(provider);
    printf("colophon: %.*s: %zu sessions · %zu subagents · %zu %s (%zu parsed, %zu cached) · ",(int)id.n,id.p,sessions,agents,logs,provider==PROVIDER_OPENCODE||provider==PROVIDER_ANTIGRAVITY?"databases":"logs",parsed,cached);decimal(stdout,tokens,true);
    fputs(" tokens · ",stdout);if(!units)fputs("no priced usage",stdout);else if(available)printf("$%.2f est.",sum+correction);else fputs("costs unavailable",stdout);
    if(provider==PROVIDER_OPENCODE&&strcmp(opencode_status(in->opencode),"ok"))printf(" · %s",opencode_status(in->opencode));
    if(provider==PROVIDER_ANTIGRAVITY&&strcmp(antigravity_status(in->antigravity),"ok"))printf(" · %s",antigravity_status(in->antigravity));
    fputc('\n',stdout);
}
static __int128 oc_map_count(const Omap *map){__int128 n=0;for(OmapEntry *q=map->first;q;q=q->next)n+=*(uint64_t *)q->value;return n;}
static void oc_diagnostics(const OpencodeStore *s,bool *first){
    if(!s)return;size_t schema=0,unreadable=0,untested=0,invalid=0;
    for(size_t i=0;i<s->database_count;i++){schema+=s->databases[i].status==OC_DB_UNSUPPORTED;unreadable+=s->databases[i].status==OC_DB_UNREADABLE;untested+=s->databases[i].untested;}
    for(size_t i=0;i<s->session_count;i++)invalid+=s->sessions[i]->invalid_numbers!=0;
    const OpencodeUsageReport *u=s->usage;
    diagnostic("opencode_schema_errors",schema,first);diagnostic("opencode_unreadable_databases",unreadable,first);diagnostic("opencode_untested_schema",untested,first);
    diagnostic("opencode_session_id_collisions",s->corpus_collisions.count,first);diagnostic("opencode_duplicate_sessions",s->duplicate_count,first);
    diagnostic("opencode_orphaned_subagents",s->orphaned_subagents.count,first);diagnostic("opencode_spawn_conflicts",s->ambiguous_spawns.count,first);diagnostic("opencode_unknown_clocks",s->unknown_clocks.count,first);
    diagnostic("opencode_invalid_numbers",invalid+(u?u->invalid_count:0),first);
    diagnostic("opencode_unknown_message_types",oc_map_count(&s->unknown_message_types),first);diagnostic("opencode_unknown_content_types",oc_map_count(&s->unknown_content_types),first);
    diagnostic("opencode_malformed_messages",s->malformed_messages,first);
    if(u){diagnostic("opencode_rollup_shortfalls",u->shortfall_count,first);diagnostic("opencode_rollup_residuals",u->residual_count,first);diagnostic("opencode_requests_without_usage",oc_map_count(&u->missing_by_provider),first);diagnostic("opencode_inherited_messages",u->inherited,first);diagnostic("opencode_cost_without_tokens",u->cost_only,first);}
}
static void oc_line(Str value){for(uint32_t i=0;i<value.n;i++)fputc(value.p[i]=='\r'||value.p[i]=='\n'?' ':value.p[i],stderr);}
Err summary_run(const char *output,size_t size,const PayloadInputs *in) {
    const Corpus *corpus=in->corpus;
    provider_summary(PROVIDER_CODEX,in);
    if(in->claude&&!in->claude->disabled)provider_summary(PROVIDER_CLAUDE,in);
    if(in->opencode&&!in->opencode->disabled)provider_summary(PROVIDER_OPENCODE,in);
    if(in->antigravity&&!in->antigravity->disabled)provider_summary(PROVIDER_ANTIGRAVITY,in);
    printf("colophon: page %.2f MB → %s\n",(double)size/(1024*1024),output);
    bool first=true;__int128 unknown=0;for(OmapEntry *e=corpus->unknown_types.first;e;e=e->next)unknown+=*(__int128 *)e->value;
    size_t metadata=0,ledger=0,catalog=0;for(MetadataError *e=in->metadata->errors;e;e=e->next)metadata++;
    for(LedgerDiagnostic *e=in->ledger->diagnostics;e;e=e->next)ledger++;
    for(CatalogMessage *e=in->catalog->messages;e;e=e->next)catalog++;
    __int128 malformed=corpus->malformed.total,truncated=corpus->truncated.total,recovered=corpus->recovered.total,claude_unknown=0;
    if(in->claude&&!in->claude->disabled){malformed+=in->claude->history_malformed;for(size_t i=0;i<in->claude->count;i++){const ReaderResult *r=&in->claude->records[i].reader;malformed+=r->malformed;truncated+=r->partial_final_line;recovered+=r->recovered;for(OmapEntry *q=r->unknown_types.first;q;q=q->next)claude_unknown+=*(uint64_t *)q->value;}}
    diagnostic("skipped_files",corpus->skipped_file_count+in->scan->unreadable_count+(in->claude?in->claude->skipped_count:0),&first);
    diagnostic("malformed_lines",malformed,&first);diagnostic("truncated_lines",truncated,&first);diagnostic("recovered_lines",recovered,&first);
    diagnostic("claude_unknown_record_types",claude_unknown,&first);diagnostic("claude_session_id_collisions",in->claude?in->claude->collisions.count:0,&first);
    diagnostic("claude_history_alias_conflicts",in->claude?in->claude->history_conflicts.size:0,&first);
    diagnostic("claude_duplicate_responses",in->claude?in->claude->duplicate_rows:0,&first);diagnostic("claude_incomplete_requests",in->claude?in->claude->incomplete_requests:0,&first);
    oc_diagnostics(in->opencode,&first);
    if(in->antigravity){const AntigravityStore *s=in->antigravity;size_t schema=0,unreadable=0;
        for(size_t i=0;i<s->database_count;i++){schema+=s->databases[i].status==AG_DB_UNSUPPORTED;unreadable+=s->databases[i].status==AG_DB_UNREADABLE;}
        diagnostic("antigravity_schema_errors",schema,&first);diagnostic("antigravity_unreadable_databases",unreadable,&first);
        diagnostic("antigravity_duplicate_sessions",s->duplicate_sessions,&first);diagnostic("antigravity_archive_disagreements",s->archive_disagreements,&first);
        diagnostic("antigravity_malformed_blobs",s->malformed_blobs,&first);diagnostic("antigravity_annotation_errors",s->annotation_errors,&first);
        diagnostic("antigravity_malformed_rows",s->malformed_rows,&first);
        diagnostic("antigravity_legacy_encrypted",s->legacy_encrypted,&first);diagnostic("antigravity_source_diagnostics",s->diagnostic_count,&first);
    }
    diagnostic("unknown_record_types",unknown,&first);diagnostic("db_threads_without_logs",corpus->db_threads_without_logs,&first);diagnostic("metadata_errors",metadata,&first);
    diagnostic("orphaned_subagents",corpus->orphaned_subagents.count,&first);diagnostic("inferred_links",corpus->inferred_links.count,&first);
    diagnostic("unresolved_history_boundaries",payload_unresolved_history(NULL,corpus,NULL),&first);
    diagnostic("fork_baseline_unavailable",corpus->fork_baselines.count,&first);diagnostic("duplicate_session_ids",corpus->duplicate_ids.size,&first);
    diagnostic("unpriced_models",in->pricing->unpriced.size,&first);diagnostic("history_begins",in->pricing->history_begins.size,&first);diagnostic("priority_without_multiplier",in->pricing->priority_without_multiplier.size,&first);diagnostic("unrecorded_catalog_rates",in->pricing->unrecorded.size,&first);diagnostic("ledger",ledger,&first);diagnostic("untimed_usage",in->pricing->untimed.size,&first);diagnostic("workspaces_file",in->workspace_errors->count,&first);diagnostic("catalog",catalog,&first);diagnostic("trace_db",corpus->trace_messages.count,&first);diagnostic("page_size_over_limit",in->over_limit,&first);
    if(!first)fputs("; see the page footer\n",stderr);
    if(in->antigravity&&!in->antigravity->disabled){const AntigravityStore *s=in->antigravity;
        for(size_t i=0;i<s->database_count;i++){const AntigravityDatabase *d=&s->databases[i];if(!d->reason.n)continue;fputs("colophon: antigravity database ",stderr);oc_line(d->path);fprintf(stderr," (%s): ",antigravity_database_status(d->status));oc_line(d->reason);fputc('\n',stderr);}
        for(size_t i=0;i<s->ignored_environment_count;i++){fputs("colophon: ignored environment ",stderr);oc_line(s->ignored_environment[i]);fputs("; use --antigravity-home PATH\n",stderr);}
    }
    if(in->opencode&&!in->opencode->disabled)for(size_t i=0;i<in->opencode->database_count;i++){
        const OpencodeDatabase *d=&in->opencode->databases[i];if(!d->reason.n)continue;
        fputs("colophon: opencode database ",stderr);oc_line(d->path);fprintf(stderr," (%s): ",opencode_database_status(d->status));oc_line(d->reason);fputc('\n',stderr);
    }
    const Omap *untimed=&in->pricing->untimed;
    if(untimed->size>SIZE_MAX/sizeof(Str))return err_make(ERR_NOMEM,"summary key overflow");
    Str *keys=malloc((untimed->size?untimed->size:1)*sizeof *keys);if(!keys)return err_make(ERR_NOMEM,"summary key allocation");
    size_t n=0;for(OmapEntry *e=untimed->first;e;e=e->next)keys[n++]=e->key;
    Err error=stable_sort(keys,n,sizeof *keys,keys_order,NULL);if(error.code){free(keys);return error;}
    for(size_t i=0;i<n;i++){fprintf(stderr,"colophon: %.*s: priced at current rates: usage has no timestamp (",(int)keys[i].n,keys[i].p);decimal(stderr,*(__int128 *)omap_get(untimed,keys[i]),false);fputs(" tokens)\n",stderr);}free(keys);
    for(LedgerDiagnostic *e=in->ledger->diagnostics;e;e=e->next)fprintf(stderr,"colophon: %.*s\n",(int)e->message.n,e->message.p);
    for(size_t i=0;i<in->workspace_errors->count;i++){Str message=in->workspace_errors->items[i];fprintf(stderr,"colophon: %.*s\n",(int)message.n,message.p);}
    return ERR_SUCCESS;
}
