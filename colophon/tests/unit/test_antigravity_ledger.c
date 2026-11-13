#define _DARWIN_C_SOURCE
#include "antigravity/ledger.h"
#include "antigravity_fixture.h"
#include "cli/run.h"
#include "runner.h"
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/stat.h>

TEST(antigravity_ledger_roundtrip_wide_tokens_and_binary_identity){
    char base[1024];snprintf(base,sizeof base,"%s/synthetic-ag-ledger-XXXXXX",getenv("TMPDIR"));ASSERT_TRUE(mkdtemp(base));
    AntigravityStore store={.home=STR_LIT("/SYNTHETIC-GEMINI")};AntigravityLedger ledger={0};
    ASSERT_EQ(ERR_OK,antigravity_ledger_load(base,&store,&ledger).code);
    SessionModel s={.id=STR_LIT(AG_SYNTHETIC_ID),.antigravity_surface=STR_LIT("app"),.title_full=STR_LIT("Synthetic ledger"),.title_source=STR_LIT("antigravity_title")};
    AntigravitySession source={.database=STR_LIT("/SYNTHETIC-ABSENT")};
    ASSERT_EQ(ERR_OK,antigravity_ledger_begin(&ledger,&s,&source).code);
    const char raw[]={0,(char)0xff,(char)0x80,'x'};AntigravityLedgerEvent event={.model_raw=STR_LIT("synthetic-model"),.ids={{raw,sizeof raw}},.tokens={INT64_MAX,0,0,0,0,0}};
    ASSERT_EQ(ERR_OK,antigravity_ledger_capture(&ledger,&s,event).code);
    ASSERT_EQ(ERR_OK,antigravity_ledger_commit(&ledger,&store,NULL,NULL).code);
    antigravity_ledger_destroy(&ledger);
    ASSERT_EQ(ERR_OK,antigravity_ledger_load(base,&store,&ledger).code);ASSERT_EQ(1,ledger.count);ASSERT_FALSE(ledger.records[0]->unreadable);
    AntigravityLedgerEvent *actual=&ledger.records[0]->events[0];ASSERT_FALSE(actual->at_ms.present);ASSERT_EQ(INT64_MAX,actual->tokens[0]);ASSERT_EQ(sizeof raw,actual->ids[0].n);ASSERT_TRUE(!memcmp(raw,actual->ids[0].p,sizeof raw));
    char *path=strdup(ledger.records[0]->path.p),*directory=strdup(ledger.directory);ASSERT_TRUE(path&&directory);antigravity_ledger_destroy(&ledger);antigravity_store_destroy(&store);
    ASSERT_EQ(0,unlink(path));ASSERT_EQ(0,rmdir(directory));char *slash=strrchr(directory,'/');ASSERT_TRUE(slash);*slash=0;ASSERT_EQ(0,rmdir(directory));ASSERT_EQ(0,rmdir(base));free(path);free(directory);
}
TEST(antigravity_failed_page_does_not_write_ledger){
    AntigravityFixture f;antigravity_fixture_open(&f);char runtime[1024];snprintf(runtime,sizeof runtime,"%s/synthetic-runtime-XXXXXX",getenv("TMPDIR"));ASSERT_TRUE(mkdtemp(runtime));
    char *prior=strdup(getenv("COLOPHON_HOME"));ASSERT_TRUE(prior);ASSERT_EQ(0,setenv("COLOPHON_HOME",runtime,1));
    Args args={.codex_home="/SYNTHETIC-ABSENT",.antigravity_home=f.home,.no_claude=true,.no_opencode=true,.offline=true,.no_open=true};
    ASSERT_EQ(0,setenv("COLOPHON_TEST_FAULT","original_page_failure",1));ASSERT_EQ(1,cli_run(&args));ASSERT_EQ(0,unsetenv("COLOPHON_TEST_FAULT"));
    char path[1200];snprintf(path,sizeof path,"%s/antigravity-ledger",runtime);struct stat st;ASSERT_TRUE(lstat(path,&st)!=0);
    ASSERT_EQ(0,setenv("COLOPHON_HOME",prior,1));free(prior);antigravity_fixture_close(&f);
}
