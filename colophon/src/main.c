#include "cli/args.h"
#include "cli/run.h"
#ifdef COLOPHON_TESTING
#include <string.h>
int dump_discover(void);
int dump_reader(void);
int dump_record(void);
int dump_tokens(void);
int dump_metadata(void);
int cmd_sqlite_version(void);
int cmd_scan_only(int argc,char **argv);
int cmd_assemble(int argc,char **argv);
int dump_turnstatus(void);
int dump_titles(void);
int dump_workspaces(void);
int dump_totals(void);
int dump_tracker(void);
int dump_accounting(void);
int dump_rows(void);
int dump_accounting_test(void);
int dump_priority(int argc,char **argv);
int cmd_compose(int argc,char **argv);
int cmd_price(int argc,char **argv);
int cmd_render_page(int argc);
#endif

int main(int argc, char **argv) {
#ifdef COLOPHON_TESTING
    if(argc>1&&!strcmp(argv[1],"render-page"))return cmd_render_page(argc);
    if(argc>1&&!strcmp(argv[1],"price"))return cmd_price(argc,argv);
    if(argc>1&&!strcmp(argv[1],"compose"))return cmd_compose(argc,argv);
    if(argc>1&&!strcmp(argv[1],"dump-priority"))return dump_priority(argc,argv);
    if(argc==2&&!strcmp(argv[1],"dump-accounting"))return dump_accounting();
    if(argc==2&&!strcmp(argv[1],"dump-rows"))return dump_rows();
    if(argc==2&&!strcmp(argv[1],"dump-accounting-test"))return dump_accounting_test();
    if(argc==2&&!strcmp(argv[1],"dump-totals"))return dump_totals();
    if(argc==2&&!strcmp(argv[1],"dump-tracker"))return dump_tracker();
    if(argc>1&&!strcmp(argv[1],"assemble"))return cmd_assemble(argc,argv);
    if(argc==2&&!strcmp(argv[1],"dump-turnstatus"))return dump_turnstatus();
    if(argc==2&&!strcmp(argv[1],"dump-titles"))return dump_titles();
    if(argc==2&&!strcmp(argv[1],"dump-workspaces"))return dump_workspaces();
    if(argc>1&&!strcmp(argv[1],"scan-only"))return cmd_scan_only(argc,argv);
    if (argc == 2 && !strcmp(argv[1], "dump-discover")) return dump_discover();
    if (argc == 2 && !strcmp(argv[1], "dump-reader")) return dump_reader();
    if (argc == 2 && !strcmp(argv[1], "dump-record")) return dump_record();
    if (argc == 2 && !strcmp(argv[1], "dump-tokens")) return dump_tokens();
    if (argc == 2 && !strcmp(argv[1], "dump-metadata")) return dump_metadata();
    if (argc == 2 && !strcmp(argv[1], "sqlite-version")) return cmd_sqlite_version();
#endif
    Args args;int result=args_parse(argc,argv,&args);
    return result<0?cli_run(&args):result;
}
