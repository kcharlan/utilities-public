#include "corpus.h"
#include "claude/parse.h"
#include "corpus/provider.h"
#include "corpus/subagents.h"
#include "corpus/titles.h"
#include "corpus/turnstatus.h"
#include <stdalign.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>

#define TRY(x) do { Err e_=(x); if(e_.code) return e_; } while(0)

static Err alloc(Arena *a, size_t n, size_t size, size_t alignment, void **out) {
    if(size && n>SIZE_MAX/size) return err_make(ERR_NOMEM,"OpenCode corpus allocation overflow");
    TRY(arena_alloc(a,n*size,alignment,out));
    if(n) memset(*out,0,n*size);
    return ERR_SUCCESS;
}
static void latest(MaybeMs *out, MaybeMs value) {
    if(value.present && (!out->present || value.value>out->value)) *out=value;
}
static MaybeMs message_end(const OpencodeMessage *m) {
    MaybeMs end=m->created_ms;
    latest(&end,m->streamed_ms);latest(&end,m->completed_ms);
    return end;
}
static bool prefix(Str s, Str p) { return s.n>=p.n && !memcmp(s.p,p.p,p.n); }
static bool meaningful_title(Str s) {
    s=str_trim(s,true);
    return metadata_text(s) && !prefix(s,STR_LIT("New session - ")) &&
        !prefix(s,STR_LIT("Child session - "));
}
static Str tool_name(Str name) {
    if(str_equal(name,STR_LIT("shell"))||str_equal(name,STR_LIT("bash"))) return STR_LIT("Bash");
    if(str_equal(name,STR_LIT("edit"))||str_equal(name,STR_LIT("patch"))||str_equal(name,STR_LIT("apply_patch"))) return STR_LIT("Edit");
    if(str_equal(name,STR_LIT("write"))) return STR_LIT("Write");
    if(str_equal(name,STR_LIT("multiedit"))) return STR_LIT("MultiEdit");
    if(str_equal(name,STR_LIT("webfetch"))) return STR_LIT("WebFetch");
    if(str_equal(name,STR_LIT("websearch"))) return STR_LIT("WebSearch");
    return name;
}
static Str end_kind(const OpencodeMessage *m) {
    if(m->kind==OC_MSG_IDLE) {
        if(str_equal(m->outcome,STR_LIT("succeeded"))) return STR_LIT("completed");
        if(str_equal(m->outcome,STR_LIT("failed"))) return STR_LIT("aborted");
        if(str_equal(m->outcome,STR_LIT("interrupted"))) return STR_LIT("interrupted");
    } else if(m->kind==OC_MSG_ASSISTANT) {
        if(str_equal(m->error,STR_LIT("aborted"))) return STR_LIT("interrupted");
        if(metadata_text(m->error)) return STR_LIT("aborted");
        if(m->completed_ms.present && metadata_text(m->finish) &&
            !str_equal(m->finish,STR_LIT("tool-calls"))) return STR_LIT("completed");
    }
    return STR_LIT("open");
}
static void finish(TurnFact *t) {
    if(t && !str_equal(t->end_kind,STR_LIT("open"))) t->end_ms=t->last_ms;
}
static Err project_session(OpencodeStore *store, OpencodeSession *r,
                           int64_t snapshot, Corpus *c, SessionModel *s) {
    *s=(SessionModel){.id=r->id,.key=r->id,.identity=r->id,
        .provider=PROVIDER_OPENCODE,.opencode_database=r->database,
        .kind=STR_LIT("session"),.archived=r->archived||r->project_archived,
        .archive_reason=r->archived?STR_LIT("session"):r->project_archived?STR_LIT("project"):(Str){0},
        .start_ms=r->created_ms,.is_subagent=r->parent_id.n!=0,.has_link=r->parent_id.n!=0,
        .parent_id=r->parent_id,.forked_from=r->fork_session_id,
        .created_at_ms={r->created_ms.present,{.i=r->created_ms.value}},
        .has_depth=!r->parent_id.n};
    if(s->archive_reason.n)
        TRY(str_copy(&c->arena,s->archive_reason,&s->archive_reason));
    s->meta.id=r->id;s->meta.created_at_ms=r->created_ms;
    s->meta.is_subagent=s->is_subagent;
    s->meta.forked_from_id=r->fork_session_id;
    s->meta.parent_thread_id=(JScalar){.kind=r->parent_id.n?JS_STRING:JS_ABSENT,.value.s=r->parent_id};
    if(r->version.n) s->meta.cli_version=(JScalar){.kind=JS_STRING,.value.s=r->version};
    if(r->directory.n && r->directory.p[0]=='/' && !memchr(r->directory.p,0,r->directory.n)) {
        struct stat st;
        if(!stat(r->directory.p,&st) && S_ISDIR(st.st_mode))
            s->meta.cwd=(JScalar){.kind=JS_STRING,.value.s=r->directory};
    }
    if(r->fork_session_id.n) s->flags|=F_FORKED;
    size_t count=0;
    bool unknown=false;
    for(size_t i=0;i<r->message_count;i++) {
        OpencodeMessage *m=&r->messages[i];
        m->turn=(Str){0};
        m->inherited=r->fork_session_id.n && r->created_ms.present &&
            m->row_created_ms.present && m->row_created_ms.value<r->created_ms.value;
        if(r->fork_session_id.n && (!r->created_ms.present||!m->row_created_ms.present)) unknown=true;
        if(m->inherited) continue;
        if(m->kind==OC_MSG_USER) count++;
        MaybeMs end=message_end(m);
        latest(&s->end_ms,end);
        if(!m->created_ms.present) unknown=true;
    }
    if(!s->end_ms.present) s->end_ms=r->updated_ms;
    TRY(alloc(&store->arena,count,sizeof *r->turns,alignof(TurnFact *),(void**)&r->turns));
    TRY(alloc(&c->arena,count,sizeof *s->requests,alignof(Request),(void**)&s->requests));
    Str *answers;
    TRY(alloc(&c->arena,count,sizeof *answers,alignof(Str),(void**)&answers));
    TurnFact *current=NULL;
    for(size_t i=0;i<r->message_count;i++) {
        OpencodeMessage *m=&r->messages[i];
        if(m->inherited) continue;
        if(m->kind==OC_MSG_USER) {
            finish(current);
            TRY(alloc(&store->arena,1,sizeof *current,alignof(TurnFact),(void**)&current));
            char key[64];int n=snprintf(key,sizeof key,"opencode-turn-%zu",r->turn_count+1);
            TRY(str_copy(&store->arena,(Str){key,(uint32_t)n},&current->key));
            current->turn_id=m->id;current->start_ms=m->created_ms;
            current->has_start_rec=true;current->start_rec=i;
            current->end_kind=STR_LIT("open");
            s->requests[r->turn_count]=(Request){.at_ms=m->created_ms,.text=m->text,
                .kind=STR_LIT("text"),.images=m->images};
            r->turns[r->turn_count++]=current;
        }
        if(!current) continue;
        m->turn=current->key;
        latest(&current->last_ms,message_end(m));
        if(m->kind==OC_MSG_ASSISTANT||m->kind==OC_MSG_IDLE) current->end_kind=end_kind(m);
        if(m->kind==OC_MSG_ASSISTANT && m->text.n) answers[r->turn_count-1]=m->text;
    }
    finish(current);
    int64_t mtime=r->updated_ms.present?r->updated_ms.value:s->end_ms.present?s->end_ms.value:snapshot;
    if(!r->updated_ms.present && !s->end_ms.present) unknown=true;
    if(unknown) TRY(corpus_strings_add(&store->arena,&store->unknown_clocks,r->id));
    TRY(turn_models(&c->arena,r->turns,r->turn_count,false,mtime,snapshot,&s->turns));
    s->turn_count=s->request_count=r->turn_count;
    TRY(alloc(&c->arena,count,sizeof *s->ordered_requests,alignof(Request *),(void**)&s->ordered_requests));
    for(size_t i=0;i<s->turn_count;i++) {
        TurnModel *t=&s->turns[i];size_t source=0;
        while(source<r->turn_count && !str_equal(r->turns[source]->key,t->id)) source++;
        if(source==r->turn_count) return err_make(ERR_INVALID,"OpenCode turn identity missing");
        TRY(alloc(&c->arena,1,sizeof *t->requests,alignof(Request *),(void**)&t->requests));
        t->requests[0]=&s->requests[source];t->request_count=1;
        t->final_answer=answers[source];s->ordered_requests[i]=t->requests[0];
        CorpusTools tools={0};Err e=ERR_SUCCESS;
        for(size_t j=0;!e.code&&j<r->message_count;j++) {
            OpencodeMessage *m=&r->messages[j];
            if(m->inherited||!str_equal(m->turn,t->id)) continue;
            for(size_t k=0;!e.code&&k<m->tool_count;k++)
                e=claude_tool_count(&c->arena,&tools,tool_name(m->tools[k].name),m->tools[k].failed);
        }
        if(!e.code)e=corpus_turn_tools_adopt(&c->arena,s,t,&tools);
        omap_destroy(&tools.mcp);omap_destroy(&tools.other);TRY(e);
        corpus_status_flags(s,t->status);
    }
    s->title_full=meaningful_title(r->title)?r->title:(Str){0};
    s->title_source=s->title_full.n?STR_LIT("opencode_title"):STR_LIT("session_id");
    if(!s->title_full.n) {
        for(size_t i=0;i<s->request_count;i++) if(metadata_text(s->requests[i].text)) {
            s->title_full=s->requests[i].text;s->title_source=STR_LIT("first_request");break;
        }
    }
    if(!s->title_full.n) s->title_full=r->id;
    TRY(title_display(&c->arena,s->title_full,&s->title));
    if(s->is_subagent) {
        s->kind=STR_LIT("subagent");s->agent_label=s->title_full;
        if(r->agent.n) s->meta.agent_nickname=(JScalar){.kind=JS_STRING,.value.s=r->agent};
    }
    TRY(corpus_session_idle(&c->arena,s));
    return ERR_SUCCESS;
}

static Err link_sessions(OpencodeStore *store, Corpus *c, Omap *identified, Omap *origins) {
    TRY(corpus_graph_break_cycles(&c->arena,identified));
    for(OmapEntry *q=identified->first;q;q=q->next) {
        SessionModel *s=q->value;
        if(!s->is_subagent) continue;
        SessionModel *parent=omap_get(identified,s->parent_id);
        if(!parent) {
            s->kind=STR_LIT("orphan");s->flags|=F_ORPHAN;
            TRY(corpus_strings_add(&store->arena,&store->orphaned_subagents,s->id));
            continue;
        }
        TRY(corpus_strings_add(&c->arena,&parent->children,s->id));
        OpencodeSession *source=omap_get(origins,parent->id);
        Str spawn={0};bool conflict=false;
        for(size_t i=0;i<source->message_count;i++) {
            OpencodeMessage *m=&source->messages[i];
            if(m->inherited || !m->turn.n) continue;
            for(size_t k=0;k<m->tool_count;k++) if(str_equal(m->tools[k].child_session_id,s->id)) {
                if(spawn.n && !str_equal(spawn,m->turn)) conflict=true;
                spawn=m->turn;
            }
        }
        if(conflict) TRY(corpus_strings_add(&store->arena,&store->ambiguous_spawns,s->id));
        else if(spawn.n) {
            s->spawn_turn=spawn;s->link_method=STR_LIT("tool_use");
            for(size_t i=0;i<parent->turn_count;i++) if(str_equal(parent->turns[i].id,spawn)) {
                TRY(corpus_strings_add(&c->arena,&parent->turns[i].spawned,s->id));break;
            }
        }
    }
    for(OmapEntry *q=identified->first;q;q=q->next) {
        SessionModel *s=q->value,*p=s;size_t steps=0;
        while(p && !p->has_depth) {steps++;p=omap_get(identified,p->parent_id);}
        if(p) {s->has_depth=true;s->depth=p->depth+steps;}
        TRY(corpus_children_order(s,identified));
    }
    return ERR_SUCCESS;
}
Err opencode_corpus_add(OpencodeStore *store, int64_t snapshot, Corpus *c) {
    Omap identified={0},origins={0},public_ids={0};Err e=ERR_SUCCESS;
    for(OmapEntry *q=c->sessions.first;!e.code&&q;q=q->next) {
        SessionModel *s=q->value;
        e=omap_put(&public_ids,s->id,s);
    }
    for(size_t i=0;!e.code&&i<store->session_count;i++) {
        OpencodeSession *r=store->sessions[i];
        bool collision=omap_get(&c->sessions,r->id)||omap_get(&public_ids,r->id);
        if(collision) {e=corpus_strings_add(&store->arena,&store->corpus_collisions,r->id);continue;}
        SessionModel *s;
        e=alloc(&c->arena,1,sizeof *s,alignof(SessionModel),(void**)&s);
        /* Publish zeroed model before projection so corpus teardown owns all
         * maps even when a later allocation fails. Errors abort the build. */
        if(!e.code) e=omap_put(&c->sessions,r->id,s);
        if(!e.code) e=project_session(store,r,snapshot,c,s);
        if(!e.code) e=omap_put(&identified,s->id,s);
        if(!e.code) e=omap_put(&origins,s->id,r);
        if(!e.code) r->corpus_accepted=true;
    }
    if(!e.code) e=link_sessions(store,c,&identified,&origins);
    omap_destroy(&identified);omap_destroy(&origins);omap_destroy(&public_ids);
    return e;
}
