#include "phase_times.h"
#include "hooks.h"
#include <stdio.h>
#include <string.h>
#include <mach/mach.h>
#include <stdint.h>
static bool active;
static double started, previous, durations[7];
static uint64_t resident[7];
static bool resident_valid[7];
void cp_phase_start(bool enabled){
    active=enabled;memset(durations,0,sizeof durations);
    memset(resident,0,sizeof resident);memset(resident_valid,0,sizeof resident_valid);
    if(active && cp_real_monotonic(&started).code)active=false;
    previous=started;
}
void cp_phase_mark(unsigned stage){
    if(!active || stage>=7)return;
    double now;if(cp_real_monotonic(&now).code){active=false;return;}
    durations[stage]+=(now-previous)*1000;previous=now;
    /* task_info observes this product process at the existing boundary. It
     * neither advances a test clock nor reports wait4's lifetime peak. A Mach
     * failure is represented by null, never by a plausible zero measurement. */
    mach_task_basic_info_data_t info;
    mach_msg_type_number_t count=MACH_TASK_BASIC_INFO_COUNT;
    kern_return_t status=task_info(mach_task_self(),MACH_TASK_BASIC_INFO,
        (task_info_t)&info,&count);
    if(status==KERN_SUCCESS && count==MACH_TASK_BASIC_INFO_COUNT){
        resident[stage]=info.resident_size;resident_valid[stage]=true;
    }
}
void cp_phase_finish(void){
    if(!active)return;
    double now;if(cp_real_monotonic(&now).code){active=false;return;}
    const char *names[]={"runtime","scan","metadata_corpus_workspaces","catalog_wait",
        "priority_pricing","payload_page","write_commit_browser_summary"};
    fputs("{\"phase_times_ms\":{",stderr);
    for(unsigned i=0;i<7;i++)fprintf(stderr,"%s\"%s\":%.9f",i?",":"",names[i],durations[i]);
    fprintf(stderr,",\"total\":%.9f},\"phase_resident_bytes\":{",(now-started)*1000);
    for(unsigned i=0;i<7;i++){
        fprintf(stderr,"%s\"%s\":",i?",":"",names[i]);
        if(resident_valid[i])fprintf(stderr,"%llu",(unsigned long long)resident[i]);
        else fputs("null",stderr);
    }
    fputs("}}\n",stderr);active=false;
}
