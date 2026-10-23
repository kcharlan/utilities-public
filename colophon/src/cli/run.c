#define _DARWIN_C_SOURCE
#include "run.h"
#include "browser.h"
#include "progress.h"
#include "summary.h"
#include "claude/scan.h"
#include "claude/store.h"
#include "claude/metadata.h"
#include "claude/compose.h"
#include "opencode/scan.h"
#include "antigravity/scan.h"
#include "antigravity/corpus.h"
#include "antigravity/compose.h"
#include "opencode/corpus.h"
#include "opencode/compose.h"
#include "out/payload.h"
#include "out/page.h"
#include "scan/scan.h"
#include "corpus/workspaces.h"
#include "price/compose.h"
#include "price/claude_cost.h"
#include "testing/hooks.h"
#include "testing/phase_times.h"
#include "util/atomic.h"
#include "util/events.h"
#include "util/fileio.h"
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
static volatile sig_atomic_t interrupted;
static void error_line(const char *message){
    for(const unsigned char *p=(const unsigned char *)message;*p;p++)
        fputc(*p=='\r'||*p=='\n'?' ':*p,stderr);
}
static void interrupt_handler(int sig){(void)sig;interrupted=1;}
static char *join(const char *home,const char *name){size_t n=strlen(home)+strlen(name)+2;char *p=malloc(n);if(p)snprintf(p,n,"%s/%s",home,name);return p;}
static Err templates(const char *home){
    const char *names[]={"price-history.json","workspaces.example.json","priority-turns.json"};
    const char *bytes[]={"{\n  \"schema\": 1,\n  \"entries\": []\n}\n",
        "{\n  \"schema\": 1,\n  \"aliases\": [\n    {\n      \"name\": \"Example Tools\",\n      \"origins\": [\n        \"https://example.invalid/synthetic/tools.git\"\n      ],\n      \"paths\": [\n        \"/synthetic/deployed/tools\"\n      ]\n    }\n  ]\n}\n",
        "{\n  \"schema\": 1,\n  \"turns\": {}\n}\n"};
    for(int i=0;i<3;i++){char *p=join(home,names[i]);if(!p)return err_make(ERR_NOMEM,"path allocation failed");struct stat st;Err e=ERR_SUCCESS;if(stat(p,&st))e=atomic_write(p,bytes[i],strlen(bytes[i]));free(p);if(e.code!=ERR_OK)return e;}return ERR_SUCCESS;
}
char *cli_source_host(const char *url){
    const char *start=strstr(url,"://");if(start)start+=3;else if(!strncmp(url,"//",2))start=url+2;else return NULL;
    size_t n=strcspn(start,"/?#");const char *last=NULL;for(size_t i=0;i<n;i++)if(start[i]=='@')last=start+i;
    if(last){n-=(size_t)(last+1-start);start=last+1;}if(!n)return NULL;
    if(*start=='['){start++;const char *end=memchr(start,']',n-1);if(!end)return NULL;n=(size_t)(end-start);}
    else{const char *colon=memchr(start,':',n);if(colon)n=(size_t)(colon-start);}
    if(!n)return NULL;Arena arena={0};Str lower;
    const char *zone=memchr(start,'%',n);size_t prefix=zone?(size_t)(zone-start):n;
    Err e=str_lower(&arena,(Str){start,(uint32_t)prefix},&lower);char *host=NULL;
    if(e.code==ERR_OK){host=malloc(lower.n+n-prefix+1);if(host){memcpy(host,lower.p,lower.n);memcpy(host+lower.n,start+prefix,n-prefix);host[lower.n+n-prefix]=0;}}
    arena_destroy(&arena);return host;
}
int cli_run(const Args *args){
    CP_PHASE_START(args->phase_times);
    const char *conflict=args_conflict(args);if(conflict){fprintf(stderr,"colophon: %s\n",conflict);return 2;}
    char *codex=NULL,*home=NULL,*output=NULL,*display=NULL,*host=NULL,*ledger_path=NULL;JsonWriter payload={0},page={0};
    Cache cache={0};ScanResult scan={0};ScanDisplay scan_display={0};ClaudeScan claude={0};ClaudeStore claude_store={0};bool codex_present=false,cache_opened=false;
    CodexMetadata metadata={0};Corpus corpus={0};OpencodeStore opencode={0};AntigravityStore antigravity={0};AssemblyRecord *assembly_records=NULL;WorkspaceAliases aliases={0};PriorityTurns priority={0};
    CatalogResult catalog={0};CatalogFetch *fetch=NULL;ModelsDevIndex index={0};RuntimeLedger ledger={0};PriceHistory history={0};PricingReport pricing={0};LedgerAppend appended={0};yyjson_doc *recording=NULL,*new_entries=NULL;
    bool home_exists=false,page_failure=false,committed=false,clock_started=false;int result=1;Err failure=ERR_SUCCESS;
    const char *failure_type="OSError";struct sigaction previous,action={0};bool handler=false;
    failure=file_expand_path(args->codex_home,&codex);if(failure.code!=ERR_OK)goto fail;
    struct stat st;codex_present=!stat(codex,&st)&&S_ISDIR(st.st_mode)&&!access(codex,R_OK|X_OK);
    failure=runtime_home(&home);if(failure.code!=ERR_OK)goto fail;
    failure=claude_inspect(args,&claude);if(failure.code)goto fail;
    action.sa_handler=interrupt_handler;sigemptyset(&action.sa_mask);interrupted=0;handler=sigaction(SIGINT,&action,&previous)==0;
    failure=claude_store_inspect(home,&claude,args->rebuild,&claude_store);if(failure.code)goto fail;
    claude.store=&claude_store;
    failure=claude_scan(&claude,&interrupted);if(failure.code)goto fail;
    failure=claude_store_reconcile(&claude_store,&claude,&interrupted);if(failure.code)goto fail;
    failure=claude_scan_aliases(&claude);if(failure.code)goto fail;
    failure=opencode_discover(args,&opencode);if(failure.code)goto fail;
    failure=opencode_store_read(&opencode,&interrupted);if(failure.code)goto fail;
    failure=antigravity_discover(args,&antigravity);if(failure.code)goto fail;
    failure=antigravity_store_read(&antigravity,&interrupted);if(failure.code)goto fail;
    if(!codex_present&&!claude.present&&!opencode.present&&!antigravity.present){fprintf(stderr,"colophon: no readable sources; Codex home is missing or unreadable: %s; Claude roots:",codex);for(size_t i=0;i<claude.root_count;i++)fprintf(stderr," %s",claude.roots[i].path.p);fprintf(stderr,"; history: %s%s; OpenCode:",claude.history_path.p,claude.disabled?" (--no-claude)":"");if(opencode.data_dir.p){fputc(' ',stderr);error_line(opencode.data_dir.p);}for(size_t i=0;i<opencode.database_count;i++){fputc(' ',stderr);error_line(opencode.databases[i].path.p);}fprintf(stderr,"%s; Antigravity:",opencode.disabled?" (--no-opencode)":"");if(antigravity.home.p){fputc(' ',stderr);error_line(antigravity.home.p);}fprintf(stderr,"%s\n",antigravity.disabled?" (--no-antigravity)":"");goto done;}
    int64_t snapshot=cp_now_ms();scan_display.tty=progress_tty();
    failure=ensure_runtime_home(home);home_exists=!stat(home,&st)&&S_ISDIR(st.st_mode);if(failure.code!=ERR_OK)goto fail;
    failure=templates(home);if(failure.code!=ERR_OK)goto fail;
    ledger_path=join(home,"price-history.json");if(!ledger_path){failure=err_make(ERR_NOMEM,"path allocation failed");goto fail;}
    int stat_result=stat(ledger_path,&st);if(stat_result){failure=err_make(ERR_IO,"ledger stat failed");goto fail;}
    /* Snapshot before catalog/scan; later ledger recording consumes this. */
    struct timespec ledger_mtime=st.st_mtimespec;
    if(cp_fault("catalog_thread_start")){failure=err_make(ERR_IO,"synthetic injected catalog_thread_start");failure_type="RuntimeError";goto fail;}
    const char *url=getenv("COLOPHON_PRICING_URL");if(!url)url="https://models.dev/api.json";
    char *catalog_path=join(home,"pricing-cache.json");if(!catalog_path){failure=err_make(ERR_NOMEM,"path allocation failed");goto fail;}
    failure=catalog_fetch_start(catalog_path,(Str){url,(uint32_t)strlen(url)},args->offline,args->refresh_prices,snapshot,&fetch);free(catalog_path);if(failure.code)goto fail;
    if(codex_present){failure=cache_open(home,args->rebuild,&cache);if(failure.code!=ERR_OK)goto fail;cache_opened=true;}
    clock_started=true;failure=progress_scan_start(&scan_display.start);if(failure.code!=ERR_OK){failure_type="RuntimeError";goto fail;}
    CP_PHASE_MARK(0);
    if(cp_fault("scan")){failure=err_make(ERR_IO,"synthetic injected scan");goto fail;}
    if(codex_present)failure=scan_logs(codex,&cache,&interrupted,progress_update,&scan_display,&scan);progress_close(&scan_display);
    if(failure.code!=ERR_OK){if(failure.code==ERR_INVALID)failure_type="ValueError";goto fail;}
    /* scan -> metadata -> corpus -> links -> workspaces -> catalog join. */
    CP_PHASE_MARK(1);
    if(codex_present){failure=metadata_load(codex,&metadata);if(failure.code)goto fail;}
    if(cp_fault("original_error_abort_failure")){failure=err_make(ERR_INVALID,"Synthetic original failure\nsecond line");failure_type="ValueError";goto fail;}
    if(cp_fault("build_corpus")){failure=err_make(ERR_IO,"synthetic injected build_corpus");goto fail;}
    assembly_records=calloc(scan.count?scan.count:1,sizeof *assembly_records);if(!assembly_records){failure=err_make(ERR_NOMEM,"assembly input allocation failed");goto fail;}
    for(size_t i=0;i<scan.count;i++)assembly_records[i]=assembly_record(scan.records[i]);
    failure=corpus_build(assembly_records,scan.count,&metadata,snapshot,&scan.identifiers,&corpus);if(failure.code)goto fail;
    failure=corpus_link_subagents(&corpus,&metadata,snapshot);if(failure.code)goto fail;
    failure=claude_metadata_load(&claude);if(failure.code)goto fail;
    failure=claude_corpus_add(claude.records,claude.count,snapshot,&corpus,&claude.collisions);if(failure.code)goto fail;
    failure=claude_metadata_apply(&claude,&corpus);if(failure.code)goto fail;
    failure=opencode_corpus_add(&opencode,snapshot,&corpus);if(failure.code)goto fail;
    failure=antigravity_corpus_add(&antigravity,snapshot,&corpus);if(failure.code)goto fail;
    char *alias_path=join(home,"workspaces.json");if(!alias_path){failure=err_make(ERR_NOMEM,"alias path allocation failed");goto fail;}
    failure=workspace_aliases_load(alias_path,&aliases);free(alias_path);if(failure.code)goto fail;
    failure=corpus_resolve_workspaces(&corpus,&aliases);if(failure.code)goto fail;
    CP_PHASE_MARK(2);
    failure=catalog_fetch_finish(&fetch,&catalog);if(failure.code)goto fail;
    CP_PHASE_MARK(3);
    if(codex_present){failure=priority_load(codex,home,&priority);if(failure.code)goto fail;}
    failure=models_dev_index(catalog.catalog?yyjson_doc_get_root(catalog.catalog):NULL,&index);if(failure.code)goto fail;
    failure=runtime_ledger_load(ledger_path,&ledger);if(failure.code)goto fail;
    failure=runtime_ledger_history(&ledger,NULL,&history);if(failure.code)goto fail;
    if(ledger.available&&catalog.catalog&&catalog.has_fetched_at) {
        failure=pricing_recording_models(&corpus,&priority,&index,&recording);if(failure.code)goto fail;
        failure=record_catalog_rates(&history,&index,catalog.fetched_at_ms,yyjson_doc_get_root(recording),snapshot,&new_entries);if(failure.code)goto fail;
        __int128 start_ns=(__int128)ledger_mtime.tv_sec*1000000000+ledger_mtime.tv_nsec;
        if(start_ns<INT64_MIN||start_ns>INT64_MAX){failure=err_make(ERR_INVALID,"ledger mtime outside int64");goto fail;}
        failure=append_user_ledger(ledger_path,yyjson_doc_get_root(new_entries),true,(int64_t)start_ns,&appended);if(failure.code)goto fail;
        if(appended.warning.p){failure=runtime_ledger_warning(&ledger,ledger_path,appended.warning);if(failure.code)goto fail;}
        if(appended.appended){history_destroy(&history);failure=runtime_ledger_history(&ledger,yyjson_doc_get_root(new_entries),&history);if(failure.code)goto fail;}
    }
    failure=compose_usage(&corpus,&priority);if(failure.code)goto fail;
    failure=price_units(&corpus,&history,catalog.catalog?&index:NULL,ledger.available,&pricing);if(failure.code)goto fail;
    failure=claude_capture_prices(&claude,catalog.catalog?&index:NULL);if(failure.code)goto fail;
    failure=claude_compose(&claude,&corpus);if(failure.code)goto fail;
    failure=claude_price_units(&corpus,catalog.catalog?&index:NULL,&pricing);if(failure.code)goto fail;
    failure=opencode_compose(&opencode,&corpus);if(failure.code)goto fail;
    failure=antigravity_compose(&antigravity,&corpus,catalog.catalog?&index:NULL,&pricing);if(failure.code)goto fail;
    failure=compose_refresh_costs(&corpus,ledger.available);if(failure.code)goto fail;
    if(cp_fault("cache_abort_fail")){failure=err_make(ERR_INVALID,"synthetic injected cache_abort_fail");failure_type="ValueError";goto fail;}
    char *key=NULL;failure=file_codex_path_key(codex,&key);if(failure.code==ERR_OK)failure=file_abbreviate_home(key,&display);free(key);if(failure.code!=ERR_OK)goto fail;
    host=cli_source_host(url);
    tzset();time_t now=time(NULL);struct tm local;char zone[128]="";if(localtime_r(&now,&local))strftime(zone,sizeof zone,"%Z",&local);
    PayloadInputs in={.snapshot_ms=snapshot,.codex_home=display,.source_host=host,.timezone=zone,
        .logs=scan.count+scan.unreadable_count,.parsed=scan.parsed,.cached=scan.cached,.scan=&scan,.corpus=&corpus,.metadata=&metadata,.source_codex_home=codex,.workspace_errors=&aliases.errors,.pricing=&pricing,.catalog=&catalog,.ledger=&ledger,.codex_present=codex_present,.claude=&claude,.opencode=&opencode,.antigravity=&antigravity};
    CP_PHASE_MARK(4);
    size_t max=0,limit=cp_page_warn_bytes();bool converged=false;
    for(int i=0;i<3;i++){jsonw_free(&payload);jsonw_free(&page);payload_empty(&payload,&in);failure=page_render(&payload,&page);if(failure.code!=ERR_OK){if(failure.code==ERR_INVALID)failure_type="ValueError";goto fail;}
        size_t size=page.length;if(size>max)max=size;bool over=size>limit;if(in.page_size==size&&in.over_limit==over){converged=true;break;}in.page_size=size;in.over_limit=over;}
    if(!converged){in.page_size=max;in.over_limit=max>limit;jsonw_free(&payload);jsonw_free(&page);payload_empty(&payload,&in);failure=page_render(&payload,&page);if(failure.code!=ERR_OK){if(failure.code==ERR_INVALID)failure_type="ValueError";goto fail;}}
    if(args->output)failure=file_expand_path(args->output,&output);else{output=join(home,"colophon.html");if(!output)failure=err_make(ERR_NOMEM,"path allocation failed");}if(failure.code!=ERR_OK)goto fail;
    CP_PHASE_MARK(5);
    if(interrupted)goto fail;
    failure=cp_fault("original_page_failure")?err_make(ERR_IO,"Synthetic page failure"):
        cp_fault("page_replace")?err_make(ERR_IO,"synthetic injected page_replace"):atomic_write(output,page.data,page.length);
    if(failure.code!=ERR_OK){page_failure=true;goto fail;}
    failure=claude_store_commit(&claude_store,&claude,&interrupted);if(failure.code)goto fail;
    if(cache_opened){failure=cache_commit(&cache,&scan.live,&interrupted);committed=cache.committed;}
    if(failure.code!=ERR_OK)goto fail;
    if(interrupted)goto fail;
    if(!args->no_open){bool opened=browser_open(output);if(interrupted)goto fail;
        if(!opened){event_note("browser_open_fallback","browser",1);fprintf(stderr,"colophon: open %s in a browser\n",output);}}
    if(clock_started){clock_started=false;failure=cp_monotonic_finish();if(failure.code!=ERR_OK){failure_type="RuntimeError";goto fail;}}
    if(interrupted)goto fail;
    failure=summary_run(output,page.length,&in);if(failure.code)goto fail;CP_PHASE_MARK(6);result=0;goto done;
fail:
    /* Serialize cancellation with any in-flight cache commit before deciding
     * to exit, then join before main-owned runtime/event resources are freed. */
    catalog_fetch_cancel(&fetch);
    progress_close(&scan_display);
    if(interrupted){fprintf(stderr,"colophon: interrupted%s\n",args->rebuild?(committed?"; rebuild cache installed":"; rebuild did not complete; previous cache kept"):"");}
    else{if(page_failure)fprintf(stderr,"colophon: cannot write %s: ",output);else fprintf(stderr,"colophon: %s: ",failure_type);
        error_line(failure.message);fputc('\n',stderr);
        if(args->rebuild)fprintf(stderr,"colophon: %s\n",committed?"rebuild cache installed":"rebuild did not complete; previous cache kept");}
done:
    CP_PHASE_FINISH();
    catalog_fetch_cancel(&fetch);
    corpus_destroy(&corpus);pricing_report_destroy(&pricing);history_destroy(&history);runtime_ledger_destroy(&ledger);models_dev_destroy(&index);catalog_result_destroy(&catalog);ledger_append_destroy(&appended);yyjson_doc_free(recording);yyjson_doc_free(new_entries);priority_destroy(&priority);workspace_aliases_destroy(&aliases);free(assembly_records);metadata_destroy(&metadata);cache_destroy(&cache);scan_destroy(&scan);
    if(clock_started)(void)cp_monotonic_finish();if(home_exists)event_flush(home);
    if(handler)sigaction(SIGINT,&previous,NULL);
    antigravity_store_destroy(&antigravity);opencode_store_destroy(&opencode);claude_store_destroy(&claude_store);claude_scan_destroy(&claude);jsonw_free(&payload);jsonw_free(&page);free(codex);free(home);free(output);free(display);free(host);free(ledger_path);return result;
}
