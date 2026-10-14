#define _DARWIN_C_SOURCE
#include "atomic.h"
#include "fileio.h"
#include "testing/hooks.h"
#include <errno.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

Err atomic_write(const char *path, const void *bytes, size_t length) {
    if(!path || !*path || (length && !bytes))return err_make(ERR_INVALID,"invalid atomic write");
    const char *slash=strrchr(path,'/'), *name=slash?slash+1:path;
    if(!*name)return err_make(ERR_INVALID,"empty atomic filename");
    size_t pn=slash?(size_t)(slash-path):1;
    if(slash==path)pn=1;
    char *parent=malloc(pn+1);if(!parent)return err_make(ERR_NOMEM,"path allocation failed");
    if(slash)memcpy(parent,path,pn);else parent[0]='.';parent[pn]=0;
    Err error=file_mkdir_parents(parent);if(error.code!=ERR_OK){free(parent);return error;}
    size_t nn=strlen(name);
    if(pn>SIZE_MAX-nn-14){free(parent);return err_make(ERR_NOMEM,"path too long");}
    char *temp=malloc(pn+nn+14);if(!temp){free(parent);return err_make(ERR_NOMEM,"path allocation failed");}
    snprintf(temp,pn+nn+14,"%s/.%s.XXXXXX.tmp",parent,name);free(parent);
    int fd=mkstemps(temp,4);
    if(fd<0){free(temp);return err_make(ERR_IO,"temporary create failed: %s",strerror(errno));}
#ifdef COLOPHON_TESTING
    cp_atomic_created(fd);
#endif
    if(cp_fault("atomic_fchmod"))error=err_make(ERR_IO,"Synthetic fchmod failure");
    else if(fchmod(fd,0600))error=err_make(ERR_IO,"temporary chmod failed: %s",strerror(errno));
    size_t used=0;
    while(error.code==ERR_OK && used<length) {
        size_t amount=length-used;if(amount>(size_t)SSIZE_MAX)amount=SSIZE_MAX;
        ssize_t n=write(fd,(const char *)bytes+used,amount);
        if(n<0 && errno==EINTR)continue;
        if(n<=0){error=err_make(ERR_IO,"temporary write failed: %s",strerror(errno));break;}
        used+=(size_t)n;
    }
    if(error.code==ERR_OK && cp_fault("atomic_fsync"))error=err_make(ERR_IO,"Synthetic fsync failure");
    else if(error.code==ERR_OK && fsync(fd))error=err_make(ERR_IO,"temporary fsync failed: %s",strerror(errno));
#ifdef COLOPHON_TESTING
    cp_atomic_closed(fd);
#endif
    if(close(fd) && error.code==ERR_OK)error=err_make(ERR_IO,"temporary close failed: %s",strerror(errno));
    if(error.code==ERR_OK && cp_fault("atomic_replace"))error=err_make(ERR_IO,"Synthetic replace failure");
    else if(error.code==ERR_OK && rename(temp,path))error=err_make(ERR_IO,"temporary rename failed: %s",strerror(errno));
    if(error.code!=ERR_OK)unlink(temp);
    free(temp);return error;
}
