#include "corpus.h"
#include "corpus/titles.h"
#include "corpus/provider.h"
#include "corpus/turnstatus.h"
#include "corpus/subagents.h"
#include "claude/parse.h"
#include "out/jsonw.h"
#include <stdalign.h>
#include <stdio.h>
#include <string.h>

#define TRY(x) do {Err e_=(x);if(e_.code)return e_;}while(0)
static Err alloc(Arena *a,size_t n,size_t size,size_t alignment,void **out) {
    if(size&&n>SIZE_MAX/size)return err_make(ERR_NOMEM,"Antigravity corpus allocation overflow");
    TRY(arena_alloc(a,n*size,alignment,out));if(n)memset(*out,0,n*size);return ERR_SUCCESS;
}
static void latest(MaybeMs *out,MaybeMs v) {if(v.present&&(!out->present||v.value>out->value))*out=v;}
static Str scalar(Str input,uint32_t n) {AgField f={0};return ag_wire_last(input,n,&f)==AG_FOUND?f.bytes:(Str){0};}
/* Concatenation is protobuf singular-message merge: later scalars win while
 * repeated children concatenate. Retain one bounded allocation per message. */
Err antigravity_message_merge(Arena *a,Str input,uint32_t n,Str *out) {
    AgCursor cur={.input=input};AgField f;size_t bytes=0,count=0;Str only={0};
    while(ag_wire_next(&cur,&f)==AG_FOUND)if(f.number==n){
        if(bytes>AG_WIRE_MAX_BYTES-f.bytes.n)return err_make(ERR_INVALID,"Antigravity merged message too large");
        bytes+=f.bytes.n;count++;only=f.bytes;
    }
    *out=only;if(count<2)return ERR_SUCCESS;
    char *p;TRY(arena_alloc(a,bytes,1,(void**)&p));size_t at=0;cur=(AgCursor){.input=input};
    while(ag_wire_next(&cur,&f)==AG_FOUND)if(f.number==n){memcpy(p+at,f.bytes.p,f.bytes.n);at+=f.bytes.n;}
    *out=(Str){p,(uint32_t)bytes};return ERR_SUCCESS;
}
Err antigravity_clock(Arena *a,Str input,uint32_t n,MaybeMs *out) {
    Str nested={0};TRY(antigravity_message_merge(a,input,n,&nested));if(!nested.p)return ERR_SUCCESS;
    AgField seconds={0},nanos={0};ag_wire_last(nested,1,&seconds);ag_wire_last(nested,2,&nanos);
    int64_t sec=(int64_t)seconds.integer;uint64_t ns=nanos.integer;
    __int128 ms=(__int128)sec*1000+ns/1000000;
    if(sec>=-62135596800LL&&sec<=253402300799LL&&ns<1000000000&&ms>=INT64_MIN&&ms<=INT64_MAX)
        *out=(MaybeMs){true,(int64_t)ms};
    return ERR_SUCCESS;
}
static Err prompt(Arena *a,Str payload,Request *request) {
    Str user={0};TRY(antigravity_message_merge(a,payload,19,&user));request->text=scalar(user,2);request->kind=STR_LIT("text");
    AgCursor cur={.input=user};AgField f;JsonWriter text={0};
    while(ag_wire_next(&cur,&f)==AG_FOUND) {
        if(f.number==3&&!request->text.n){Str s=scalar(f.bytes,1);if(s.n){if(text.length)jsonw_raw(&text,"\n");jsonw_bytes(&text,s.p,s.n);}}
        if(f.number==5)request->images++;
        if(f.number==9){Str mime=scalar(f.bytes,1);if(mime.n>=6&&!memcmp(mime.p,"image/",6))request->images++;}
    }
    Err e=text.error;if(!e.code&&!request->text.n&&text.length)e=str_copy(a,(Str){text.data,(uint32_t)text.length},&request->text);
    jsonw_free(&text);return e;
}
static bool active(int64_t n) {return n==1||n==2||n==8||n==9||n==11;}
bool antigravity_step_enum(const AntigravityStep *step,bool status,int64_t *out) {
    AntigravityIntegerState state=status?step->status_state:step->step_type_state;
    if(state==AG_SQL_INTEGER){*out=status?step->status:step->step_type;return true;}
    AgField f={0};if(ag_wire_last(step->payload,status?4:1,&f)!=AG_FOUND)return false;
    *out=(int64_t)f.integer;return true;
}
static Err diagnose(AntigravityStore *store,const AntigravitySession *r,const char *context,int64_t idx,const char *reason) {
    AntigravityDatabase db={.id=r->id,.path=r->database,.surface=r->surface};
    return antigravity_diagnostic(store,&db,context,idx,reason);
}
static int hex(unsigned char c) {return c>='0'&&c<='9'?c-'0':c>='a'&&c<='f'?c-'a'+10:c>='A'&&c<='F'?c-'A'+10:-1;}
static Err uri(AntigravityStore *store,const AntigravitySession *r,Arena *a,Str input,Str *out) {
    if(!input.n)return ERR_SUCCESS;
    if(input.n<8||memcmp(input.p,"file:///",8))return diagnose(store,r,"workspace",0,"workspace URI must use an absolute file:// path");
    char *p;TRY(arena_alloc(a,input.n,1,(void**)&p));size_t n=0;
    for(size_t i=7;i<input.n;i++) {
        unsigned char value=(unsigned char)input.p[i];
        if(value=='%') {
            if(i+2>=input.n||hex(input.p[i+1])<0||hex(input.p[i+2])<0)return diagnose(store,r,"workspace",0,"invalid percent escape in workspace URI");
            value=(unsigned char)(hex(input.p[i+1])*16+hex(input.p[i+2]));i+=2;
        }else if(value=='?'||value=='#')return diagnose(store,r,"workspace",0,"workspace URI query or fragment is unsupported");
        if(!value)return diagnose(store,r,"workspace",0,"workspace URI contains a null byte");
        p[n++]=(char)value;
    }
    p[n]=0;*out=(Str){p,(uint32_t)n};return ERR_SUCCESS;
}
static Err workspace(AntigravityStore *store,const AntigravitySession *r,Corpus *c,SessionModel *s,Str input) {
    AgCursor cur={.input=input};AgField f;
    while(ag_wire_next(&cur,&f)==AG_FOUND)if(f.number==1) {
        Str cwd={0},root={0};TRY(uri(store,r,&c->arena,scalar(f.bytes,1),&cwd));TRY(uri(store,r,&c->arena,scalar(f.bytes,2),&root));
        if(cwd.n)s->meta.cwd=(JScalar){.kind=JS_STRING,.value.s=cwd};
        if(root.n)s->antigravity_git_root=root;
        Str branch=scalar(f.bytes,4);if(branch.n)s->meta.branch=(JScalar){.kind=JS_STRING,.value.s=branch};
    }
    Str parent=scalar(input,5);if(parent.n)s->parent_id=parent;
    return ERR_SUCCESS;
}
static Err tool_calls(AntigravityStore *store,const AntigravitySession *r,Corpus *c,
                      const AntigravityStep *step,Str planner,const Omap *failed_ids,CorpusTools *counted) {
    Err e=ERR_SUCCESS;
    AgCursor cur={.input=planner};AgField f;
    while(!e.code&&ag_wire_next(&cur,&f)==AG_FOUND)if(f.number==7) {
        Str name=scalar(f.bytes,2),id=scalar(f.bytes,1);bool failed=id.n&&omap_get(failed_ids,id);
        Str arguments=scalar(f.bytes,3);
        if(arguments.n&&!str_equal(name,STR_LIT("call_mcp_tool"))) {
            JsonRead read=json_read(arguments,STRICT,JSON_CONSTANTS_REJECT,"antigravity.tool_arguments");
            if(read.status==JSON_NOMEM)e=err_make(ERR_NOMEM,"Antigravity tool argument allocation failed");
            else if(read.status!=JSON_OK)e=diagnose(store,r,"tool_arguments",step->idx,"malformed tool arguments JSON");
            json_read_free(&read);
        }
        if(str_equal(name,STR_LIT("run_command")))name=STR_LIT("Bash");
        else if(str_equal(name,STR_LIT("write_to_file"))||str_equal(name,STR_LIT("write_file"))||str_equal(name,STR_LIT("replace_file_content"))||str_equal(name,STR_LIT("multi_replace_file_content")))name=STR_LIT("Edit");
        else if(str_equal(name,STR_LIT("call_mcp_tool"))) {
            Str args=scalar(f.bytes,3);JsonRead read=json_read(args,STRICT,JSON_CONSTANTS_REJECT,"antigravity.tool_arguments");
            yyjson_val *root=read.doc?yyjson_doc_get_root(read.doc):NULL;
            yyjson_val *server=root?yyjson_obj_get(root,"ServerName"):NULL,*tool=root?yyjson_obj_get(root,"ToolName"):NULL;
            if(read.status==JSON_OK&&yyjson_is_str(server)&&yyjson_is_str(tool)&&yyjson_get_len(server)&&yyjson_get_len(tool)) {
                JsonWriter w={0};jsonw_raw(&w,"mcp__");jsonw_bytes(&w,yyjson_get_str(server),yyjson_get_len(server));jsonw_raw(&w,"__");jsonw_bytes(&w,yyjson_get_str(tool),yyjson_get_len(tool));
                e=w.error;if(!e.code)e=str_copy(&c->arena,(Str){w.data,(uint32_t)w.length},&name);jsonw_free(&w);
            }else if(read.status==JSON_NOMEM)e=err_make(ERR_NOMEM,"Antigravity tool argument allocation failed");
            else e=diagnose(store,r,"tool_arguments",step->idx,"call_mcp_tool arguments require ServerName and ToolName strings");
            json_read_free(&read);
        }
        if(!e.code)e=claude_tool_count(&c->arena,counted,name,failed);
    }
    return e;
}
static Err session_tools(AntigravityStore *store,const AntigravitySession *r,Corpus *c,SessionModel *s) {
    if(!s->turn_count)return ERR_SUCCESS;
    Arena scratch={0};Omap failed_ids={0},turns={0};CorpusTools *counted=NULL;
    Err e=alloc(&scratch,s->turn_count,sizeof *counted,alignof(CorpusTools),(void**)&counted);
    /* Error execution IDs are session-local. Merge each execution once; the
     * map copies keys before temporary merged bytes are destroyed. */
    for(size_t i=0;!e.code&&i<r->step_count;i++) {
        const AntigravityStep *step=&r->steps[i];int64_t status=0;
        if(!antigravity_step_enum(step,true,&status)||status!=7)continue;
        Str call={0};e=antigravity_message_merge(&scratch,step->metadata,4,&call);
        Str id=scalar(call,1);if(!e.code&&id.n)e=omap_put(&failed_ids,id,(void*)r);
    }
    for(size_t i=0;!e.code&&i<s->turn_count;i++)e=omap_put(&turns,s->turns[i].id,&counted[i]);
    /* One source pass routes planner calls to their already-constructed turn,
     * rather than visiting every session step again for every display turn. */
    for(size_t i=0;!e.code&&i<r->step_count;i++) {
        const AntigravityStep *step=&r->steps[i];if(!step->turn.n)continue;
        CorpusTools *target=omap_get(&turns,step->turn);
        if(!target){e=err_make(ERR_INVALID,"Antigravity tool turn identity missing");break;}
        Str planner={0};e=antigravity_message_merge(&scratch,step->payload,20,&planner);
        if(!e.code)e=tool_calls(store,r,c,step,planner,&failed_ids,target);
    }
    for(size_t i=0;!e.code&&i<s->turn_count;i++)e=corpus_turn_tools_adopt(&c->arena,s,&s->turns[i],&counted[i]);
    if(counted)for(size_t i=0;i<s->turn_count;i++){omap_destroy(&counted[i].mcp);omap_destroy(&counted[i].other);}
    omap_destroy(&failed_ids);omap_destroy(&turns);arena_destroy(&scratch);return e;
}
static Err project_session(AntigravityStore *store,AntigravitySession *r,int64_t snapshot,Corpus *c,SessionModel *s) {
    *s=(SessionModel){.id=r->id,.key=r->id,.identity=r->id,.provider=PROVIDER_ANTIGRAVITY,
        .antigravity_surface=r->surface,.kind=STR_LIT("session"),.archived=r->archived,
        .archive_reason=r->archive_reason,.title_full=r->title,
        .title_source=r->title.n?STR_LIT("antigravity_title"):STR_LIT("session_id")};
    s->meta.id=r->id;
    for(size_t i=0;i<r->metadata_count;i++){TRY(antigravity_clock(&c->arena,r->metadata[i].data,2,&s->start_ms));TRY(workspace(store,r,c,s,r->metadata[i].data));}
    bool subagent=false;for(size_t i=0;i<r->meta_count;i++)if(r->meta[i].source_state==AG_SQL_INTEGER&&r->meta[i].source==16)subagent=true;
    s->is_subagent=subagent||s->parent_id.n;s->has_link=s->parent_id.n;s->has_depth=!s->is_subagent;s->meta.is_subagent=s->is_subagent;
    s->meta.parent_thread_id=(JScalar){.kind=s->parent_id.n?JS_STRING:JS_ABSENT,.value.s=s->parent_id};
    size_t count=0;MaybeMs completion={0},creation={0};
    for(size_t i=0;i<r->step_count;i++) {
        AntigravityStep *step=&r->steps[i];step->turn=(Str){0};MaybeMs start={0},end={0};
        TRY(antigravity_clock(&c->arena,step->metadata,1,&start));TRY(antigravity_clock(&c->arena,step->metadata,8,&end));
        if(!s->start_ms.present)s->start_ms=start;latest(&creation,start);latest(&completion,end);
        int64_t type=0;if(antigravity_step_enum(step,false,&type)&&type==14)count++;
        for(size_t which=0;which<2;which++) {
            AntigravityIntegerState state=which?step->status_state:step->step_type_state;AgField f={0};
            if(state==AG_SQL_INTEGER&&ag_wire_last(step->payload,which?4:1,&f)==AG_FOUND&&(int64_t)f.integer!=(which?step->status:step->step_type))
                TRY(diagnose(store,r,"enum_conflict",step->idx,which?"SQL status overrides conflicting payload status":"SQL step_type overrides conflicting payload type"));
        }
    }
    s->end_ms=completion.present?completion:creation;
    s->created_at_ms=(MaybeNum){s->start_ms.present,{.i=s->start_ms.value}};s->meta.created_at_ms=s->start_ms;
    TurnFact *facts,**pointers;Str *answers;
    TRY(alloc(&c->arena,count,sizeof *facts,alignof(TurnFact),(void**)&facts));
    TRY(alloc(&c->arena,count,sizeof *pointers,alignof(TurnFact*),(void**)&pointers));
    TRY(alloc(&c->arena,count,sizeof *answers,alignof(Str),(void**)&answers));
    TRY(alloc(&c->arena,count,sizeof *s->requests,alignof(Request),(void**)&s->requests));
    TurnFact *current=NULL;size_t turn=0;bool error=false,canceled=false,running=false;
    for(size_t i=0;i<=r->step_count;i++) {
        AntigravityStep *step=i<r->step_count?&r->steps[i]:NULL;
        int64_t type=0;bool user=step&&antigravity_step_enum(step,false,&type)&&type==14;
        if((user||!step)&&current)current->end_kind=error?STR_LIT("aborted"):canceled?STR_LIT("interrupted"):!step&&running?STR_LIT("open"):STR_LIT("completed");
        if(!step)break;
        if(user) {
            current=&facts[turn];pointers[turn]=current;error=canceled=running=false;
            char key[64];int n=snprintf(key,sizeof key,"antigravity-turn-%lld",(long long)step->idx);
            TRY(str_copy(&c->arena,(Str){key,(uint32_t)n},&current->key));current->turn_id=current->key;
            TRY(antigravity_clock(&c->arena,step->metadata,1,&current->start_ms));current->has_start_rec=true;current->start_rec=i;
            s->requests[turn].at_ms=current->start_ms;TRY(prompt(&c->arena,step->payload,&s->requests[turn]));turn++;
        }
        if(!current)continue;
        step->turn=current->key;MaybeMs created={0},completed={0};
        TRY(antigravity_clock(&c->arena,step->metadata,1,&created));TRY(antigravity_clock(&c->arena,step->metadata,8,&completed));
        latest(&current->last_ms,created);latest(&current->last_ms,completed);latest(&current->end_ms,completed);
        int64_t status=0;if(antigravity_step_enum(step,true,&status)){error|=status==7;canceled|=status==6||status==12;running|=active(status);}
        Str planner={0};TRY(antigravity_message_merge(&c->arena,step->payload,20,&planner));Str answer=scalar(planner,1);if(!answer.n)answer=scalar(planner,8);
        if(answer.n)answers[turn-1]=answer;
    }
    MaybeMs activity=creation;latest(&activity,completion);
    int64_t mtime=activity.present?activity.value:s->end_ms.present?s->end_ms.value:snapshot;
    TRY(turn_models(&c->arena,pointers,count,false,mtime,snapshot,&s->turns));s->turn_count=s->request_count=count;
    TRY(alloc(&c->arena,count,sizeof *s->ordered_requests,alignof(Request*),(void**)&s->ordered_requests));
    for(size_t i=0;i<count;i++) {
        TurnModel *t=&s->turns[i];size_t source=0;while(source<count&&!str_equal(t->id,facts[source].key))source++;
        if(source==count)return err_make(ERR_INVALID,"Antigravity turn identity missing");
        TRY(alloc(&c->arena,1,sizeof *t->requests,alignof(Request*),(void**)&t->requests));
        t->requests[0]=&s->requests[source];t->request_count=1;t->final_answer=answers[source];s->ordered_requests[i]=t->requests[0];corpus_status_flags(s,t->status);
    }
    TRY(session_tools(store,r,c,s));
    if(!metadata_text(s->title_full))for(size_t i=0;i<count;i++)if(metadata_text(s->requests[i].text)){s->title_full=s->requests[i].text;s->title_source=STR_LIT("first_request");break;}
    if(!metadata_text(s->title_full)){s->title_full=r->id;s->title_source=STR_LIT("session_id");}
    TRY(title_display(&c->arena,s->title_full,&s->title));if(s->is_subagent){s->kind=STR_LIT("subagent");s->agent_label=s->title_full;}
    TRY(corpus_session_idle(&c->arena,s));return ERR_SUCCESS;
}

Err antigravity_corpus_add(AntigravityStore *store,int64_t snapshot,Corpus *c) {
    Omap identified={0},public_ids={0};Err e=ERR_SUCCESS;
    for(OmapEntry *q=c->sessions.first;!e.code&&q;q=q->next){SessionModel *s=q->value;e=omap_put(&public_ids,s->id,s);}
    for(size_t i=0;!e.code&&i<store->session_count;i++) {
        AntigravitySession *r=store->sessions[i];SessionModel *s;
        if(omap_get(&c->sessions,r->id)||omap_get(&public_ids,r->id)){e=corpus_strings_add(&store->arena,&store->corpus_collisions,r->id);continue;}
        e=arena_alloc(&c->arena,sizeof *s,alignof(SessionModel),(void**)&s);if(e.code)break;
        *s=(SessionModel){0};
        e=omap_put(&c->sessions,r->id,s);
        if(!e.code)e=project_session(store,r,snapshot,c,s);
        if(!e.code)e=omap_put(&identified,r->id,s);
        if(!e.code)r->corpus_accepted=true;
    }
    if(!e.code)e=corpus_graph_break_cycles(&c->arena,&identified);
    for(OmapEntry *q=identified.first;!e.code&&q;q=q->next){SessionModel *s=q->value;if(!s->is_subagent)continue;
        SessionModel *parent=omap_get(&identified,s->parent_id);
        if(!parent){s->kind=STR_LIT("orphan");s->flags|=F_ORPHAN;e=corpus_strings_add(&store->arena,&store->orphaned_subagents,s->id);}
        else e=corpus_strings_add(&c->arena,&parent->children,s->id);
    }
    for(OmapEntry *q=identified.first;!e.code&&q;q=q->next){SessionModel *s=q->value,*p=s;size_t depth=0;
        while(p&&!p->has_depth){depth++;p=omap_get(&identified,p->parent_id);}
        if(p){s->has_depth=true;s->depth=p->depth+depth;}e=corpus_children_order(s,&identified);
    }
    omap_destroy(&identified);omap_destroy(&public_ids);return e;
}
