#define _DARWIN_C_SOURCE
#include "fileio.h"
#include "testing/hooks.h"
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <pwd.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

Err file_read_all(const char *path, char **bytes, size_t *length) {
    char text[256];
    int fd=open(path,O_RDONLY);
    if(fd<0) return err_make(ERR_IO,"open failed: %s",err_system(errno,text));
    size_t capacity=8192, used=0; char *buffer=malloc(capacity);
    if(!buffer){close(fd);return err_make(ERR_NOMEM,"file buffer allocation failed");}
    Err error=ERR_SUCCESS;
    for(;;) {
        if(used==capacity-1) {
            if(capacity>SIZE_MAX/2){error=err_make(ERR_NOMEM,"file too large");break;}
            char *grown=realloc(buffer,capacity*2);
            if(!grown){error=err_make(ERR_NOMEM,"file buffer allocation failed");break;}
            buffer=grown; capacity*=2;
        }
        ssize_t n=read(fd,buffer+used,capacity-used-1);
        if(n<0){if(errno==EINTR)continue;error=err_make(ERR_IO,"read failed: %s",err_system(errno,text));break;}
        if(n==0)break;
        used+=(size_t)n;
    }
    if(close(fd) && error.code==ERR_OK)error=err_make(ERR_IO,"close failed: %s",err_system(errno,text));
    if(error.code!=ERR_OK){free(buffer);return error;}
    buffer[used]=0; *bytes=buffer; *length=used; return ERR_SUCCESS;
}
static Err user_home(const char *name, char **output, bool *missing) {
    *missing=false;
    const char *env=name?NULL:getenv("HOME");
    if(env){*output=strdup(env);return *output?ERR_SUCCESS:err_make(ERR_NOMEM,"home allocation failed");}
    long hint=sysconf(_SC_GETPW_R_SIZE_MAX); size_t n=hint>0?(size_t)hint:16384;
    struct passwd pw,*found=NULL; char *buffer=NULL; int result;
    for(;;) {
        buffer=malloc(n); if(!buffer)return err_make(ERR_NOMEM,"passwd allocation failed");
        result=name?getpwnam_r(name,&pw,buffer,n,&found):getpwuid_r(getuid(),&pw,buffer,n,&found);
        if(result!=ERANGE)break;
        free(buffer); if(n>SIZE_MAX/2)return err_make(ERR_NOMEM,"passwd buffer too large"); n*=2;
    }
    if(result || !found){*missing=!result&&!found;free(buffer);return err_make(ERR_IO,"home unavailable");}
    *output=strdup(pw.pw_dir);free(buffer);
    return *output?ERR_SUCCESS:err_make(ERR_NOMEM,"home allocation failed");
}
/* pathlib's lexical POSIX normalization keeps '..' and an exactly-double
 * leading slash, but removes empty and '.' components. Never resolve links. */
Err file_lexical_path(Str raw, bool collapse_parent, Str *output) {
    const char *input=raw.p;
    size_t length=raw.n;
    if(length>SIZE_MAX-2)return err_make(ERR_NOMEM,"path too long");
    char *result=malloc(length+2);
    if(!result)return err_make(ERR_NOMEM,"path allocation failed");
    size_t used=0,i=0;
    if(length && input[0]=='/') {
        result[used++]='/';
        if(length>=2 && input[1]=='/' && (length==2 || input[2]!='/'))result[used++]='/';
        while(i<length && input[i]=='/')i++;
    }
    size_t root=used;
    while(i<length) {
        size_t start=i;
        while(i<length && input[i]!='/')i++;
        size_t count=i-start;
        if(collapse_parent && count==2 && !memcmp(input+start,"..",2)) {
            while(used>root && result[used-1]!='/')used--;
            if(used>root)used--;
        } else if(count && !(count==1 && input[start]=='.')) {
            if(used && result[used-1]!='/')result[used++]='/';
            memcpy(result+used,input+start,count);used+=count;
        }
        while(i<length && input[i]=='/')i++;
    }
    if(!used)result[used++]='.';
    result[used]=0;*output=(Str){result,(uint32_t)used};return ERR_SUCCESS;
}
static Err path_lexical(const char *raw, bool collapse_parent, char **output) {
    Str result;
    Err error=file_lexical_path((Str){raw,(uint32_t)strlen(raw)},collapse_parent,&result);
    if(!error.code)*output=(char *)result.p;
    return error;
}
Err file_expand_user(Str raw, bool missing_user_unchanged, Str *path) {
    Str setting={0};Err error=file_lexical_path(raw,false,&setting);
    if(error.code!=ERR_OK)return error;
    if(setting.p[0]!='~'){*path=setting;return ERR_SUCCESS;}
    const char *suffix=memchr(setting.p,'/',setting.n);if(!suffix)suffix=setting.p+setting.n;
    size_t name_length=(size_t)(suffix-setting.p)-1;char *name=NULL;
    if(name_length){
        if(memchr(setting.p+1,0,name_length)){free((void *)setting.p);return err_make(ERR_INVALID,"embedded null byte");}
        name=malloc(name_length+1);if(!name){free((void *)setting.p);return err_make(ERR_NOMEM,"username allocation failed");}memcpy(name,setting.p+1,name_length);name[name_length]=0;
    }
    char *home=NULL;bool missing;error=user_home(name,&home,&missing);free(name);
    if(error.code!=ERR_OK){if(missing_user_unchanged && missing){*path=setting;return ERR_SUCCESS;}free((void *)setting.p);return error;}
    size_t a=strlen(home),b=setting.n-(size_t)(suffix-setting.p);
    while(a && home[a-1]=='/')a--;
    if(a>SIZE_MAX-b-1 || a+b>UINT32_MAX){free(home);free((void *)setting.p);return err_make(ERR_NOMEM,"path too long");}
    char *expanded=malloc(a+b+1);
    if(!expanded){free(home);free((void *)setting.p);return err_make(ERR_NOMEM,"path allocation failed");}
    memcpy(expanded,home,a);memcpy(expanded+a,suffix,b);expanded[a+b]=0;free(home);free((void *)setting.p);
    error=file_lexical_path(!a && !b?STR_LIT("/"):(Str){expanded,(uint32_t)(a+b)},false,path);
    free(expanded);return error;
}
Err file_expand_path(const char *raw, char **path) {
    Str result;
    Err error=file_expand_user((Str){raw,(uint32_t)strlen(raw)},false,&result);
    if(!error.code)*path=(char *)result.p;
    return error;
}
Err runtime_home(char **path) {
    const char *raw=getenv("COLOPHON_HOME");
    return file_expand_path(raw?raw:"~/.colophon",path);
}
Err file_codex_path_key(const char *path,char **key) {
    char *absolute=NULL;
    if(path[0]=='/')absolute=strdup(path);
    else{char *cwd=getcwd(NULL,0);if(!cwd)return err_make(ERR_IO,"working directory unavailable");
        size_t n=strlen(cwd)+strlen(path)+2;absolute=malloc(n);if(absolute)snprintf(absolute,n,"%s/%s",cwd,path);free(cwd);}
    if(!absolute)return err_make(ERR_NOMEM,"path allocation failed");
    Err e=path_lexical(absolute,true,key);free(absolute);
    if(e.code==ERR_OK&&!strncmp(*key,"/private/var/",13))memmove(*key,*key+8,strlen(*key+8)+1);
    return e;
}
Err file_abbreviate_home(const char *path,char **display) {
    char *home=NULL;Err e=file_expand_path("~",&home);if(e.code!=ERR_OK)return e;
    size_t n=strlen(home);bool root=!strcmp(home,"/");
    bool matches=!strncmp(home,path,n)&&(root?path[1]!='/':(!path[n]||path[n]=='/'));
    if(matches){const char *suffix=root?path:path+n;
        *display=malloc(strlen(suffix)+2);if(*display){(*display)[0]='~';strcpy(*display+1,suffix);if(root&&!strcmp(suffix,"/"))(*display)[1]=0;}}
    else *display=strdup(path);
    free(home);return *display?ERR_SUCCESS:err_make(ERR_NOMEM,"path allocation failed");
}
Err file_mkdir_parents(const char *directory) {
    if(!directory || !*directory)return err_make(ERR_INVALID,"empty directory path");
    char *copy=strdup(directory);if(!copy)return err_make(ERR_NOMEM,"directory allocation failed");
    Err error=ERR_SUCCESS;
    for(char *p=copy+1;;p++) {
        if(*p!='/' && *p)continue;
        char saved=*p;*p=0;
        if(mkdir(copy,0700) && errno!=EEXIST){error=err_make(ERR_IO,"mkdir failed: %s",strerror(errno));break;}
        struct stat st;
        if(stat(copy,&st) || !S_ISDIR(st.st_mode)){error=err_make(ERR_IO,"parent is not a directory");break;}
        *p=saved;if(!saved)break;
    }
    free(copy);return error;
}
Err ensure_runtime_home(const char *path) {
    Err error=file_mkdir_parents(path);if(error.code!=ERR_OK)return error;
    if(chmod(path,0700))return err_make(ERR_IO,"runtime chmod failed: %s",strerror(errno));
    DIR *dir=opendir(path);if(!dir)return err_make(ERR_IO,"runtime open failed: %s",strerror(errno));
    int64_t wall=cp_wall_ms(); struct dirent *entry;
    while((entry=readdir(dir))) {
        size_t n=strlen(entry->d_name),pn=strlen(path);
        if(n<5 || entry->d_name[0]!='.' || strcmp(entry->d_name+n-4,".tmp"))continue;
        if(pn>SIZE_MAX-n-2)continue;
        char *candidate=malloc(pn+n+2);if(!candidate)continue;
        snprintf(candidate,pn+n+2,"%s/%s",path,entry->d_name);
        struct stat st;
        if(!lstat(candidate,&st) && S_ISREG(st.st_mode)) {
            long double modified=(long double)st.st_mtimespec.tv_sec*1000+st.st_mtimespec.tv_nsec/1000000.0L;
            if(modified<(long double)wall-3600000 && !cp_fault("runtime_temp_unlink"))unlink(candidate);
        }
        free(candidate);
    }
    closedir(dir);return ERR_SUCCESS;
}
