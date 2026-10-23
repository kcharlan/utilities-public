#define _DARWIN_C_SOURCE
#include "scan.h"
#include "parse/record.h"
#include "util/fileio.h"
#include "util/sort.h"
#include <dirent.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#define TRY(x) do{Err e_=(x);if(e_.code)return e_;}while(0)
#define APPEND(a,d,n,c,v) record_append_aligned(a,(void **)&(d),&(n),&(c),sizeof(v),_Alignof(__typeof__(v)),&(v))
static Str text(const char *p){return (Str){p,(uint32_t)strlen(p)};}
bool antigravity_safe_path(Str root,const char *path){
    size_t n=strlen(path);if(n<root.n||memcmp(root.p,path,root.n)||(n>root.n&&path[root.n]!='/'))return false;
    char *copy=strdup(path);if(!copy)return false;bool safe=true;struct stat st;
    for(size_t i=root.n;i<=n;i++)if(i==n||copy[i]=='/'){
        char old=copy[i];copy[i]=0;
        if(lstat(copy,&st)){safe=errno==ENOENT;copy[i]=old;break;}
        if(S_ISLNK(st.st_mode)){safe=false;copy[i]=old;break;}
        copy[i]=old;
    }
    free(copy);return safe;
}
static bool uuid(const char *p,size_t n){
    if(n!=36)return false;
    for(size_t i=0;i<n;i++){if(i==8||i==13||i==18||i==23){if(p[i]!='-')return false;}else if(!((p[i]>='0'&&p[i]<='9')||(p[i]>='a'&&p[i]<='f')||(p[i]>='A'&&p[i]<='F')))return false;}
    return true;
}
static int order(const void *a,const void *b,void *ctx){(void)ctx;return str_compare(*(const Str *)a,*(const Str *)b);}
static Err add(AntigravityStore *s,Str path,Str surface,Str id,const char *reason){
    AntigravityDatabase d={.surface=surface,.status=reason?AG_DB_UNREADABLE:AG_DB_ABSENT};
    TRY(str_copy(&s->arena,path,&d.path));TRY(str_copy(&s->arena,id,&d.id));
    if(reason)TRY(str_copy(&s->arena,text(reason),&d.reason));
    TRY(APPEND(&s->arena,s->databases,s->database_count,s->database_capacity,d));s->present=true;return ERR_SUCCESS;
}
Err antigravity_discover(const Args *args,AntigravityStore *s){
    if(s->discovered)return err_make(ERR_INVALID,"Antigravity discovery already performed");
    s->discovered=true;s->disabled=args->no_antigravity;
    if(s->disabled){s->discovery_complete=true;return ERR_SUCCESS;}
    char *expanded=NULL,*full=NULL;Str normalized={0};Err e=file_expand_path(args->antigravity_home?args->antigravity_home:"~/.gemini",&expanded);
    if(e.code)return e;
    if(expanded[0]!='/'){
        char *cwd=getcwd(NULL,0);if(!cwd){free(expanded);return err_make(ERR_IO,"Antigravity working directory unavailable");}
        size_t n=strlen(cwd)+strlen(expanded)+2;full=malloc(n);if(full)snprintf(full,n,"%s/%s",cwd,expanded);free(cwd);
        if(!full){free(expanded);return err_make(ERR_NOMEM,"Antigravity path allocation failed");}
    }
    e=file_lexical_path(text(full?full:expanded),true,&normalized);free(full);free(expanded);if(e.code)return e;
    e=str_copy(&s->arena,normalized,&s->home);free((void *)normalized.p);if(e.code)return e;
    const char *env[]={"ANTIGRAVITY_GEMINI_DIR","ANTIGRAVITY_APP_DATA_DIR","JETSKI_APP_DATA_DIR"};
    for(size_t i=0;i<3;i++){const char *v=getenv(env[i]);if(v&&*v){Str name=text(env[i]);TRY(APPEND(&s->arena,s->ignored_environment,s->ignored_environment_count,s->ignored_environment_capacity,name));}}
    const char *dirs[]={"antigravity","antigravity-cli","antigravity-ide"},*surfaces[]={"app","cli","ide"};
    Omap legacy={0},db_ids={0};
    for(size_t k=0;!e.code&&k<3;k++){
        size_t n=s->home.n+strlen(dirs[k])+32;char *directory=malloc(n);if(!directory){e=err_make(ERR_NOMEM,"Antigravity path allocation failed");break;}
        snprintf(directory,n,"%s/%s/conversations",s->home.p,dirs[k]);Str surface=text(surfaces[k]);
        DIR *dir=NULL;
        if(!antigravity_safe_path(s->home,directory))e=add(s,text(directory),surface,(Str){0},"Antigravity source symlink excluded");
        else {dir=opendir(directory);if(!dir&&errno!=ENOENT)e=add(s,text(directory),surface,(Str){0},"Antigravity discovery directory unreadable");}
        Str *paths=NULL;size_t count=0,capacity=0;
        if(dir){struct dirent *ent;
            while(!e.code){errno=0;ent=readdir(dir);if(!ent){if(errno)e=add(s,text(directory),surface,(Str){0},"Antigravity directory enumeration failed");break;}
                size_t len=strlen(ent->d_name);if(len!=39||!uuid(ent->d_name,36)||(!strstr(ent->d_name+36,".db")&&!strstr(ent->d_name+36,".pb")))continue;
                Str id={0};e=str_copy(&s->arena,(Str){ent->d_name,36},&id);if(e.code)break;
                if(!strcmp(ent->d_name+36,".pb")){e=omap_put(&legacy,id,(void *)1);continue;}
                e=omap_put(&db_ids,id,(void *)1);if(e.code)break;
                size_t size=strlen(directory)+len+2;char *path=malloc(size);if(!path){e=err_make(ERR_NOMEM,"Antigravity path allocation failed");break;}
                snprintf(path,size,"%s/%s",directory,ent->d_name);Str owned={0};e=str_copy(&s->arena,text(path),&owned);free(path);
                if(!e.code)e=APPEND(&s->arena,paths,count,capacity,owned);
            }
            if(closedir(dir)&&!e.code)e=add(s,text(directory),surface,(Str){0},"Antigravity directory close failed");
        }
        if(!e.code)e=stable_sort(paths,count,sizeof *paths,order,NULL);
        for(size_t i=0;!e.code&&i<count;i++){
            const char *base=strrchr(paths[i].p,'/')+1;Str id={base,36};
            e=add(s,paths[i],surface,id,antigravity_safe_path(s->home,paths[i].p)?NULL:"Antigravity database symlink excluded");
        }
        free(directory);
    }
    for(OmapEntry *p=legacy.first;p;p=p->next)if(!omap_get(&db_ids,p->key))s->legacy_encrypted++;
    omap_destroy(&legacy);omap_destroy(&db_ids);s->discovery_complete=!e.code;return e;
}
const char *antigravity_database_status(AntigravityDatabaseStatus s){switch(s){case AG_DB_OK:return "ok";case AG_DB_ABSENT:return "absent";case AG_DB_UNREADABLE:return "unreadable";case AG_DB_UNSUPPORTED:return "unsupported";}return "unreadable";}
const char *antigravity_status(const AntigravityStore *s){
    if(s&&s->disabled)return "disabled";bool unsupported=false,unreadable=false;
    if(s)for(size_t i=0;i<s->database_count;i++){if(s->databases[i].status==AG_DB_OK)return "ok";unsupported|=s->databases[i].status==AG_DB_UNSUPPORTED;unreadable|=s->databases[i].status==AG_DB_UNREADABLE;}
    return unsupported?"unsupported":unreadable?"unreadable":"absent";
}
