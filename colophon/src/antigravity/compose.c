#include "compose.h"
#include "model.h"
#include "price/claude_cost.h"
#include "parse/record.h"
#include <stdalign.h>
#include <stdio.h>
#include <string.h>
#define TRY(x) do {Err e_=(x);if(e_.code)return e_;}while(0)
typedef struct Event Event;
struct Event {
    Event *parent,*next;size_t order;
    SessionModel *session;UsageUnit unit;
    uint64_t tokens[6]; /* fresh, read, write, reported output, thinking, reconciled visible */
    bool reasoning,step_clock;
};
typedef struct {Arena arena;Omap aliases;Event *first,*last;size_t count;AntigravityStore *store;} Collection;
static Str scalar(Str s,uint32_t n) {AgField f={0};return ag_wire_last(s,n,&f)==AG_FOUND?f.bytes:(Str){0};}
static Event *root(Event *e) {Event *r=e;while(r->parent)r=r->parent;while(e->parent){Event *p=e->parent;e->parent=r;e=p;}return r;}
static void merge(Event *a,Event *b) {
    for(size_t i=0;i<6;i++)if(b->tokens[i]>a->tokens[i])a->tokens[i]=b->tokens[i];
    a->reasoning|=b->reasoning;
    if(b->step_clock&&!a->step_clock){a->unit.at_ms=b->unit.at_ms;a->unit.timestamp_ms=b->unit.timestamp_ms;a->step_clock=true;}
}
/* ccusage 20.0.42 synthetic native probes: response_id, provider-assigned ID
 * and message_id are independent namespaces, not priority candidates. Any
 * shared alias joins components, including transitive bridges. Missing/empty
 * aliases are never token fingerprints. Earliest discovery owns the component.
 * The source Rust algorithms have not been independently verified. */
static Err identify(Collection *c,Event *event,Str usage) {
    const uint32_t fields[]={11,12,7};Event *owner=event;
    for(size_t i=0;i<3;i++) {
        Str id=scalar(usage,fields[i]);if(!id.n)continue;
        JsonWriter w={0};jsonw_i64(&w,fields[i]);jsonw_raw(&w,":");jsonw_bytes(&w,id.p,id.n);
        Err e=w.error;if(e.code){jsonw_free(&w);return e;}
        Str key={w.data,(uint32_t)w.length};Event *seen=omap_get(&c->aliases,key);
        if(seen){Event *other=root(seen);owner=root(owner);
            if(other!=owner){if(other->order<owner->order){Event *t=owner;owner=other;other=t;}merge(owner,other);other->parent=owner;}}
        e=omap_put(&c->aliases,key,event);jsonw_free(&w);if(e.code)return e;
    }
    return ERR_SUCCESS;
}
static Err emit(Collection *c,SessionModel *s,Str usage,Str response,const AntigravityStep *step,Str chat,Str *previous,bool *eligible) {
    const uint32_t fields[]={2,5,4,3,9,10};uint64_t tokens[6]={0};bool positive=false,reasoning=false;
    for(size_t i=0;i<6;i++){AgField f={0};bool present=ag_wire_last(usage,fields[i],&f)==AG_FOUND;
        if(present){tokens[i]=f.integer;if(tokens[i]>INT64_MAX){c->store->invalid_numbers++;return ERR_SUCCESS;}}
        positive|=tokens[i]!=0;if(i==4)reasoning=present;
    }
    /* Reconcile each observation before merging copies. A smaller thinking
     * count can expose more visible output in one copy; taking raw maxima
     * first would erase that evidence. Native 20.0.42 probes pin this order. */
    uint64_t visible=tokens[3]>tokens[4]?tokens[3]-tokens[4]:0;
    if(visible>tokens[5])tokens[5]=visible;
    uint64_t in=tokens[0]+tokens[1];bool bad=in>INT64_MAX;
    if(!bad){in+=tokens[2];bad=in>INT64_MAX;}
    uint64_t out=tokens[4]+tokens[5];if(tokens[3]>out)out=tokens[3];
    if(bad||out>INT64_MAX||in>(uint64_t)INT64_MAX-out){c->store->invalid_numbers++;return ERR_SUCCESS;}
    if(!positive)return ERR_SUCCESS;*eligible=true;
    Event *e;TRY(arena_alloc(&c->arena,sizeof *e,alignof(Event),(void**)&e));
    *e=(Event){.order=c->count++,.session=s,.reasoning=reasoning};memcpy(e->tokens,tokens,sizeof tokens);
    e->unit=(UsageUnit){.session_id=s->id,.source=STR_LIT("antigravity"),.display_turn=step?step->turn:(Str){0}};
    TRY(antigravity_model(&c->arena,response,usage,step?step->metadata:(Str){0},*previous,&e->unit.model_raw,&e->unit.model));
    if(!str_equal(e->unit.model_raw,STR_LIT("antigravity/unattributed")))*previous=e->unit.model_raw;
    MaybeMs at={0};if(step){const uint32_t clocks[]={8,7,1};for(size_t i=0;i<3&&!at.present;i++)TRY(antigravity_clock(&c->arena,step->metadata,clocks[i],&at));e->step_clock=at.present;}
    if(!at.present){Str start={0};TRY(antigravity_message_merge(&c->arena,chat,9,&start));TRY(antigravity_clock(&c->arena,start,4,&at));}
    if(!at.present){at=s->start_ms;c->store->unknown_clocks++;}
    e->unit.at_ms=e->unit.timestamp_ms=at;
    if(c->last)c->last->next=e;else c->first=e;c->last=e;
    return identify(c,e,usage);
}
static Err collect_location(Collection *c,SessionModel *s,Str message,uint32_t direct,uint32_t retries,Str response,const AntigravityStep *step,Str chat,Str *previous,bool *eligible) {
    Str u={0};TRY(antigravity_message_merge(&c->arena,message,direct,&u));
    if(u.p)TRY(emit(c,s,u,response,step,chat,previous,eligible));
    AgCursor cursor={.input=message};AgField f;
    while(ag_wire_next(&cursor,&f)==AG_FOUND)if(f.number==retries){TRY(antigravity_message_merge(&c->arena,f.bytes,2,&u));if(u.p)TRY(emit(c,s,u,response,step,chat,previous,eligible));}
    return ERR_SUCCESS;
}
static Str index_key(int64_t index,char buffer[32]) {int n=snprintf(buffer,32,"%lld",(long long)index);return (Str){buffer,(uint32_t)n};}
static Err session(Collection *c,AntigravitySession *r,SessionModel *s) {
    Omap executions={0},indices={0},turns={0},first_generators={0};Err e=ERR_SUCCESS;Str previous={0};
    for(size_t i=0;!e.code&&i<r->step_count;i++){
        AntigravityStep *step=&r->steps[i];char key[32];e=omap_put(&indices,index_key(step->idx,key),step);
        Str id=scalar(step->metadata,12);if(!e.code&&id.n&&!omap_get(&executions,id))e=omap_put(&executions,id,step);
    }
    for(size_t i=0;!e.code&&i<s->turn_count;i++){s->turns[i].ttft_ms=(MaybeNum){0};e=omap_put(&turns,s->turns[i].id,&s->turns[i]);}
    for(size_t i=0;!e.code&&i<r->generator_count;i++){
        Str gen=r->generators[i].data,chat={0};e=antigravity_message_merge(&c->arena,gen,1,&chat);if(e.code)break;
        AntigravityStep *step=omap_get(&executions,scalar(gen,4));
        if(!step){AgCursor cursor={.input=gen};uint64_t n=0;
            if(ag_wire_integer_next(&cursor,2,&n)==AG_FOUND){char key[32];step=omap_get(&indices,index_key((int64_t)n,key));}}
        if(step&&step->turn.n&&!omap_get(&first_generators,step->turn)){
            e=omap_put(&first_generators,step->turn,step);TurnModel *turn=omap_get(&turns,step->turn);
            MaybeMs duration={0};if(!e.code)e=antigravity_clock(&c->arena,chat,11,&duration);
            if(turn&&duration.present&&duration.value>=0)turn->ttft_ms=(MaybeNum){true,{.i=duration.value}};
        }
        bool eligible=false;if(!e.code)e=collect_location(c,s,chat,4,17,scalar(chat,19),step,chat,&previous,&eligible);
        if(!eligible)c->store->requests_without_usage++;
    }
    for(size_t i=0;!e.code&&i<r->step_count;i++){bool eligible=false;e=collect_location(c,s,r->steps[i].metadata,9,28,(Str){0},&r->steps[i],(Str){0},&previous,&eligible);}
    omap_destroy(&executions);omap_destroy(&indices);omap_destroy(&turns);omap_destroy(&first_generators);return e;
}
Err antigravity_compose(AntigravityStore *store,Corpus *corpus,ModelsDevIndex *index,PricingReport *report) {
    PricingReport scratch={0};bool local=!report;if(local)report=&scratch;
    Collection c={.store=store};Err error=ERR_SUCCESS;
    store->cross_session_duplicates=store->requests_without_usage=store->invalid_numbers=store->unknown_clocks=0;
    for(size_t i=0;!error.code&&i<store->session_count;i++){
        AntigravitySession *r=store->sessions[i];if(!r->corpus_accepted)continue;
        SessionModel *s=omap_get(&corpus->sessions,r->id);
        if(!s||s->provider!=PROVIDER_ANTIGRAVITY){error=err_make(ERR_INVALID,"missing Antigravity corpus session");break;}
        error=session(&c,r,s);
    }
    for(Event *e=c.first;!error.code&&e;e=e->next){Event *owner=root(e);if(owner!=e){if(owner->session!=e->session)store->cross_session_duplicates++;continue;}
        __int128 in=(__int128)e->tokens[0]+e->tokens[1]+e->tokens[2],out=(__int128)e->tokens[4]+e->tokens[5];if(e->tokens[3]>out)out=e->tokens[3];
        if(in>INT64_MAX||out>INT64_MAX||in+out>INT64_MAX){store->invalid_numbers++;continue;}
        UsageUnit u=e->unit;u.input=in;u.cached=e->tokens[1];u.cache_write=e->tokens[2];u.output=out;u.reasoning=(OptionalTokens){e->reasoning,(int64_t)e->tokens[4]};
        error=str_copy(&corpus->usage_arena,u.model_raw,&u.model_raw);if(!error.code)error=str_copy(&corpus->usage_arena,u.model,&u.model);
        SessionModel *s=e->session;if(!error.code)error=record_append_aligned(&corpus->usage_arena,(void**)&s->units,&s->unit_count,&s->unit_capacity,sizeof u,alignof(UsageUnit),&u);
    }
    for(OmapEntry *q=corpus->sessions.first;!error.code&&q;q=q->next){SessionModel *s=q->value;if(s->provider!=PROVIDER_ANTIGRAVITY)continue;
        error=catalog_price_usage_units(s->units,s->unit_count,index,report,STR_LIT("antigravity:"),true);
        if(!error.code)error=compose_aggregate_session(corpus,s);
    }
    omap_destroy(&c.aliases);arena_destroy(&c.arena);if(local)pricing_report_destroy(&scratch);return error;
}
