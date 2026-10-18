#include "compose.h"
#include "parse/record.h"
#include "util/sort.h"
#include <math.h>
#include <stdalign.h>
#include <string.h>

#define TRY(x) do { Err e_=(x); if(e_.code)return e_; } while(0)
#define APPEND(a,p,n,c,v) record_append_aligned(a,(void**)&(p),&(n),&(c),sizeof(v),alignof(OpencodeTokens),&(v))
static Err alloc(Arena *a,size_t size,size_t alignment,void **out) {
    TRY(arena_alloc(a,size,alignment,out));memset(*out,0,size);return ERR_SUCCESS;
}
void opencode_usage_destroy(OpencodeStore *store) {
    if(store->usage)omap_destroy(&store->usage->missing_by_provider);
    store->usage=NULL;
}
static Err invalid(OpencodeStore *store,const OpencodeSession *s,OpencodeUsageInvalidContext context) {
    OpencodeUsageReport *r=store->usage;OpencodeUsageInvalid value={s,context};
    return APPEND(&store->arena,r->invalid,r->invalid_count,r->invalid_capacity,value);
}
static bool eligible(const OpencodeMessage *m) {
    return m->kind==OC_MSG_ASSISTANT||(m->kind==OC_MSG_COMPACTION&&
        (str_equal(m->status,STR_LIT("completed"))||str_equal(m->status,STR_LIT("failed"))));
}
static bool positive(OpencodeTokens t) {
    return t.input||t.output||t.reasoning||t.cache_read||t.cache_write;
}
/* Parsing bounds every component to int64; the sum keeps that exact raw
 * component space in aligned int128 storage until mapping/serialization. */
static bool add_tokens(OpencodeTokens *sum,OpencodeTokens value) {
    OpencodeTokens result;
    if(__builtin_add_overflow(sum->input,value.input,&result.input)||
       __builtin_add_overflow(sum->output,value.output,&result.output)||
       __builtin_add_overflow(sum->reasoning,value.reasoning,&result.reasoning)||
       __builtin_add_overflow(sum->cache_read,value.cache_read,&result.cache_read)||
       __builtin_add_overflow(sum->cache_write,value.cache_write,&result.cache_write))return false;
    *sum=result;return true;
}
static Err model(Arena *a,const OpencodeMessage *m,Str *out) {
    if(!m||!m->provider_id.n||!m->model_id.n){*out=STR_LIT("opencode/unattributed");return ERR_SUCCESS;}
    JsonWriter w={0};jsonw_bytes(&w,m->provider_id.p,m->provider_id.n);jsonw_raw(&w,"/");jsonw_bytes(&w,m->model_id.p,m->model_id.n);
    Err e=w.error;if(!e.code)e=str_copy(a,(Str){w.data,(uint32_t)w.length},out);jsonw_free(&w);return e;
}
static Err unit(Corpus *c,SessionModel *s,OpencodeTokens tokens,const OpencodeMessage *m,
                MaybeMs at,bool has_cost,double cost) {
    UsageUnit u={.session_id=s->id,.source=STR_LIT("opencode"),.at_ms=at,.timestamp_ms=at,
        .display_turn=m?m->turn:(Str){0},.has_cost=has_cost,.cost_usd=has_cost?cost:0,
        .input=tokens.input+tokens.cache_read+tokens.cache_write,.cached=tokens.cache_read,
        .cache_write=tokens.cache_write,.output=tokens.output+tokens.reasoning,
        .reasoning={true,(int64_t)tokens.reasoning}};
    TRY(model(&c->usage_arena,m,&u.model));u.model_raw=u.model;
    return APPEND(&c->usage_arena,s->units,s->unit_count,s->unit_capacity,u);
}
static Err missing(OpencodeStore *store,const OpencodeMessage *m) {
    OpencodeUsageReport *r=store->usage;r->missing_usage++;
    Str key=m->provider_id.n?m->provider_id:STR_LIT("opencode/unattributed");
    uint64_t *count=omap_get(&r->missing_by_provider,key);
    if(!count){TRY(alloc(&store->arena,sizeof *count,alignof(uint64_t),(void**)&count));TRY(omap_put(&r->missing_by_provider,key,count));}
    (*count)++;return ERR_SUCCESS;
}
static int message_order(const void *a,const void *b,void *context) {
    (void)context;int64_t x=(*(const OpencodeMessage *const*)a)->seq,y=(*(const OpencodeMessage *const*)b)->seq;
    return (x>y)-(x<y);
}
static OpencodeTokens difference(OpencodeTokens total,OpencodeTokens sum,bool shortfall) {
#define DIFF(field) .field=shortfall?(sum.field>total.field?sum.field-total.field:0):(total.field>sum.field?total.field-sum.field:0)
    return (OpencodeTokens){DIFF(input),DIFF(output),DIFF(reasoning),DIFF(cache_read),DIFF(cache_write)};
#undef DIFF
}
static Err session(OpencodeStore *store,Corpus *c,OpencodeSession *raw,SessionModel *s) {
    OpencodeUsageReport *r=store->usage;
    OpencodeMessage **ordered=NULL;
    if(raw->message_count>SIZE_MAX/sizeof *ordered)return err_make(ERR_NOMEM,"OpenCode usage order overflow");
    TRY(alloc(&store->arena,raw->message_count*sizeof *ordered,alignof(OpencodeMessage*),(void**)&ordered));
    for(size_t i=0;i<raw->message_count;i++)ordered[i]=&raw->messages[i];
    TRY(stable_sort(ordered,raw->message_count,sizeof *ordered,message_order,NULL));
    OpencodeTokens sum={0};double costs=0;bool token_sum_valid=true,cost_sum_valid=true,all_costs=true;
    bool incomplete=!raw->provenance_complete||raw->malformed_messages||raw->unknown_message_types.size||raw->unknown_content_types.size;
    for(size_t i=0;i<raw->message_count;i++) {
        const OpencodeMessage *m=ordered[i];
        if(m->inherited){r->inherited++;continue;}
        if(!eligible(m))continue;
        r->requests++;
        bool usable=m->tokens_valid&&positive(m->tokens);
        bool valid_cost=m->cost_valid&&isfinite(m->cost)&&m->cost>=0;
        if(!usable)TRY(missing(store,m));
        if(!m->tokens_valid)incomplete=true;
        if(!valid_cost)all_costs=false;
        bool cost_only=!usable&&valid_cost&&m->cost>0;
        if(cost_only){r->cost_only++;incomplete=true;}
        if(!usable&&!cost_only)continue;
        OpencodeTokens tokens=usable?m->tokens:(OpencodeTokens){0};
        if(token_sum_valid&&!add_tokens(&sum,tokens)){
            token_sum_valid=false;TRY(invalid(store,raw,OC_USAGE_MESSAGE_TOKEN_SUM));
        }
        if(valid_cost&&cost_sum_valid){double next=costs+m->cost;
            if(!isfinite(next)){cost_sum_valid=false;TRY(invalid(store,raw,OC_USAGE_MESSAGE_COST_SUM));}
            else costs=next;
        }
        MaybeMs at=m->completed_ms.present?m->completed_ms:m->created_ms;
        TRY(unit(c,s,tokens,m,at,valid_cost,m->cost));
    }
    if(!cost_sum_valid)for(size_t i=0;i<s->unit_count;i++){s->units[i].has_cost=false;}
    if(raw->tokens_present&&!raw->tokens_valid)TRY(invalid(store,raw,OC_USAGE_ROLLUP_TOKENS));
    bool rollup_cost=raw->cost_valid&&isfinite(raw->cost)&&raw->cost>=0;
    if(raw->cost_present&&!rollup_cost)TRY(invalid(store,raw,OC_USAGE_ROLLUP_COST));
    OpencodeTokens remaining={0},shortfall={0};
    if(raw->tokens_valid&&token_sum_valid){remaining=difference(raw->tokens,sum,false);shortfall=difference(raw->tokens,sum,true);}
    bool cost_difference_valid=rollup_cost&&cost_sum_valid;double delta=0;
    if(cost_difference_valid){delta=raw->cost-costs;
        if(!isfinite(delta)){cost_difference_valid=false;TRY(invalid(store,raw,OC_USAGE_RESIDUAL_COST));}
        else if(fabs(delta)<=1e-9)delta=0;
    }
    if(positive(shortfall)||(cost_difference_valid&&delta<0)){
        OpencodeUsageDifference d={.session=raw,.tokens=shortfall,.has_cost=cost_difference_valid&&delta<0,
            .cost=delta<0?-delta:0,.date=raw->created_ms};
        TRY(APPEND(&store->arena,r->shortfalls,r->shortfall_count,r->shortfall_capacity,d));
    }
    if(positive(remaining)||(cost_difference_valid&&delta>0)) {
        bool known=cost_difference_valid&&(delta>0||(delta==0&&all_costs&&!incomplete));
        OpencodeUsageDifference d={.session=raw,.tokens=remaining,.has_cost=known,.cost=known&&delta>0?delta:0,.date=raw->created_ms};
        TRY(APPEND(&store->arena,r->residuals,r->residual_count,r->residual_capacity,d));
        TRY(unit(c,s,remaining,NULL,raw->created_ms,known,d.cost));
    }
    return compose_aggregate_session(c,s);
}
Err opencode_compose(OpencodeStore *store,Corpus *corpus) {
    if(store->usage)return err_make(ERR_INVALID,"OpenCode usage already composed");
    TRY(alloc(&store->arena,sizeof *store->usage,alignof(OpencodeUsageReport),(void**)&store->usage));
    for(size_t i=0;i<store->session_count;i++) {
        OpencodeSession *raw=store->sessions[i];if(!raw->corpus_accepted)continue;
        SessionModel *s=omap_get(&corpus->sessions,raw->id);
        if(!s||s->provider!=PROVIDER_OPENCODE)return err_make(ERR_INVALID,"missing OpenCode corpus session");
        TRY(session(store,corpus,raw,s));
    }
    return ERR_SUCCESS;
}
