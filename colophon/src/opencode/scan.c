#define _DARWIN_C_SOURCE
#include "scan.h"
#include "parse/record.h"
#include "util/fileio.h"
#include "util/sort.h"
#include <dirent.h>
#include <errno.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#define TRY(expr) do { Err e_=(expr); if(e_.code) return e_; } while(0)
static Str text(const char *s){return (Str){s,(uint32_t)strlen(s)};}
static Err absolute(const char *raw,const char *base,bool expand,char **out){
    char *expanded=NULL,*joined=NULL;Str normalized={0};
    Err e=expand?file_expand_path(raw,&expanded):ERR_SUCCESS;
    if(e.code)return e;
    const char *value=expand?expanded:raw;
    if(value[0]!='/'){
        char *cwd=base?NULL:getcwd(NULL,0);const char *anchor=base?base:cwd;
        if(!anchor){free(expanded);return err_make(ERR_IO,"OpenCode working directory unavailable");}
        size_t n=strlen(anchor)+strlen(value)+2;joined=malloc(n);
        if(joined)snprintf(joined,n,"%s/%s",anchor,value);free(cwd);
        if(!joined){free(expanded);return err_make(ERR_NOMEM,"OpenCode path allocation failed");}
        value=joined;
    }
    e=file_lexical_path(text(value),true,&normalized);free(expanded);free(joined);
    if(!e.code)*out=(char *)normalized.p;return e;
}
static Err candidate(OpencodeStore *s,const char *path,bool primary,const char *reason){
    for(size_t i=0;i<s->database_count;i++)if(str_equal(s->databases[i].path,text(path)))return ERR_SUCCESS;
    TRY(opencode_store_add_database(s,text(path),primary));
    OpencodeDatabase *d=&s->databases[s->database_count-1];
    const char *name=strrchr(path,'/');name=name?name+1:path;
    if(!strcmp(name,"opencode-next.db"))reason="preview database owned by OpenCode migration";
    if(reason){d->status=!strcmp(name,"opencode-next.db")?OC_DB_SKIPPED:OC_DB_UNREADABLE;TRY(str_copy(&s->arena,text(reason),&d->reason));}
    return ERR_SUCCESS;
}
static Err discovery_failure(OpencodeStore *s,const char *path,int error){
    char message[256],system[128];snprintf(message,sizeof message,"OpenCode discovery failed: %s",err_system(error,system));
    /* A separate directory diagnostic must not replace an existing primary. */
    return candidate(s,path,false,message);
}
static int path_order(const void *a,const void *b,void *unused){(void)unused;return str_compare(*(const Str *)a,*(const Str *)b);}
Err opencode_discover(const Args *args,OpencodeStore *s){
    if(s->discovered)return err_make(ERR_INVALID,"OpenCode discovery already performed");
    s->discovered=true;s->disabled=args->no_opencode;
    if(s->disabled){s->discovery_complete=true;return ERR_SUCCESS;}
    if(args->opencode_db){
        if(!strcmp(args->opencode_db,":memory:"))return err_make(ERR_INVALID,"--opencode-db requires a file path, not :memory:");
        char *path=NULL;Err e=absolute(args->opencode_db,NULL,true,&path);
        if(!e.code)e=candidate(s,path,true,NULL);
        if(!e.code){char *slash=strrchr(path,'/');size_t n=slash==(char *)path?1:(size_t)(slash-path);e=str_copy(&s->arena,(Str){path,(uint32_t)n},&s->data_dir);}
        free(path);if(e.code)return e;
    }else{
        const char *xdg=getenv("XDG_DATA_HOME"),*override=getenv("OPENCODE_DB");char *base=NULL,*directory=NULL;
        Err e=absolute(xdg&&*xdg?xdg:"~/.local/share",NULL,!(xdg&&*xdg),&base);
        if(!e.code)e=absolute("opencode",base,false,&directory);free(base);if(e.code)return e;
        e=str_copy(&s->arena,text(directory),&s->data_dir);if(e.code){free(directory);return e;}
        bool memory=override&&!strcmp(override,":memory:");
        if(!memory){char *path=NULL;
            if(override&&!*override)e=candidate(s,directory,true,"OPENCODE_DB is empty; expected a file path");
            else{e=absolute(override?override:"opencode.db",directory,false,&path);if(!e.code)e=candidate(s,path,true,NULL);}
            free(path);
        }
        DIR *dir=NULL;Str *paths=NULL;size_t count=0,capacity=0;Arena names={0};
        if(!e.code){dir=opendir(directory);if(!dir&&errno!=ENOENT)e=discovery_failure(s,directory,errno);}
        if(dir){struct dirent *entry;
            while(!e.code){errno=0;entry=readdir(dir);if(!entry){if(errno)e=discovery_failure(s,directory,errno);break;}
                size_t n=strlen(entry->d_name);
                bool matched=n>=12&&!strncmp(entry->d_name,"opencode-",9)&&!strcmp(entry->d_name+n-3,".db");
                if(!memory&&!strcmp(entry->d_name,"opencode.db"))matched=true;
                if(!matched)continue;
                char *path=NULL;e=absolute(entry->d_name,directory,false,&path);if(e.code)break;
                Str owned={0};e=str_copy(&names,text(path),&owned);
                if(!e.code)e=record_append_aligned(&names,(void **)&paths,&count,&capacity,sizeof owned,_Alignof(Str),&owned);
                free(path);
            }
            if(closedir(dir)&&!e.code)e=discovery_failure(s,directory,errno);
        }
        if(!e.code)e=stable_sort(paths,count,sizeof *paths,path_order,NULL);
        for(size_t i=0;!e.code&&i<count;i++){
            struct stat st;int result=stat(paths[i].p,&st);
            if(!result&&S_ISREG(st.st_mode))e=candidate(s,paths[i].p,false,NULL);
            else if(result&&errno!=ENOENT)e=candidate(s,paths[i].p,false,"OpenCode sibling database inaccessible");
        }
        arena_destroy(&names);free(directory);if(e.code)return e;
    }
    /* Presence is an existing non-skipped candidate or a reportable failure. */
    for(size_t i=0;i<s->database_count;i++){
        OpencodeDatabase *d=&s->databases[i];struct stat st;
        if(d->reason.n){if(d->status!=OC_DB_SKIPPED)s->present=true;continue;}
        if(!stat(d->path.p,&st)){if(S_ISREG(st.st_mode))s->present=true;}
        else if(errno!=ENOENT)s->present=true;
    }
    s->discovery_complete=true;return ERR_SUCCESS;
}
const char *opencode_database_status(OpencodeDatabaseStatus status){
    switch(status){case OC_DB_OK:return "ok";case OC_DB_ABSENT:return "absent";case OC_DB_UNREADABLE:return "unreadable";case OC_DB_UNSUPPORTED:return "unsupported";case OC_DB_SKIPPED:return "skipped";}return "unreadable";
}
const char *opencode_status(const OpencodeStore *s){
    if(s&&s->disabled)return "disabled";bool unsupported=false,unreadable=false;
    if(s)for(size_t i=0;i<s->database_count;i++)switch(s->databases[i].status){case OC_DB_OK:return "ok";case OC_DB_UNSUPPORTED:unsupported=true;break;case OC_DB_UNREADABLE:unreadable=true;break;default:break;}
    return unsupported?"unsupported":unreadable?"unreadable":"absent";
}
