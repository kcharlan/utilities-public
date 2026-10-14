#define _DARWIN_C_SOURCE
#include "runner.h"
#include "cli/run.h"
#include "cli/progress.h"
#include "cli/summary.h"
#include "testing/hooks.h"
#include "testing/cache_faults.h"
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <signal.h>
#include <sys/wait.h>

TEST(run_conflict_precedes_home_resolution) {
    FILE *capture=tmpfile();ASSERT_TRUE(capture);int saved=dup(STDERR_FILENO);ASSERT_TRUE(saved>=0);
    ASSERT_TRUE(dup2(fileno(capture),STDERR_FILENO)>=0);
    Args args={.offline=true,.refresh_prices=true,.codex_home="/tmp/synthetic-colophon-missing"};
    int result=cli_run(&args);fflush(stderr);int restored=dup2(saved,STDERR_FILENO);close(saved);
    rewind(capture);char message[512];size_t n=fread(message,1,sizeof message-1,capture);message[n]=0;fclose(capture);
    ASSERT_TRUE(restored>=0);ASSERT_EQ(2,result);
    ASSERT_STREQ("colophon: --offline and --refresh-prices cannot be combined\n",message);
}

static char *captured(FILE *file,int saved,int descriptor){
    fflush(descriptor==2?stderr:stdout);ASSERT_EQ(descriptor,dup2(saved,descriptor));close(saved);
    ASSERT_EQ(0,fseek(file,0,SEEK_END));long length=ftell(file);ASSERT_TRUE(length>=0);
    ASSERT_EQ(0,fseek(file,0,SEEK_SET));char *text=calloc((size_t)length+1,1);ASSERT_TRUE(text);
    ASSERT_EQ((size_t)length,fread(text,1,(size_t)length,file));fclose(file);return text;
}
TEST(cli_original_progress_format_cases){
    struct {uint64_t done,total;const char *clock,*expected;} cases[]={
        {1048576,4194304,"0,2","\rcolophon: parsing 1.0/4.0 MB · ETA 6s\n"},
        {1048576,2097152,"0,1.2","\rcolophon: parsing 1.0/2.0 MB · ETA 2s\n"},
        {524288,1048576,"0,3","\rcolophon: parsing 0.5/1.0 MB · ETA 3s\n"},
        {1048576,1048576,"0,4","\rcolophon: parsing 1.0/1.0 MB · ETA 0s\n"},
        {0,1048576,"0,3","\rcolophon: parsing 0.0/1.0 MB · ETA ?s\n"},
        {0,0,"0,3","\rcolophon: parsing 0.0/0.0 MB · ETA 0s\n"}
    };
    for(size_t i=0;i<6;i++){
        setenv("COLOPHON_TEST_MONOTONIC",cases[i].clock,1);
        FILE *file=tmpfile();ASSERT_TRUE(file);int saved=dup(2);ASSERT_TRUE(saved>=0);ASSERT_EQ(2,dup2(fileno(file),2));
        ScanDisplay display={.tty=true};Err start=progress_scan_start(&display.start);
        Err result=progress_update(cases[i].done,cases[i].total,&display);progress_close(&display);
        char *text=captured(file,saved,2);
        ASSERT_EQ(ERR_OK,start.code);ASSERT_EQ(ERR_OK,result.code);ASSERT_EQ(ERR_OK,cp_monotonic_finish().code);
        ASSERT_STREQ(cases[i].expected,text);free(text);
    }
    unsetenv("COLOPHON_TEST_MONOTONIC");
}
TEST(cli_original_diagnostic_summary_counts_data_names_and_structured_totals){
    Corpus corpus={0};ScanResult scan={0};CodexMetadata metadata={0};RuntimeLedger ledger={.available=true};
    CatalogResult catalog={0};PricingReport pricing={0};CorpusStrings errors={0};
    __int128 one=1,two=2;ASSERT_EQ(ERR_OK,omap_put(&corpus.unknown_types,STR_LIT("total"),&one).code);
    ASSERT_EQ(ERR_OK,omap_put(&corpus.unknown_types,STR_LIT("files"),&two).code);
    corpus.malformed.total=3;corpus.truncated.total=3;corpus.recovered.total=3;
    PayloadInputs inputs={.corpus=&corpus,.scan=&scan,.metadata=&metadata,.ledger=&ledger,
        .catalog=&catalog,.pricing=&pricing,.workspace_errors=&errors};
    FILE *out=tmpfile(),*err=tmpfile();ASSERT_TRUE(out&&err);int saved_out=dup(1),saved_err=dup(2);
    ASSERT_EQ(1,dup2(fileno(out),1));ASSERT_EQ(2,dup2(fileno(err),2));
    Err result=summary_run("/synthetic/page.html",0,&inputs);
    char *stdout_text=captured(out,saved_out,1),*stderr_text=captured(err,saved_err,2);
    ASSERT_EQ(ERR_OK,result.code);
    ASSERT_STREQ("colophon: diagnostics: malformed_lines=3, truncated_lines=3, recovered_lines=3, unknown_record_types=3; see the page footer\n",stderr_text);
    free(stdout_text);free(stderr_text);omap_destroy(&corpus.unknown_types);
}
TEST(cli_prune_barrier_rejects_stale_and_duplicate_markers_and_bounds_wait){
    char root[]="/tmp/colophon-prune-negative.XXXXXX";ASSERT_TRUE(mkdtemp(root));
    setenv("COLOPHON_TEST_PRUNE_BARRIER",root,1);
    char marker[512];snprintf(marker,sizeof marker,"%s/ready-2147483647",root);
    int fd=open(marker,O_WRONLY|O_CREAT|O_EXCL,0600);ASSERT_TRUE(fd>=0);close(fd);
    ASSERT_EQ(ERR_IO,test_cache_prune_barrier().code);unlink(marker);
    snprintf(marker,sizeof marker,"%s/ready-%d",root,getpid());unlink(marker);
    double before,after;ASSERT_EQ(ERR_OK,cp_real_monotonic(&before).code);
    Err result=test_cache_prune_barrier();ASSERT_EQ(ERR_OK,cp_real_monotonic(&after).code);
    ASSERT_EQ(ERR_IO,result.code);ASSERT_TRUE(strstr(result.message,"timeout"));ASSERT_TRUE(after-before>=10&&after-before<11);
    ASSERT_EQ(ERR_IO,test_cache_prune_barrier().code);unlink(marker);rmdir(root);
    unsetenv("COLOPHON_TEST_PRUNE_BARRIER");ASSERT_EQ(ERR_OK,test_cache_prune_barrier().code);
}

TEST(cli_prune_barrier_two_processes_complete_and_cannot_reuse_markers){
    char root[]="/tmp/colophon-prune-pair.XXXXXX";ASSERT_TRUE(mkdtemp(root));
    setenv("COLOPHON_TEST_PRUNE_BARRIER",root,1);
    pid_t child=fork();ASSERT_TRUE(child>=0);
    if(!child){usleep(23000);_exit(test_cache_prune_barrier().code?1:0);}
    Err result=test_cache_prune_barrier();int status;ASSERT_EQ(child,waitpid(child,&status,0));
    ASSERT_EQ(ERR_OK,result.code);ASSERT_TRUE(WIFEXITED(status)&&WEXITSTATUS(status)==0);
    ASSERT_EQ(ERR_IO,test_cache_prune_barrier().code);
    char marker[512];pid_t peers[]={getpid(),child};
    for(size_t i=0;i<2;i++){
        snprintf(marker,sizeof marker,"%s/ready-%d",root,peers[i]);ASSERT_EQ(0,unlink(marker));
        snprintf(marker,sizeof marker,"%s/passed-%d",root,peers[i]);ASSERT_EQ(0,unlink(marker));
    }
    ASSERT_EQ(0,rmdir(root));unsetenv("COLOPHON_TEST_PRUNE_BARRIER");
}
