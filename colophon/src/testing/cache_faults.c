#define _DARWIN_C_SOURCE
#include "cache_faults.h"
#include "util/atomic.h"
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <dirent.h>
#include <fcntl.h>
#include <limits.h>
#include <signal.h>
#include <time.h>
#include <unistd.h>
#include "hooks.h"

Err test_cache_prune_barrier(void){
    const char *root=getenv("COLOPHON_TEST_PRUNE_BARRIER");if(!root)return ERR_SUCCESS;
    DIR *initial=opendir(root);if(!initial)return err_make(ERR_IO,"synthetic prune barrier unavailable");
    struct dirent *prior;
    while((prior=readdir(initial)))if(!strncmp(prior->d_name,"passed-",7)){
        closedir(initial);return err_make(ERR_IO,"synthetic prune barrier stale completion marker");
    }
    closedir(initial);
    size_t n=strlen(root)+64;char *marker=malloc(n);if(!marker)return err_make(ERR_NOMEM,"synthetic prune barrier allocation");
    snprintf(marker,n,"%s/ready-%d",root,getpid());
    int fd=open(marker,O_WRONLY|O_CREAT|O_EXCL,0600);free(marker);
    if(fd<0)return err_make(ERR_IO,"synthetic prune barrier marker rejected");close(fd);
    double start;Err e=cp_real_monotonic(&start);if(e.code)return e;
    for(;;){
        DIR *directory=opendir(root);if(!directory)return err_make(ERR_IO,"synthetic prune barrier unavailable");
        unsigned ready=0;struct dirent *entry;
        while((entry=readdir(directory))){
            if(!strcmp(entry->d_name,".")||!strcmp(entry->d_name,".."))continue;
            if(!strncmp(entry->d_name,"passed-",7))continue;
            if(strlen(entry->d_name)<=6 || strncmp(entry->d_name,"ready-",6)){
                closedir(directory);return err_make(ERR_IO,"synthetic prune barrier stale or invalid marker");
            }
            char *end=NULL;long pid=strtol(entry->d_name+6,&end,10);
            char completed[PATH_MAX];snprintf(completed,sizeof completed,"%s/passed-%ld",root,pid);
            /* A completed participant may exit before its peer's next poll.
             * Completion cannot predate the fresh caller's ready marker. */
            if(!end||*end||pid<=0||pid>INT_MAX||(kill((pid_t)pid,0)&&access(completed,F_OK))){
                closedir(directory);return err_make(ERR_IO,"synthetic prune barrier stale or invalid marker");
            }
            ready++;
        }
        closedir(directory);if(ready==2){
            char completed[PATH_MAX];snprintf(completed,sizeof completed,"%s/passed-%d",root,getpid());
            int done=open(completed,O_WRONLY|O_CREAT|O_EXCL,0600);
            if(done<0)return err_make(ERR_IO,"synthetic prune barrier completion rejected");
            close(done);return ERR_SUCCESS;
        }
        if(ready>2)return err_make(ERR_IO,"synthetic prune barrier participant count");
        double now;e=cp_real_monotonic(&now);if(e.code)return e;
        if(now-start>=10)return err_make(ERR_IO,"synthetic prune barrier timeout");
        struct timespec pause={0,10000000};if(nanosleep(&pause,NULL)&&errno==EINTR)return err_make(ERR_IO,"synthetic prune barrier interrupted");
    }
}
/* Mirrors source test_missing_install_path_does_not_prove_backup_ownership:
 * preserve the owned directory, replace its name with a foreign directory,
 * then the caller delivers an interrupt at the completed backup boundary. */
Err test_cache_replace_backup(const char *home, const char *old) {
    size_t n = strlen(home) + sizeof "/synthetic-preserved-original";
    size_t marker_size = strlen(old) + sizeof "/synthetic-marker";
    char *preserved = malloc(n), *marker = malloc(marker_size);
    if (!preserved || !marker) {
        free(preserved);
        free(marker);
        return err_make(ERR_NOMEM, "synthetic cache fault allocation failed");
    }
    snprintf(preserved, n, "%s/synthetic-preserved-original", home);
    snprintf(marker, marker_size, "%s/synthetic-marker", old);
    Err e = ERR_SUCCESS;
    if (rename(old, preserved) || mkdir(old, 0700))
        e = err_make(ERR_IO, "synthetic backup replacement failed: %s", strerror(errno));
    if (!e.code)
        e = atomic_write(marker, "synthetic foreign directory", 27);
    free(preserved);
    free(marker);
    return e;
}
