#include "progress.h"
#include "testing/hooks.h"
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <math.h>
#include <stdio.h>
#include <signal.h>
bool progress_tty(void){
#ifdef COLOPHON_TESTING
    const char *s=getenv("COLOPHON_TEST_TTY");if(s)return !strcmp(s,"1");
#endif
    return isatty(STDERR_FILENO)!=0;
}
Err progress_scan_start(double *start){Err e=cp_monotonic_start();return e.code==ERR_OK?cp_monotonic(start):e;}
Err progress_update(uint64_t done,uint64_t total,void *context){
    ScanDisplay *display=context;if(!display->tty)return ERR_SUCCESS;
    double now;Err e=cp_monotonic(&now);if(e.code)return e;
    char eta[80],line[256];
    if(done>=total)snprintf(eta,sizeof eta,"0");
    else if(!done)snprintf(eta,sizeof eta,"?");
    else snprintf(eta,sizeof eta,"%.0f",ceil((now-display->start)*(double)(total-done)/(double)done));
    int n=snprintf(line,sizeof line,"colophon: parsing %.1f/%.1f MB · ETA %ss",(double)done/1048576,(double)total/1048576,eta);
    if(n<0||(size_t)n>=sizeof line)return err_make(ERR_INVALID,"progress format failed");
    /* Python pads by codepoints; the middle dot occupies two UTF8 bytes. */
    size_t width=(size_t)n-1;if(width>display->width)display->width=width;
    fprintf(stderr,"\r%s%*s",line,(int)(display->width-width),"");fflush(stderr);display->active=true;
    if(cp_fault("progress_interrupt")){raise(SIGINT);return err_make(ERR_IO,"interrupted");}
    return ERR_SUCCESS;
}
void progress_close(ScanDisplay *display){if(display->active){fputc('\n',stderr);display->active=false;}}
