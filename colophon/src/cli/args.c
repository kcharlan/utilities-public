#include "args.h"
#include <stdio.h>
#include <string.h>
#include "out/jsonw.h"
#define USAGE "usage: colophon [-h] [--no-open] [--rebuild] [--offline] [--refresh-prices]\n                [--output PATH] [--codex-home PATH] [--claude-home PATH]\n                [--claude-desktop-dir PATH] [--no-claude] [--opencode-db PATH]\n                [--no-opencode] [--antigravity-home PATH] [--no-antigravity] [--version]\n"
static const char *names[]={"--help","--no-open","--rebuild","--offline","--refresh-prices","--output","--codex-home","--version","--claude-home","--claude-desktop-dir","--no-claude","--opencode-db","--no-opencode","--antigravity-home","--no-antigravity"};
#define OPTION_COUNT (sizeof names / sizeof *names)
static int error(const char *message){fputs(USAGE,stderr);fprintf(stderr,"colophon: error: %s\n",message);return 2;}
const char *args_conflict(const Args *args){return args->offline&&args->refresh_prices?"--offline and --refresh-prices cannot be combined":NULL;}
static bool optional_value(const char *s){
    if(s[0]!='-'||!s[1]||strchr(s,' '))return false;
    const char *p=s+1;bool digits=false,point=false;
    while(*p){if(*p>='0'&&*p<='9')digits=true;else if(*p=='.'&&!point)point=true;else return true;p++;}
    return !digits || (point&&p[-1]=='.');
}
int args_parse(int argc,char **argv,Args *out){
    *out=(Args){.codex_home="~/.codex"};char message[1024];JsonWriter unknown={0};
    for(int i=1;i<argc;i++){
#ifdef COLOPHON_TESTING
        if(!strcmp(argv[i],"--phase-times")){out->phase_times=true;continue;}
#endif
        const char *s=argv[i],*equal=strchr(s,'=');size_t n=equal?(size_t)(equal-s):strlen(s);int match=-1,count=0;
        if(!strcmp(s,"--")){for(;i<argc;i++){if(unknown.length)jsonw_raw(&unknown," ");jsonw_raw(&unknown,argv[i]);}break;}
        if(s[0]=='-'&&s[1]=='h'){match=0;if(s[2]!='=')equal=NULL;}
        else if(n>2&&s[0]=='-'&&s[1]=='-'){
            for(int k=0;(size_t)k<OPTION_COUNT;k++)if(strlen(names[k])==n&&!strncmp(s,names[k],n)){match=k;break;}
            if(match<0)for(int k=0;(size_t)k<OPTION_COUNT;k++)if(!strncmp(s,names[k],n)){match=k;count++;}
        }
        if(count>1){int used=snprintf(message,sizeof message,"ambiguous option: %.*s could match ",(int)n,s);
            for(int k=0,first=1;(size_t)k<OPTION_COUNT;k++)if(!strncmp(s,names[k],n)){used+=snprintf(message+used,sizeof message-(size_t)used,"%s%s",first?"":", ",names[k]);first=0;}
            jsonw_free(&unknown);return error(message);}
        if(match<0){if(unknown.length)jsonw_raw(&unknown," ");jsonw_raw(&unknown,s);continue;}
        if(match==5||match==6||match==8||match==9||match==11||match==13){const char *value=equal?equal+1:NULL;
            if(!value){if(i+1==argc||optional_value(argv[i+1])){snprintf(message,sizeof message,"argument %s: expected one argument",names[match]);jsonw_free(&unknown);return error(message);}value=argv[++i];}
            if(match==5)out->output=value;else if(match==6)out->codex_home=value;else if(match==8)out->claude_home=value;else if(match==9)out->claude_desktop_dir=value;else if(match==13)out->antigravity_home=value;else if(match==11){if(!strcmp(value,":memory:")){jsonw_free(&unknown);return error("--opencode-db requires a file path, not :memory:");}out->opencode_db=value;}continue;}
        if(equal){snprintf(message,sizeof message,"argument %s: ignored explicit argument '%s'",names[match],equal+1);jsonw_free(&unknown);return error(message);}
        if(match==0){jsonw_free(&unknown);fputs(USAGE,stdout);puts("\nExplore local Codex, Claude Code and OpenCode sessions in a self-contained offline page.\n\noptions:\n  -h, --help         show this help message and exit\n  --no-open          Do not open a browser.\n  --rebuild          Reparse every log into a fresh cache.\n  --offline          Use cached prices without a network request.\n  --refresh-prices   Force an unconditional price-catalog download.\n  --output PATH      Page path instead of the runtime-home default.\n  --codex-home PATH  Read Codex data from PATH (default: ~/.codex).\n  --claude-home PATH  Literal config root (default: CLAUDE_CONFIG_DIR or ~/.claude).\n  --claude-desktop-dir PATH  Desktop source directory override.\n  --no-claude        Disable Claude inputs and reconciliation.\n  --opencode-db PATH  Read only the selected OpenCode database file.\n  --no-opencode      Disable OpenCode database discovery and reads.\n  --antigravity-home PATH  Gemini root (default: ~/.gemini).\n  --no-antigravity   Disable Antigravity discovery and reads.\n  --version          show program's version number and exit\n\nEnvironment variables:\n  CLAUDE_CONFIG_DIR     Literal Claude config root; empty selects defaults.\n  OPENCODE_DB          Primary database (relative to OpenCode data directory).\n  XDG_DATA_HOME        OpenCode data base (default: ~/.local/share).\n  ANTIGRAVITY_GEMINI_DIR, ANTIGRAVITY_APP_DATA_DIR, JETSKI_APP_DATA_DIR\n                       Ignored; use --antigravity-home PATH.\n  COLOPHON_HOME         Runtime home (default: ~/.colophon).\n  COLOPHON_PRICING_URL  Price catalog URL (default: https://models.dev/api.json).\n\nRuntime files (directories 0700, written files 0600):\n  colophon.html          Generated offline page.\n  cache-native/          Native per-log parse cache.\n  pricing-cache.json     Cached multi-provider price catalog.\n  price-history.json     Editable price history, initially empty.\n  priority-turns.json    Sticky memory of detected priority turns.\n  workspaces.json        Optional workspace aliases.\n  workspaces.example.json  Synthetic template, never read as configuration.\n\nStandalone development checks (from the source project):\n  make test            C units, synthetic CLI/integration and Chromium cases.\n  make sanitize        Same checks under ASan/UBSan.\n  make tsan            C units under ThreadSanitizer.\n  make check-assets    Embedded asset digest guard.\n  make check-sort      Stable-sort guard.\n  Keep synthetic fixtures and evidence outside the public checkout.");return 0;}
        if(match==7){jsonw_free(&unknown);puts("colophon 0.4.2");return 0;}
        if(match==1)out->no_open=true;else if(match==2)out->rebuild=true;else if(match==3)out->offline=true;else if(match==10)out->no_claude=true;else if(match==12)out->no_opencode=true;else if(match==14)out->no_antigravity=true;else if(match==4)out->refresh_prices=true;
    }
    if(unknown.data){fputs(USAGE,stderr);fprintf(stderr,"colophon: error: unrecognized arguments: %s\n",unknown.data);jsonw_free(&unknown);return 2;}
    jsonw_free(&unknown);
    const char *conflict=args_conflict(out);if(conflict)return error(conflict);
    return -1;
}
