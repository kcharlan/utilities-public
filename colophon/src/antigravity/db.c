#define _DARWIN_C_SOURCE
#include "db.h"
#include "meta/metadata.h"
#include "parse/record.h"
#include "testing/hooks.h"
#include "util/fileio.h"
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <sqlite3.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#define TRY(x) do{Err e_=(x);if(e_.code)return e_;}while(0)
#define APPEND(a,d,n,c,v) record_append_aligned(a,(void **)&(d),&(n),&(c),sizeof(v),_Alignof(__typeof__(v)),&(v))
static Str text(const char *p){return (Str){p,(uint32_t)strlen(p)};}
Err antigravity_diagnostic(AntigravityStore *s,const AntigravityDatabase *d,const char *context,int64_t idx,const char *reason){
    AntigravityDiagnostic v={.database=d->path,.session=d->id,.surface=d->surface,.idx=idx};
    TRY(str_copy(&s->arena,text(context),&v.context));TRY(str_copy(&s->arena,text(reason),&v.reason));
    return APPEND(&s->arena,s->diagnostics,s->diagnostic_count,s->diagnostic_capacity,v);
}
static Err sql_error(sqlite3 *db){int rc=sqlite3_errcode(db);return err_make(rc==SQLITE_NOMEM?ERR_NOMEM:ERR_IO,"Antigravity SQLite read failed (code %d)",rc);}
static Err prepare(sqlite3 *db,const char *sql,sqlite3_stmt **out){return sqlite3_prepare_v2(db,sql,-1,out,NULL)==SQLITE_OK?ERR_SUCCESS:sql_error(db);}
static Err execute(sqlite3 *db,const char *sql){return sqlite3_exec(db,sql,NULL,NULL,NULL)==SQLITE_OK?ERR_SUCCESS:sql_error(db);}
typedef struct { const char *name,*columns[7]; } Table;
static const Table tables[]={
    {"trajectory_meta",{"trajectory_id","cascade_id","trajectory_type","source",NULL}},
    {"trajectory_metadata_blob",{"id","data",NULL}},
    {"steps",{"idx","step_type","status","metadata","step_payload","step_format",NULL}},
    {"gen_metadata",{"idx","data",NULL}},
    {"conversation_summaries",{"conversation_id","title","raw_summary",NULL}}
};
typedef struct { bool summary; } Access;
static const Table *table(const char *name){for(size_t i=0;i<sizeof tables/sizeof *tables;i++)if(name&&!strcmp(name,tables[i].name))return &tables[i];return NULL;}
static int authorize(void *ctx,int action,const char *a,const char *b,const char *database,const char *trigger){
    (void)database;(void)trigger;Access *access=ctx;const Table *t=table(a);
    switch(action){
    case SQLITE_SELECT:case SQLITE_TRANSACTION:return SQLITE_OK;
    case SQLITE_READ:
        if(a&&(!strcmp(a,"sqlite_master")||!strcmp(a,"sqlite_schema")))return SQLITE_OK;
        if(!t||access->summary!=(t==&tables[4]))return SQLITE_DENY;
        for(size_t i=0;t->columns[i];i++)if(b&&!strcmp(b,t->columns[i]))return SQLITE_OK;
        return b&&!*b?SQLITE_OK:SQLITE_DENY;
    case SQLITE_PRAGMA:t=table(b);return a&&!strcmp(a,"table_info")&&t&&access->summary==(t==&tables[4])?SQLITE_OK:SQLITE_DENY;
    default:return SQLITE_DENY;
    }
}
static Err db_open(Str root,const char *path,Access *access,sqlite3 **out){
    *out=NULL;
    if(!antigravity_safe_path(root,path))return err_make(ERR_IO,"Antigravity source symlink excluded");
    const char *suffixes[]={"-wal","-shm","-journal"};
    for(size_t i=0;i<3;i++){
        size_t n=strlen(path)+strlen(suffixes[i])+1;char *p=malloc(n);if(!p)return err_make(ERR_NOMEM,"Antigravity sidecar path allocation failed");
        snprintf(p,n,"%s%s",path,suffixes[i]);bool safe=antigravity_safe_path(root,p);
        struct stat sidecar;int status=safe?lstat(p,&sidecar):-1,error=errno;free(p);
        if(!safe)return err_make(ERR_IO,"Antigravity SQLite sidecar symlink excluded");
        if(status&&error!=ENOENT)return err_make(ERR_IO,"Antigravity SQLite sidecar inaccessible");
        if(!status&&!S_ISREG(sidecar.st_mode))return err_make(ERR_IO,"Antigravity SQLite sidecar is not a regular file");
    }
    char *uri=NULL;sqlite3 *db=NULL;Err e=metadata_database_uri(path,&uri);
    if(!e.code&&sqlite3_open_v2(uri,&db,SQLITE_OPEN_READONLY|SQLITE_OPEN_URI,NULL)!=SQLITE_OK)e=sql_error(db);free(uri);
    if(!e.code&&sqlite3_busy_timeout(db,1000)!=SQLITE_OK)e=sql_error(db);
    if(!e.code&&sqlite3_set_authorizer(db,authorize,access)!=SQLITE_OK)e=sql_error(db);
    if(e.code){if(db)sqlite3_close(db);}else *out=db;return e;
}
static Err cell(Arena *a,sqlite3_stmt *st,int col,bool binary,Str *out){
    *out=(Str){0};int kind=sqlite3_column_type(st,col);
    if(kind==SQLITE_NULL)return ERR_SUCCESS;
    if(kind!=(binary?SQLITE_BLOB:SQLITE_TEXT))return err_make(ERR_INVALID,"Antigravity invalid SQLite cell type");
    const char *p=binary?sqlite3_column_blob(st,col):(const void *)sqlite3_column_text(st,col);
    if(sqlite3_errcode(sqlite3_db_handle(st))==SQLITE_NOMEM)return sql_error(sqlite3_db_handle(st));
    int n=sqlite3_column_bytes(st,col);if(sqlite3_errcode(sqlite3_db_handle(st))==SQLITE_NOMEM)return sql_error(sqlite3_db_handle(st));
    Str value={p?p:"",(uint32_t)n};
    if(binary&&value.n>AG_WIRE_MAX_BYTES)return err_make(ERR_INVALID,"Antigravity blob exceeds decoder allocation limit");
    if(!binary&&(!str_utf8_scalar_valid(value)||memchr(value.p,0,value.n)))return err_make(ERR_INVALID,"Antigravity invalid source text");
    return str_copy(a,value,out);
}
static Err guard(sqlite3 *db,bool summary,bool *raw){
    *raw=false;
    for(size_t i=summary?4:0;i<(summary?5:4);i++){
        const Table *t=&tables[i];sqlite3_stmt *st=NULL;
        TRY(prepare(db,"SELECT type FROM sqlite_master WHERE name=?",&st));sqlite3_bind_text(st,1,t->name,-1,SQLITE_STATIC);
        int rc=sqlite3_step(st);bool valid=rc==SQLITE_ROW&&sqlite3_column_type(st,0)==SQLITE_TEXT&&!strcmp((const char *)sqlite3_column_text(st,0),"table");
        Err e=rc!=SQLITE_ROW&&rc!=SQLITE_DONE?sql_error(db):ERR_SUCCESS;sqlite3_finalize(st);if(e.code)return e;
        if(!valid)return err_make(ERR_INVALID,"Antigravity missing required table %s",t->name);
        char sql[96];snprintf(sql,sizeof sql,"PRAGMA table_info(\"%s\")",t->name);TRY(prepare(db,sql,&st));bool found[7]={0};
        while((rc=sqlite3_step(st))==SQLITE_ROW){const char *name=(const char *)sqlite3_column_text(st,1);if(sqlite3_errcode(db)==SQLITE_NOMEM){e=sql_error(db);break;}for(size_t j=0;t->columns[j];j++)if(name&&!strcmp(name,t->columns[j]))found[j]=true;}
        if(!e.code&&rc!=SQLITE_DONE)e=sql_error(db);sqlite3_finalize(st);if(e.code)return e;
        for(size_t j=0;t->columns[j];j++)if(!found[j]&&!(summary&&j==2))return err_make(ERR_INVALID,"Antigravity %s missing required column %s",t->name,t->columns[j]);
        if(summary)*raw=found[2];
    }
    return ERR_SUCCESS;
}
static Err blob(AntigravityStore *s,AntigravityDatabase *d,sqlite3_stmt *st,int col,AgMessageType type,int64_t idx,Str *out,bool *valid){
    Err e=cell(&d->arena,st,col,true,out);*valid=false;
    if(e.code==ERR_NOMEM)return e;
    if(!e.code&&ag_wire_validate(*out,type)!=AG_MALFORMED){*valid=true;return ERR_SUCCESS;}
    s->malformed_blobs++;return antigravity_diagnostic(s,d,ag_wire_type_name(type),idx,e.code?e.message:"malformed protobuf blob");
}
static bool integer(sqlite3_stmt *st,int col,int64_t *value,bool *present){
    *present=sqlite3_column_type(st,col)!=SQLITE_NULL;*value=0;
    if(!*present)return true;
    if(sqlite3_column_type(st,col)!=SQLITE_INTEGER)return false;
    *value=sqlite3_column_int64(st,col);return true;
}
static AntigravityIntegerState enum_integer(sqlite3_stmt *st,int col,int64_t *value){
    bool present=false;
    if(!integer(st,col,value,&present))return AG_SQL_INVALID;
    return present?AG_SQL_INTEGER:AG_SQL_ABSENT;
}
static Err malformed_row(AntigravityStore *s,AntigravityDatabase *d,const char *context,int64_t idx,const char *reason){
    s->malformed_rows++;return antigravity_diagnostic(s,d,context,idx,reason);
}
static Err read_rows(AntigravityStore *s,AntigravityDatabase *d,sqlite3 *db,AntigravitySession *r,volatile sig_atomic_t *interrupted){
    sqlite3_stmt *st=NULL;Err e=prepare(db,"SELECT trajectory_id,cascade_id,trajectory_type,source FROM trajectory_meta",&st);int rc=SQLITE_DONE;
    while(!e.code&&(rc=sqlite3_step(st))==SQLITE_ROW){
        if(interrupted&&*interrupted){e=err_make(ERR_IO,"Antigravity read interrupted");break;}
        AntigravityMeta m={0};
        m.trajectory_type_state=enum_integer(st,2,&m.trajectory_type);m.source_state=enum_integer(st,3,&m.source);
        if(m.trajectory_type_state==AG_SQL_INVALID||m.source_state==AG_SQL_INVALID)e=malformed_row(s,d,"trajectory_meta",0,"noninteger optional enum; independent source facts retained");
        if(e.code)break;
        e=cell(&d->arena,st,0,false,&m.trajectory_id);if(!e.code)e=cell(&d->arena,st,1,false,&m.cascade_id);
        if(!e.code)e=APPEND(&d->arena,r->meta,r->meta_count,r->meta_capacity,m);
        if(!e.code&&((m.trajectory_id.n&&!str_equal(m.trajectory_id,r->id))||(m.cascade_id.n&&!str_equal(m.cascade_id,r->id))))e=antigravity_diagnostic(s,d,"trajectory_meta",0,"metadata identity differs from filename conversation id");
    }
    if(!e.code&&rc!=SQLITE_DONE)e=sql_error(db);sqlite3_finalize(st);st=NULL;
    const char *queries[]={"SELECT id,data FROM trajectory_metadata_blob ORDER BY id","SELECT idx,data FROM gen_metadata ORDER BY idx","SELECT idx,step_type,status,metadata,step_payload,step_format FROM steps ORDER BY idx"};
    for(size_t k=0;!e.code&&k<3;k++){
        e=prepare(db,queries[k],&st);
        while(!e.code&&(rc=sqlite3_step(st))==SQLITE_ROW){
            if(interrupted&&*interrupted){e=err_make(ERR_IO,"Antigravity read interrupted");break;}
            int64_t idx=0;bool has_idx=false,valid=false;
            if(!integer(st,0,&idx,&has_idx)||(!has_idx&&k)){e=malformed_row(s,d,k==0?"trajectory_metadata_blob":k==1?"gen_metadata":"steps",0,"noninteger index or absent required row index");continue;}
            if(k<2){AntigravityBlob b={.idx=idx,.has_idx=has_idx};e=blob(s,d,st,1,k?AG_GENERATOR:AG_TRAJECTORY,idx,&b.data,&valid);
                if(!e.code&&valid){if(k)e=APPEND(&d->arena,r->generators,r->generator_count,r->generator_capacity,b);else e=APPEND(&d->arena,r->metadata,r->metadata_count,r->metadata_capacity,b);}
            }else{
                AntigravityStep step={.idx=idx};bool payload_valid=false;
                step.step_type_state=enum_integer(st,1,&step.step_type);step.status_state=enum_integer(st,2,&step.status);step.step_format_state=enum_integer(st,5,&step.step_format);
                if(step.step_type_state==AG_SQL_INVALID||step.status_state==AG_SQL_INVALID||step.step_format_state==AG_SQL_INVALID)e=malformed_row(s,d,"steps",idx,"noninteger optional enum; independent source facts retained");
                if(e.code)break;
                e=blob(s,d,st,3,AG_STEP_METADATA,idx,&step.metadata,&valid);if(!e.code)e=blob(s,d,st,4,AG_STEP,idx,&step.payload,&payload_valid);
                if(!e.code&&valid&&payload_valid)e=APPEND(&d->arena,r->steps,r->step_count,r->step_capacity,step);
            }
        }
        if(!e.code&&rc!=SQLITE_DONE)e=sql_error(db);sqlite3_finalize(st);st=NULL;
    }
    return e;
}
/* Text protobuf annotations: lexical tokens keep quoted braces separate from
 * nested messages. Unknown fields are consumed, never interpreted as archive. */
typedef struct { Str input;size_t at,tokens;Arena *arena;Err error; } TextReader;
static void space(TextReader *r){while(r->at<r->input.n){unsigned char c=r->input.p[r->at];if(isspace(c)||c==','||c==';')r->at++;else if(c=='#'){while(r->at<r->input.n&&r->input.p[r->at]!='\n')r->at++;}else break;}}
static int hex(unsigned char c){return c>='0'&&c<='9'?c-'0':c>='a'&&c<='f'?c-'a'+10:c>='A'&&c<='F'?c-'A'+10:-1;}
static bool quoted(TextReader *r,Str *out){
    char quote=r->input.p[r->at++];size_t cap=r->input.n-r->at+1,n=0;char *p=malloc(cap);if(!p){r->error=err_make(ERR_NOMEM,"Antigravity annotation string allocation failed");return false;}bool ok=false;
    while(r->at<r->input.n){unsigned char c=r->input.p[r->at++];if(c==quote){ok=true;break;}if(c=='\n'||c=='\r')break;
        if(c=='\\'){
            if(r->at==r->input.n)break;c=r->input.p[r->at++];
            const char *esc="abfnrtv",*pos=c?strchr(esc,c):NULL;const char mapped[]={7,8,12,10,13,9,11};
            if(pos)c=mapped[pos-esc];
            else if(c=='x'||c=='u'||c=='U'){
                unsigned digits=c=='x'?2:c=='u'?4:8;uint32_t cp=0;unsigned count=0;
                while(count<digits&&r->at<r->input.n&&hex(r->input.p[r->at])>=0){cp=cp*16+(unsigned)hex(r->input.p[r->at++]);count++;}
                if(!count||(c!='x'&&count!=digits)||cp>0x10ffff||(cp>=0xd800&&cp<=0xdfff))break;
                if(c=='x')c=(unsigned char)cp;else{char encoded[4];size_t z=str_encode_codepoint(cp,encoded);memcpy(p+n,encoded,z);n+=z;continue;}
            }else if(c>='0'&&c<='7'){
                unsigned cp=c-'0';for(unsigned j=1;j<3&&r->at<r->input.n&&r->input.p[r->at]>='0'&&r->input.p[r->at]<='7';j++)cp=cp*8+(unsigned)(r->input.p[r->at++]-'0');if(cp>255)break;c=(unsigned char)cp;
            }else if(c!='\\'&&c!='\''&&c!='"'&&c!='?')break;
        }
        p[n++]=(char)c;
    }
    Str value={p,(uint32_t)n};if(ok&&(!str_utf8_scalar_valid(value)||memchr(p,0,n)))ok=false;
    if(ok&&out){r->error=str_copy(r->arena,value,out);if(r->error.code)ok=false;}free(p);return ok;
}
static bool text_message(TextReader *r,unsigned depth,char close,Str *title,bool *archived){
    if(depth>AG_WIRE_MAX_DEPTH)return false;
    for(;;){space(r);if(r->at==r->input.n)return !close;if(++r->tokens>AG_WIRE_MAX_FIELDS)return false;
        char c=r->input.p[r->at];if(c=='}'||c=='>'){r->at++;return close==c;}
        size_t begin=r->at;while(r->at<r->input.n&&(isalnum((unsigned char)r->input.p[r->at])||r->input.p[r->at]=='_'))r->at++;
        if(begin==r->at)return false;Str name={r->input.p+begin,(uint32_t)(r->at-begin)};space(r);
        bool colon=r->at<r->input.n&&r->input.p[r->at]==':';
        if(colon){r->at++;space(r);}if(r->at==r->input.n)return false;c=r->input.p[r->at];
        if(!colon&&c!='{'&&c!='<')return false;
        bool known_title=!depth&&str_equal(name,STR_LIT("title")),known_archive=!depth&&str_equal(name,STR_LIT("archived"));
        if(c=='{'||c=='<'){if(known_title||known_archive)return false;r->at++;if(!text_message(r,depth+1,c=='{'?'}':'>',NULL,NULL))return false;}
        else if(c=='\''||c=='"'){if(known_archive)return false;Str value={0};if(!quoted(r,known_title?&value:NULL))return false;if(known_title)*title=value;}
        else{
            if(known_title)return false;begin=r->at;while(r->at<r->input.n&&!isspace((unsigned char)r->input.p[r->at])&&!strchr("{}<>:;,",r->input.p[r->at]))r->at++;
            if(begin==r->at)return false;Str value={r->input.p+begin,(uint32_t)(r->at-begin)};
            if(known_archive){if(str_equal(value,STR_LIT("true"))||str_equal(value,STR_LIT("1")))*archived=true;else if(str_equal(value,STR_LIT("false"))||str_equal(value,STR_LIT("0")))*archived=false;else return false;}
        }
    }
}
static Err annotation(AntigravityStore *s,AntigravityDatabase *d,AntigravitySession *r){
    const char *surface=str_equal(d->surface,STR_LIT("app"))?"antigravity":str_equal(d->surface,STR_LIT("cli"))?"antigravity-cli":"antigravity-ide";
    size_t size=s->home.n+strlen(surface)+r->id.n+32;char *path=malloc(size);if(!path)return err_make(ERR_NOMEM,"Antigravity annotation path allocation failed");
    snprintf(path,size,"%s/%s/annotations/%s.pbtxt",s->home.p,surface,r->id.p);
    int fd=-1;bool safe=antigravity_safe_path(s->home,path);if(safe)fd=open(path,O_RDONLY|O_NOFOLLOW|O_NONBLOCK);int error=errno;free(path);
    if(fd<0&&safe&&error==ENOENT)return ERR_SUCCESS;
    Err e=ERR_SUCCESS;bool valid=false;char *bytes=NULL;struct stat st;
    if(fd>=0&&!fstat(fd,&st)&&S_ISREG(st.st_mode)&&st.st_size>=0&&st.st_size<=4*1024*1024){
        size_t n=(size_t)st.st_size;bytes=malloc(n+1);if(!bytes)e=err_make(ERR_NOMEM,"Antigravity annotation allocation failed");
        size_t used=0;while(!e.code&&bytes&&used<n){ssize_t got=read(fd,bytes+used,n-used);if(got<0&&errno==EINTR)continue;if(got<=0)break;used+=(size_t)got;}
        if(!e.code&&used==n){TextReader reader={.input={bytes,(uint32_t)n},.arena=&d->arena};valid=text_message(&reader,0,0,&r->annotation_title,&r->annotation_archived);e=reader.error;}
    }
    free(bytes);if(fd>=0)close(fd);if(e.code)return e;
    r->annotation_valid=valid;
    if(!valid){s->annotation_errors++;TRY(antigravity_diagnostic(s,d,"annotations",0,"annotation unreadable or malformed; using same-surface summary fallback"));}
    return ERR_SUCCESS;
}
static Err summary(AntigravityStore *s,AntigravityDatabase *d,AntigravitySession *r){
    const char *surface=str_equal(d->surface,STR_LIT("app"))?"antigravity":str_equal(d->surface,STR_LIT("cli"))?"antigravity-cli":"antigravity-ide";
    size_t n=s->home.n+strlen(surface)+40;char *path=malloc(n);if(!path)return err_make(ERR_NOMEM,"Antigravity summary path allocation failed");
    snprintf(path,n,"%s/%s/conversation_summaries.db",s->home.p,surface);struct stat st;
    int status=lstat(path,&st);
    if(status&&errno==ENOENT){free(path);return ERR_SUCCESS;}
    Access access={.summary=true};sqlite3 *db=NULL;sqlite3_stmt *q=NULL;bool raw=false;
    Err e=status?err_make(ERR_IO,"Antigravity summary database inaccessible"):
        !S_ISREG(st.st_mode)?err_make(ERR_IO,"Antigravity summary database is not a regular file"):db_open(s->home,path,&access,&db);free(path);
    if(!e.code)e=execute(db,"BEGIN");if(!e.code)e=guard(db,true,&raw);
    if(!e.code)e=prepare(db,raw?"SELECT title,raw_summary FROM conversation_summaries WHERE conversation_id=? COLLATE BINARY":"SELECT title,NULL FROM conversation_summaries WHERE conversation_id=? COLLATE BINARY",&q);
    if(!e.code){sqlite3_bind_text(q,1,r->id.p,r->id.n,SQLITE_STATIC);int rc=sqlite3_step(q);
        if(rc==SQLITE_ROW){
            e=cell(&d->arena,q,0,false,&r->summary_title);
            if(!e.code&&!raw)r->summary_valid=true;
            else if(!e.code){Str bytes={0};e=cell(&d->arena,q,1,true,&bytes);
                if(!e.code&&ag_wire_validate(bytes,AG_SUMMARY)!=AG_MALFORMED){
                    r->summary_blob=bytes;
                    /* Singular embedded messages merge. Only a found archived
                     * scalar overwrites prior state; empty/title-only instances
                     * cannot erase a scalar from an earlier occurrence. */
                    AgCursor cursor={.input=bytes};AgField annotations={0};AgResult result;
                    r->summary_valid=true;
                    while((result=ag_wire_next(&cursor,&annotations))==AG_FOUND){
                        if(annotations.number!=15)continue;
                        AgField archived={0};AgResult scalar=ag_wire_last(annotations.bytes,4,&archived);
                        if(annotations.wire!=2||scalar==AG_MALFORMED||(scalar==AG_FOUND&&archived.wire!=0)){r->summary_valid=false;break;}
                        if(scalar==AG_FOUND)r->summary_archived=archived.integer!=0;
                    }
                    if(result==AG_MALFORMED)r->summary_valid=false;
                }
                if(!e.code&&!r->summary_valid)e=err_make(ERR_INVALID,"malformed summary protobuf blob");
            }
        }else if(rc!=SQLITE_DONE)e=sql_error(db);
    }
    sqlite3_finalize(q);if(!e.code&&db)e=execute(db,"COMMIT");if(db)sqlite3_close(db);
    if(e.code==ERR_NOMEM)return e;
    if(e.code){r->summary_valid=false;r->summary_title=(Str){0};r->summary_blob=(Str){0};TRY(antigravity_diagnostic(s,d,"conversation_summaries",0,e.message));}
    return ERR_SUCCESS;
}
static Err read_database(AntigravityStore *s,AntigravityDatabase *d,volatile sig_atomic_t *interrupted){
    if(d->reason.n)return ERR_SUCCESS;struct stat st;
    if(lstat(d->path.p,&st)){if(errno==ENOENT){d->status=AG_DB_ABSENT;return ERR_SUCCESS;}d->status=AG_DB_UNREADABLE;return str_copy(&s->arena,STR_LIT("Antigravity database inaccessible"),&d->reason);}
    Access access={0};sqlite3 *db=NULL;Err e=S_ISREG(st.st_mode)?db_open(s->home,d->path.p,&access,&db):err_make(ERR_IO,"Antigravity database is not a regular file");
    bool raw=false;if(!e.code)e=execute(db,"BEGIN");if(!e.code)e=guard(db,false,&raw);
    AntigravitySession *r=NULL;
    if(!e.code){e=arena_alloc(&d->arena,sizeof *r,_Alignof(AntigravitySession),(void **)&r);if(!e.code){*r=(AntigravitySession){.id=d->id,.database=d->path,.surface=d->surface};e=read_rows(s,d,db,r,interrupted);}}
    if(!e.code&&cp_fault("antigravity.commit"))e=err_make(ERR_IO,"Antigravity snapshot commit failed");
    if(!e.code)e=execute(db,"COMMIT");if(db)sqlite3_close(db);
    if(e.code){arena_destroy(&d->arena);if(e.code==ERR_NOMEM||(interrupted&&*interrupted))return e;d->status=e.code==ERR_INVALID?AG_DB_UNSUPPORTED:AG_DB_UNREADABLE;return str_copy(&s->arena,text(e.message),&d->reason);}
    d->status=AG_DB_OK;
    if(omap_get(&s->session_ids,r->id)){s->duplicate_sessions++;TRY(antigravity_diagnostic(s,d,"duplicate_sessions",0,"conversation id already accepted from an earlier database"));arena_destroy(&d->arena);return ERR_SUCCESS;}
    TRY(summary(s,d,r));TRY(annotation(s,d,r));
    if(r->annotation_valid&&r->summary_valid&&r->annotation_archived!=r->summary_archived){s->archive_disagreements++;TRY(antigravity_diagnostic(s,d,"archive_disagreements",0,"annotation and same-surface summary disagree"));}
    r->archived=r->annotation_valid?r->annotation_archived:r->summary_valid?r->summary_archived:false;
    r->archive_reason=r->archived?STR_LIT("session"):(Str){0};
    r->title=r->annotation_valid&&r->annotation_title.n?r->annotation_title:r->summary_title;
    TRY(omap_put(&s->session_ids,r->id,r));TRY(APPEND(&s->arena,s->sessions,s->session_count,s->session_capacity,r));
    d->accepted_sessions=1;d->accepted_steps=r->step_count;return ERR_SUCCESS;
}
Err antigravity_store_read(AntigravityStore *s,volatile sig_atomic_t *interrupted){
    if(s->disabled)return ERR_SUCCESS;
    for(size_t i=0;i<s->database_count;i++)TRY(read_database(s,&s->databases[i],interrupted));return ERR_SUCCESS;
}
void antigravity_store_destroy(AntigravityStore *s){
    for(size_t i=0;i<s->database_count;i++)arena_destroy(&s->databases[i].arena);omap_destroy(&s->session_ids);arena_destroy(&s->arena);memset(s,0,sizeof *s);
}
