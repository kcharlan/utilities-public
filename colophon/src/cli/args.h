#ifndef CP_ARGS_H
#define CP_ARGS_H
#include <stdbool.h>
typedef struct { bool no_open,rebuild,offline,refresh_prices,no_claude,no_opencode; const char *output,*codex_home,*claude_home,*claude_desktop_dir,*opencode_db;
#ifdef COLOPHON_TESTING
    bool phase_times;
#endif
} Args;
/* -1 means continue into run; otherwise an already reported terminal status. */
int args_parse(int argc,char **argv,Args *out);
const char *args_conflict(const Args *args);
#endif
