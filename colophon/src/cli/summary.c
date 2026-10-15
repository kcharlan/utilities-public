#include "summary.h"
#include <stdio.h>
#include <math.h>
#include <stdlib.h>
#include "util/events.h"
#include "util/sort.h"
#include "out/session_payload.h"
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
Err summary_run(const char *output,size_t size,const PayloadInputs *in) {
    size_t sessions=0,agents=0;__int128 tokens=0;double sum=0.0,correction=0.0;bool available=in->ledger->available;
    const Corpus *corpus=in->corpus;
    for(OmapEntry *entry=corpus->sessions.first;entry;entry=entry->next) {
        const SessionModel *session=entry->value;if(str_equal(session->kind,STR_LIT("subagent")))agents++;else sessions++;
        for(size_t i=0;i<session->unit_count;i++) {
            const UsageUnit *unit=&session->units[i];tokens+=unit->input+unit->output;
            if(!unit->has_cost){available=false;continue;}
            double value=unit->cost_usd,next=sum+value;
            if(!isfinite(next))correction=0.0;
            else if(fabs(sum)>=fabs(value))correction+=(sum-next)+value;else correction+=(value-next)+sum;
            sum=next;
        }
    }
    if(tokens<INT64_MIN||tokens>INT64_MAX)event_note("int128_payload_sum","summary.tokens",1);
    printf("colophon: %zu sessions · %zu subagents · %zu logs (%zu parsed, %zu cached) · ",sessions,agents,in->logs+(in->claude?in->claude->logs:0),in->parsed+(in->claude?in->claude->parsed:0),in->cached);decimal(stdout,tokens,true);
    fputs(" tokens · ",stdout);if(available)printf("$%.2f",sum+correction);else fputs("costs unavailable",stdout);
    printf(" est. · page %.2f MB → %s\n",(double)size/(1024*1024),output);
    bool first=true;__int128 unknown=0;for(OmapEntry *e=corpus->unknown_types.first;e;e=e->next)unknown+=*(__int128 *)e->value;
    size_t metadata=0,ledger=0,catalog=0;for(MetadataError *e=in->metadata->errors;e;e=e->next)metadata++;
    for(LedgerDiagnostic *e=in->ledger->diagnostics;e;e=e->next)ledger++;
    for(CatalogMessage *e=in->catalog->messages;e;e=e->next)catalog++;
    __int128 malformed=corpus->malformed.total,truncated=corpus->truncated.total,recovered=corpus->recovered.total,claude_unknown=0;
    if(in->claude&&!in->claude->disabled){malformed+=in->claude->history_malformed;for(size_t i=0;i<in->claude->count;i++){const ReaderResult *r=&in->claude->records[i].reader;malformed+=r->malformed;truncated+=r->partial_final_line;recovered+=r->recovered;for(OmapEntry *q=r->unknown_types.first;q;q=q->next)claude_unknown+=*(uint64_t *)q->value;}}
    diagnostic("skipped_files",corpus->skipped_file_count+in->scan->unreadable_count+(in->claude?in->claude->skipped_count:0),&first);
    diagnostic("malformed_lines",malformed,&first);diagnostic("truncated_lines",truncated,&first);diagnostic("recovered_lines",recovered,&first);
    diagnostic("claude_unknown_record_types",claude_unknown,&first);diagnostic("claude_session_id_collisions",in->claude?in->claude->collisions.count:0,&first);
    diagnostic("unknown_record_types",unknown,&first);diagnostic("db_threads_without_logs",corpus->db_threads_without_logs,&first);diagnostic("metadata_errors",metadata,&first);
    diagnostic("orphaned_subagents",corpus->orphaned_subagents.count,&first);diagnostic("inferred_links",corpus->inferred_links.count,&first);
    diagnostic("unresolved_history_boundaries",payload_unresolved_history(NULL,corpus,NULL),&first);
    diagnostic("fork_baseline_unavailable",corpus->fork_baselines.count,&first);diagnostic("duplicate_session_ids",corpus->duplicate_ids.size,&first);
    diagnostic("unpriced_models",in->pricing->unpriced.size,&first);diagnostic("history_begins",in->pricing->history_begins.size,&first);diagnostic("priority_without_multiplier",in->pricing->priority_without_multiplier.size,&first);diagnostic("unrecorded_catalog_rates",in->pricing->unrecorded.size,&first);diagnostic("ledger",ledger,&first);diagnostic("untimed_usage",in->pricing->untimed.size,&first);diagnostic("workspaces_file",in->workspace_errors->count,&first);diagnostic("catalog",catalog,&first);diagnostic("trace_db",corpus->trace_messages.count,&first);diagnostic("page_size_over_limit",in->over_limit,&first);
    if(!first)fputs("; see the page footer\n",stderr);
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
