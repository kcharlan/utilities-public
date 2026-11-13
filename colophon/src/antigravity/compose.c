#include "compose.h"
#include "model.h"
#include "parse/tokenstream.h"
#include "price/claude_cost.h"
#include "price/claude_model.h"
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
typedef struct NameCount NameCount;
struct NameCount {NameCount *next;Str name,raw;size_t count;};
typedef struct {Arena arena;Omap aliases,numbers,counts;Event *first,*last;size_t count;AntigravityStore *store;AntigravityLedger *ledger;ModelsDevIndex *index;const PricingRules *rules;} Collection;
static Str scalar(AgMismatches *m,AgMessageType type,Str s,uint32_t n) {Str v={0};ag_wire_text(m,type,s,n,&v);return v;}
static bool model_marker(Str name) {
    if(str_equal(name,STR_LIT("antigravity/unattributed")))return true;
    Str prefix=STR_LIT("antigravity/model-");if(name.n<=prefix.n||memcmp(name.p,prefix.p,prefix.n))return false;
    for(uint32_t i=prefix.n;i<name.n;i++)if(name.p[i]<'0'||name.p[i]>'9')return false;
    return true;
}
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
static Err identify(Collection *c,Event *event,const Str ids[3]) {
    const uint32_t fields[]={11,12,7};Event *owner=event;
    for(size_t i=0;i<3;i++) {
        Str id=ids[i];if(!id.n)continue;
        JsonWriter w={0};jsonw_i64(&w,fields[i]);jsonw_raw(&w,":");jsonw_bytes(&w,id.p,id.n);
        Err e=w.error;if(e.code){jsonw_free(&w);return e;}
        Str key={w.data,(uint32_t)w.length};Event *seen=omap_get(&c->aliases,key);
        if(seen){Event *other=root(seen);owner=root(owner);
            if(other!=owner){if(other->order<owner->order){Event *t=owner;owner=other;other=t;}merge(owner,other);other->parent=owner;}}
        e=omap_put(&c->aliases,key,event);jsonw_free(&w);if(e.code)return e;
    }
    return ERR_SUCCESS;
}
static Err emit(Collection *c,SessionModel *s,Str usage,Str response,const AntigravityStep *step,Str chat,AntigravityPrevious *previous,bool *eligible) {
    const uint32_t fields[]={2,5,4,3,9,10};uint64_t tokens[6]={0};bool positive=false,reasoning=false;
    for(size_t i=0;i<6;i++){bool present=ag_wire_uint(&c->store->field_mismatches,AG_USAGE,usage,fields[i],&tokens[i])==AG_FOUND;
        if(present){if(tokens[i]>INT64_MAX){c->store->invalid_numbers++;return ERR_SUCCESS;}}
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
    const char *source=NULL;TRY(antigravity_model_typed(c->rules,&c->store->field_mismatches,&c->arena,response,usage,step?step->metadata:(Str){0},*previous,&c->numbers,&e->unit.model_raw,&e->unit.model,&source));
    if(strcmp(source,"previous")&&strcmp(source,"marker")){uint64_t number=0;bool has=ag_wire_uint(NULL,AG_USAGE,usage,1,&number)==AG_FOUND;*previous=(AntigravityPrevious){e->unit.model_raw,has,number};}
    MaybeMs at={0};if(step){const uint32_t clocks[]={8,7,1};for(size_t i=0;i<3&&!at.present;i++)TRY(antigravity_clock_typed(&c->store->field_mismatches,AG_STEP_METADATA,&c->arena,step->metadata,clocks[i],&at));e->step_clock=at.present;}
    if(!at.present){Str start={0};TRY(antigravity_message_merge_typed(&c->store->field_mismatches,AG_CHAT_MODEL,&c->arena,chat,9,&start));TRY(antigravity_clock_typed(&c->store->field_mismatches,AG_CHAT_START,&c->arena,start,4,&at));}
    if(!at.present){at=s->start_ms;c->store->unknown_clocks++;}
    e->unit.at_ms=e->unit.timestamp_ms=at;
    if(c->last)c->last->next=e;else c->first=e;c->last=e;
    AntigravityLedgerEvent saved={.order=e->order,.reasoning=e->reasoning,.step_clock=e->step_clock,.at_ms=e->unit.at_ms,.model_raw=e->unit.model_raw,.model_source=source};memcpy(saved.tokens,e->tokens,sizeof saved.tokens);
    const uint32_t id_fields[]={11,12,7};for(size_t i=0;i<3;i++)ag_wire_bytes(&c->store->field_mismatches,AG_USAGE,usage,id_fields[i],&saved.ids[i]);
    uint64_t model=0;saved.has_model_number=ag_wire_uint(&c->store->field_mismatches,AG_USAGE,usage,1,&model)==AG_FOUND;if(saved.has_model_number)saved.model_number=(int64_t)model;
    TRY(antigravity_ledger_capture(c->ledger,s,saved));return identify(c,e,saved.ids);
}
static Err collect_location(Collection *c,SessionModel *s,Str message,uint32_t direct,uint32_t retries,Str response,const AntigravityStep *step,Str chat,AntigravityPrevious *previous,bool *eligible) {
    Str u={0};TRY(antigravity_message_merge_typed(&c->store->field_mismatches,direct==4?AG_CHAT_MODEL:AG_STEP_METADATA,&c->arena,message,direct,&u));
    if(u.p)TRY(emit(c,s,u,response,step,chat,previous,eligible));
    AgCursor cursor={.input=message};AgField f;
    while(ag_wire_next(&cursor,&f)==AG_FOUND)if(f.number==retries){if(!ag_wire_message_field(&c->store->field_mismatches,direct==4?AG_CHAT_MODEL:AG_STEP_METADATA,&f))continue;TRY(antigravity_message_merge_typed(&c->store->field_mismatches,AG_RETRY,&c->arena,f.bytes,2,&u));if(u.p)TRY(emit(c,s,u,response,step,chat,previous,eligible));}
    return ERR_SUCCESS;
}
static Str index_key(int64_t index,char buffer[32]) {int n=snprintf(buffer,32,"%lld",(long long)index);return (Str){buffer,(uint32_t)n};}
/* Keep all candidates in discovery order so ties retain the earliest name. */
static Err learn(Collection *c,uint64_t number,Str raw) {
    raw=token_model_trim(raw);
    if(!raw.n||model_marker(raw))return ERR_SUCCESS;
    Str name={0};ClaudeLookup lookup={0};TRY(claude_models_dev_lookup(&c->arena,c->index,raw,&lookup));
    if(!lookup.catalog.model){Str stripped;TRY(antigravity_strip_routing(c->rules,&c->arena,raw,&stripped));TRY(claude_models_dev_lookup(&c->arena,c->index,stripped,&lookup));}
    if(lookup.catalog.model)name=lookup.catalog.identity;else TRY(antigravity_normalize_model(c->rules,&c->arena,raw,&name));if(!name.n)return ERR_SUCCESS;
    char buf[32];int len=snprintf(buf,sizeof buf,"%llu",(unsigned long long)number);Str key={buf,(uint32_t)len};
    NameCount *head=omap_get(&c->counts,key),*item=head,*last=NULL;
    while(item&&!str_equal(item->name,name)){last=item;item=item->next;}
    if(!item){Str saved;TRY(str_copy(&c->arena,raw,&saved));TRY(arena_alloc(&c->arena,sizeof *item,alignof(NameCount),(void**)&item));*item=(NameCount){.name=name,.raw=saved};if(last)last->next=item;else {head=item;TRY(omap_put(&c->counts,key,head));}}
    item->count++;NameCount *best=head;for(NameCount *p=head->next;p;p=p->next)if(p->count>best->count)best=p;
    return omap_put(&c->numbers,key,&best->raw);
}
static Err learn_usage(Collection *c,Str usage,Str response) {
    uint64_t number=0;if(ag_wire_uint(NULL,AG_USAGE,usage,1,&number)==AG_FOUND)return learn(c,number,response);return ERR_SUCCESS;
}
static Err learn_generators(Collection *c,AntigravitySession *r) {
    for(size_t i=0;i<r->generator_count;i++){
        Str chat={0},u={0};TRY(antigravity_message_merge_typed(NULL,AG_GENERATOR,&c->arena,r->generators[i].data,1,&chat));
        Str response=scalar(NULL,AG_CHAT_MODEL,chat,19);if(!response.n)continue;
        TRY(antigravity_message_merge_typed(NULL,AG_CHAT_MODEL,&c->arena,chat,4,&u));if(u.p)TRY(learn_usage(c,u,response));
        AgCursor cursor={.input=chat};AgField f;while(ag_wire_next(&cursor,&f)==AG_FOUND)if(f.number==17&&ag_wire_message_field(NULL,AG_CHAT_MODEL,&f)){
            TRY(antigravity_message_merge_typed(NULL,AG_RETRY,&c->arena,f.bytes,2,&u));if(u.p)TRY(learn_usage(c,u,response));
        }
    }return ERR_SUCCESS;
}
static Err session(Collection *c,AntigravitySession *r,SessionModel *s) {
    Omap executions={0},indices={0},turns={0},first_generators={0};Err e=ERR_SUCCESS;AntigravityPrevious previous={0};
    for(size_t i=0;!e.code&&i<r->step_count;i++){
        AntigravityStep *step=&r->steps[i];char key[32];e=omap_put(&indices,index_key(step->idx,key),step);
        Str id=scalar(&c->store->field_mismatches,AG_STEP_METADATA,step->metadata,12);if(!e.code&&id.n&&!omap_get(&executions,id))e=omap_put(&executions,id,step);
    }
    for(size_t i=0;!e.code&&i<s->turn_count;i++){s->turns[i].ttft_ms=(MaybeNum){0};e=omap_put(&turns,s->turns[i].id,&s->turns[i]);}
    for(size_t i=0;!e.code&&i<r->generator_count;i++){
        Str gen=r->generators[i].data,chat={0};e=antigravity_message_merge_typed(&c->store->field_mismatches,AG_GENERATOR,&c->arena,gen,1,&chat);if(e.code)break;
        AntigravityStep *step=omap_get(&executions,scalar(&c->store->field_mismatches,AG_GENERATOR,gen,4));
        if(!step){AgCursor cursor={.input=gen};uint64_t n=0;
            if(ag_wire_integer_next_typed(&c->store->field_mismatches,AG_GENERATOR,&cursor,2,&n)==AG_FOUND){char key[32];step=omap_get(&indices,index_key((int64_t)n,key));}}
        if(step&&step->turn.n&&!omap_get(&first_generators,step->turn)){
            e=omap_put(&first_generators,step->turn,step);TurnModel *turn=omap_get(&turns,step->turn);
            MaybeMs duration={0};if(!e.code)e=antigravity_clock_typed(&c->store->field_mismatches,AG_CHAT_MODEL,&c->arena,chat,11,&duration);
            if(turn&&duration.present&&duration.value>=0)turn->ttft_ms=(MaybeNum){true,{.i=duration.value}};
        }
        bool eligible=false;if(!e.code)e=collect_location(c,s,chat,4,17,scalar(&c->store->field_mismatches,AG_CHAT_MODEL,chat,19),step,chat,&previous,&eligible);
        if(!eligible)c->store->requests_without_usage++;
    }
    for(size_t i=0;!e.code&&i<r->step_count;i++){bool eligible=false;e=collect_location(c,s,r->steps[i].metadata,9,28,(Str){0},&r->steps[i],(Str){0},&previous,&eligible);}
    omap_destroy(&executions);omap_destroy(&indices);omap_destroy(&turns);omap_destroy(&first_generators);return e;
}
Err antigravity_compose(AntigravityStore *store,Corpus *corpus,ModelsDevIndex *index,PricingReport *report,AntigravityLedger *ledger) {
    PricingReport scratch={.rules=index?index->rules:NULL};bool local=!report;if(local)report=&scratch;
    Collection c={.store=store,.ledger=ledger,.index=index,.rules=report->rules};Err error=ERR_SUCCESS;
    store->cross_session_duplicates=store->requests_without_usage=store->invalid_numbers=store->unknown_clocks=store->ledger_shrunk=0;
    if(ledger)for(size_t i=0;!error.code&&i<ledger->count;i++){AntigravityLedgerRecord *r=ledger->records[i];if(r->unreadable)continue;for(size_t j=0;!error.code&&j<r->event_count;j++){AntigravityLedgerEvent *e=&r->events[j];if(e->has_model_number&&e->model_source&&!strcmp(e->model_source,"response"))error=learn(&c,(uint64_t)e->model_number,e->model_raw);}}
    for(size_t i=0;!error.code&&i<store->session_count;i++)if(store->sessions[i]->corpus_accepted)error=learn_generators(&c,store->sessions[i]);
    for(size_t i=0;!error.code&&i<store->session_count;i++){
        AntigravitySession *r=store->sessions[i];if(!r->corpus_accepted)continue;
        SessionModel *s=omap_get(&corpus->sessions,r->id);
        if(!s||s->provider!=PROVIDER_ANTIGRAVITY){error=err_make(ERR_INVALID,"missing Antigravity corpus session");break;}
        error=antigravity_ledger_begin(ledger,s,r);if(!error.code)error=session(&c,r,s);
        if(!error.code&&ledger){AntigravityLedgerRecord *record=omap_get(&ledger->by_id,s->id);if(record&&record->live&&record->event_count<record->previous_count)store->ledger_shrunk++;}
    }
    if(ledger)for(size_t i=0;!error.code&&i<ledger->count;i++){AntigravityLedgerRecord *r=ledger->records[i];if(!r->retained)continue;
        for(size_t j=0;!error.code&&j<r->event_count;j++){AntigravityLedgerEvent *saved=&r->events[j];Event *e=NULL;error=arena_alloc(&c.arena,sizeof *e,alignof(Event),(void**)&e);if(error.code)break;
            *e=(Event){.order=c.count++,.session=&r->header,.reasoning=saved->reasoning,.step_clock=saved->step_clock};memcpy(e->tokens,saved->tokens,sizeof e->tokens);
            e->unit=(UsageUnit){.session_id=r->header.id,.source=STR_LIT("antigravity"),.at_ms=saved->at_ms,.timestamp_ms=saved->at_ms,.model_raw=saved->model_raw};
            if(saved->has_model_number&&model_marker(saved->model_raw)){
                char key[32];int n=snprintf(key,sizeof key,"%llu",(unsigned long long)(uint64_t)saved->model_number);
                Str rule=rules_antigravity_model_number(c.rules,(uint64_t)saved->model_number);Str *learned=omap_get(&c.numbers,(Str){key,(uint32_t)n});if(rule.n)e->unit.model_raw=rule;else if(learned)e->unit.model_raw=*learned;
            }
            error=antigravity_normalize_model(c.rules,&c.arena,e->unit.model_raw,&e->unit.model);if(error.code)break;
            if(c.last)c.last->next=e;else c.first=e;c.last=e;error=identify(&c,e,saved->ids);
        }
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
        for(size_t i=0;!error.code&&i<s->unit_count;i++)error=str_copy(&corpus->usage_arena,s->units[i].model,&s->units[i].model);
        if(!error.code)error=compose_aggregate_session(corpus,s);
    }
    if(!error.code)error=store->field_mismatches.error;omap_destroy(&c.aliases);omap_destroy(&c.numbers);omap_destroy(&c.counts);arena_destroy(&c.arena);if(local)pricing_report_destroy(&scratch);return error;
}
