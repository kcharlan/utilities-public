#include "pricing.h"
#include "util/events.h"
#include "util/json_read.h"
#include "util/sort.h"
#include <stdlib.h>
#include <string.h>
static yyjson_val *get(yyjson_val *v,const char *key){return obj_get_last(v,(Str){key,(uint32_t)strlen(key)});}
static Err allocate(PricingReport *report,size_t size,size_t alignment,void **out) {
    Err e=arena_alloc(&report->arena,size,alignment,out);if(!e.code)memset(*out,0,size);return e;
}
static Err periods_for(PricingReport *report,Str key,PricingPeriods **out) {
    *out=omap_get(&report->periods,key);if(*out)return ERR_SUCCESS;
    Err e=allocate(report,sizeof **out,_Alignof(PricingPeriods),(void **)out);if(e.code)return e;
    e=str_copy(&report->arena,key,&(*out)->key);if(e.code)return e;
    return omap_put(&report->periods,key,*out);
}
static Err append_period(PricingPeriods *group,PricingPeriod *period) {
    if(group->count==group->capacity) {
        size_t next=group->capacity?group->capacity*2:8;
        if(next<group->capacity||next>SIZE_MAX/sizeof *group->items)return err_make(ERR_NOMEM,"pricing periods overflow");
        PricingPeriod **grown=realloc(group->items,next*sizeof *grown);if(!grown)return err_make(ERR_NOMEM,"pricing periods allocation");
        group->items=grown;group->capacity=next;
    }
    group->items[group->count++]=period;return ERR_SUCCESS;
}
Err pricing_report_init(const PriceHistory *history,PricingReport *out) {
    for(OmapEntry *entry=history->groups.first;entry;entry=entry->next) {
        const HistoryGroup *source=entry->value;PricingPeriods *group;
        Err e=periods_for(out,entry->key,&group);if(e.code)return e;
        for(size_t i=0;i<source->count;i++) {
            PricingPeriod *period;e=allocate(out,sizeof *period,_Alignof(PricingPeriod),(void **)&period);if(e.code)return e;
            period->history=source->entries[i];period->rates=source->entries[i]->rates;period->priority=source->entries[i]->priority;
            e=append_period(group,period);if(e.code)return e;
        }
    }
    return ERR_SUCCESS;
}
static Err count_add(PricingReport *report,Omap *map,Str key,__int128 amount) {
    __int128 *count=omap_get(map,key);
    if(!count){Err e=allocate(report,sizeof *count,_Alignof(__int128),(void **)&count);if(e.code)return e;e=omap_put(map,key,count);if(e.code)return e;}
    if(__builtin_add_overflow(*count,amount,count))return err_make(ERR_INVALID,"pricing token sum overflow");
    return ERR_SUCCESS;
}
static Err picked(PricingReport *report,const PriceHistory *history,Str model,int64_t at,HistoryPick *out) {
    *out=history_pick(history,model,at);
    if(out->entry&&out->before_first) {
        int64_t *clock=omap_get(&report->history_begins,model);
        if(!clock){Err e=allocate(report,sizeof *clock,_Alignof(int64_t),(void **)&clock);if(e.code)return e;e=omap_put(&report->history_begins,model,clock);if(e.code)return e;}
        *clock=out->entry->effective_ms;
    }
    return ERR_SUCCESS;
}
static Err catalog_match(ModelsDevIndex *index,Str raw,CatalogLookup *out) {
    *out=(CatalogLookup){0};if(!index)return ERR_SUCCESS;
    Arena scratch={0};PricingTargets targets;Err e=codex_models_dev_pricing_targets(&scratch,raw,&targets);
    if(!e.code)for(size_t i=0;i<targets.count;i++){e=models_dev_pricing(index,STR_LIT("openai"),targets.model[i],out);if(e.code||out->model)break;}
    arena_destroy(&scratch);return e;
}
static Err override_key(PricingReport *report,ModelsDevIndex *index,Str raw,Str normalized,Str *out) {
    *out=(Str){0};CatalogLookup a,b;Err e=catalog_match(index,raw,&a);if(e.code)return e;e=catalog_match(index,normalized,&b);if(e.code)return e;
    if(!a.model||(b.model&&str_equal(a.identity,b.identity)))return ERR_SUCCESS;
    JsonWriter bytes={0};jsonw_raw(&bytes,"catalog:");jsonw_bytes(&bytes,a.identity.p,a.identity.n);jsonw_raw(&bytes,"|");jsonw_bytes(&bytes,normalized.p,normalized.n);
    e=bytes.error;if(!e.code)e=str_copy(&report->arena,(Str){bytes.data,(uint32_t)bytes.length},out);jsonw_free(&bytes);return e;
}
static bool priority_equal(PricePriority a,PricePriority b) {
    return a.present==b.present&&(!a.present||(a.capped==b.capped&&(!a.capped||a.cap==b.cap)&&pynum_equal(a.multiplier,b.multiplier)));
}
static Err rates_at(PricingReport *report,const PriceHistory *history,ModelsDevIndex *index,Str key,Str source,
                    int64_t at,bool current,PricePriority priority,const PriceEntry **out,PricePeriod *reference) {
    *out=NULL;*reference=(PricePeriod){0};HistoryPick pick={0};Err e=ERR_SUCCESS;
    if(!current){e=picked(report,history,key,at,&pick);if(e.code)return e;}
    PricingPeriods *group;e=periods_for(report,key,&group);if(e.code)return e;
    if(pick.entry){*out=&pick.entry->rates;*reference=(PricePeriod){true,group->key,pick.index};return ERR_SUCCESS;}
    PriceEntry rates;bool found;e=resolve_rates(source,index,&rates,&found);if(e.code||!found)return e;
    size_t position=0;
    for(;position<group->count;position++) {
        PricingPeriod *p=group->items[position];if(!p->history&&price_entry_equal(&p->rates,&rates)&&priority_equal(p->priority,priority))break;
    }
    if(position==group->count) {
        PricingPeriod *period;e=allocate(report,sizeof *period,_Alignof(PricingPeriod),(void **)&period);if(e.code)return e;
        period->rates=rates;period->priority=priority;e=append_period(group,period);if(e.code)return e;
    }
    CatalogLookup match;e=catalog_match(index,source,&match);if(e.code)return e;
    if(match.model){e=omap_put(&report->unrecorded,group->key,(void *)1);if(e.code)return e;}
    *out=&group->items[position]->rates;*reference=(PricePeriod){true,group->key,position};return ERR_SUCCESS;
}
static bool cutoff_for(Str model,int64_t *cutoff) {
    if(str_equal(model,STR_LIT("gpt-5.6-sol"))){*cutoff=INT64_C(1787270400000);return true;}
    if(str_equal(model,STR_LIT("gpt-5.6-terra"))||str_equal(model,STR_LIT("gpt-5.6-luna"))){*cutoff=INT64_C(1785369600000);return true;}
    return false;
}
Err price_usage_units(UsageUnit *units,size_t count,const PriceHistory *history,ModelsDevIndex *index,bool available,PricingReport *report) {
    for(size_t i=0;i<count;i++) {
        UsageUnit *unit=&units[i];unit->has_cost=false;unit->cost_usd=0;unit->period=unit->priority_period=(PricePeriod){0};
        PricingPeriods *unused;Err e=periods_for(report,unit->model,&unused);if(e.code)return e;
        if(!available)continue;
        Str trace=unit->priority&&(unit->priority_fields&PRIORITY_MODEL)?unit->priority->model:(Str){0};
        bool override=trace.p&&codex_api_fast_multiplier(trace)!=0;
        Str raw=override?trace:unit->model_raw,normalized;
        if(index){e=models_dev_normalize(index,raw,&normalized);if(e.code)return e;}
        else normalized=normalize_codex_model(raw);
        if(str_equal(normalized,STR_LIT("unknown"))){e=count_add(report,&report->unpriced,unit->model,unit->input+unit->output);if(e.code)return e;continue;}
        const PriceEntry *rates=NULL;PricePriority priority={0};
        if(!unit->at_ms.present) {
            double multiplier=unit->priority_tier?codex_api_fast_multiplier(raw):0;
            if(multiplier)priority=(PricePriority){.present=true,.capped=!str_equal(normalized,STR_LIT("gpt-6-astra")),.cap=272000,.multiplier={.is_float=true,.f=multiplier}};
            Str key={0};if(override){e=override_key(report,index,raw,normalized,&key);if(e.code)return e;}
            e=rates_at(report,history,index,key.p?key:normalized,override?raw:normalized,0,true,priority,&rates,&unit->period);if(e.code)return e;
            if(!rates){e=count_add(report,&report->unpriced,unit->model,unit->input+unit->output);if(e.code)return e;continue;}
            e=count_add(report,&report->untimed,unit->model,unit->input+unit->output);if(e.code)return e;
            unit->has_cost=true;unit->cost_usd=cost_usd(rates,unit->input,unit->cached,unit->output);
            if(unit->priority_tier) {
                double fast;if(priority_cost_usd(rates,&priority,unit->input,unit->cached,unit->output,&fast)&&fast>unit->cost_usd)unit->cost_usd=fast;
                if(priority.present)unit->priority_period=unit->period;
                else {e=count_add(report,&report->priority_without_multiplier,normalized,unit->input);if(e.code)return e;}
            }
            continue;
        }
        int64_t at=unit->at_ms.value,cutoff=0,rates_clock=at;bool cutoff_present=cutoff_for(normalized,&cutoff);
        bool historical=cutoff_present&&unit->timestamp_ms.present&&unit->timestamp_ms.value<cutoff;
        if(cutoff_present&&!unit->timestamp_ms.present&&rates_clock<cutoff)rates_clock=cutoff;
        Str key={0};if(override&&!historical){e=override_key(report,index,raw,normalized,&key);if(e.code)return e;}
        if(key.p){HistoryPick pick=history_pick(history,key,rates_clock);if(pick.entry&&pick.before_first)key=(Str){0};}
        e=rates_at(report,history,index,key.p?key:normalized,key.p?raw:normalized,rates_clock,false,(PricePriority){0},&rates,&unit->period);if(e.code)return e;
        if(!rates){e=count_add(report,&report->unpriced,unit->model,unit->input+unit->output);if(e.code)return e;continue;}
        unit->has_cost=true;unit->cost_usd=cost_usd(rates,unit->input,unit->cached,unit->output);
        if(unit->priority_tier) {
            HistoryPick pick;e=picked(report,history,normalized,at,&pick);if(e.code)return e;
            if(pick.entry)priority=pick.entry->priority;
            if(pick.entry&&priority.present) {
                PricingPeriods *group;e=periods_for(report,normalized,&group);if(e.code)return e;
                unit->priority_period=(PricePeriod){true,group->key,pick.index};
            }
            double fast;if(priority_cost_usd(rates,&priority,unit->input,unit->cached,unit->output,&fast)&&fast>unit->cost_usd)unit->cost_usd=fast;
            else if(!priority.present){e=count_add(report,&report->priority_without_multiplier,normalized,unit->input);if(e.code)return e;}
        }
    }
    return ERR_SUCCESS;
}
Err price_units(Corpus *corpus,const PriceHistory *history,ModelsDevIndex *index,bool available,PricingReport *report) {
    Err e=pricing_report_init(history,report);if(e.code)return e;
    for(OmapEntry *entry=corpus->sessions.first;entry;entry=entry->next) {
        SessionModel *session=entry->value;e=price_usage_units(session->units,session->unit_count,history,index,available,report);if(e.code)return e;
    }
    pricing_report_note_sums(report);return ERR_SUCCESS;
}
void pricing_report_note_sums(const PricingReport *report) {
    const Omap *maps[]={&report->unpriced,&report->priority_without_multiplier,&report->untimed};
    const char *sites[]={"pricing.unpriced","pricing.priority_without_multiplier","pricing.untimed"};
    for(size_t i=0;i<3;i++)for(OmapEntry *entry=maps[i]->first;entry;entry=entry->next) {
        __int128 value=*(__int128 *)entry->value;if(value<INT64_MIN||value>INT64_MAX)event_note("int128_payload_sum",sites[i],1);
    }
}
static void policy_json(JsonWriter *w,PricePriority priority) {
    if(!priority.present){jsonw_raw(w,"null");return;}
    jsonw_raw(w,"{\"multiplier\":");if(priority.multiplier.is_float)jsonw_double(w,priority.multiplier.f);else jsonw_i64(w,priority.multiplier.i);
    jsonw_raw(w,",\"max_input_tokens\":");if(priority.capped)jsonw_i64(w,priority.cap);else jsonw_raw(w,"null");jsonw_raw(w,"}");
}
static void period_json(JsonWriter *w,const PricingPeriod *period) {
    jsonw_raw(w,"{\"effective_from_ms\":");
    if(period->history&&!period->history->null_time)jsonw_i64(w,period->history->effective_ms);else jsonw_raw(w,"null");
    jsonw_raw(w,",\"source\":");if(period->history)jsonw_value(w,get(period->history->value,"source"));else jsonw_string(w,STR_LIT("transient"));
    if(period->history) {
        jsonw_raw(w,",\"per_million\":");jsonw_value(w,get(period->history->value,"per_million"));
        jsonw_raw(w,",\"long_context\":");yyjson_val *extended=get(period->history->value,"long_context");if(extended)jsonw_value(w,extended);else jsonw_raw(w,"null");
    } else {
        jsonw_raw(w,",");price_entry_fields_json(w,&period->rates);
    }
    jsonw_raw(w,",\"priority\":");if(period->history&&period->history->has_priority)jsonw_value(w,get(period->history->value,"priority"));else policy_json(w,period->priority);
    jsonw_raw(w,"}");
}
static void count_map_json(JsonWriter *w,const Omap *map,bool clock) {
    jsonw_raw(w,"{");size_t i=0;for(OmapEntry *entry=map->first;entry;entry=entry->next){if(i++)jsonw_raw(w,",");jsonw_string(w,entry->key);jsonw_raw(w,":");if(clock)jsonw_i64(w,*(int64_t *)entry->value);else jsonw_i128(w,*(__int128 *)entry->value);}jsonw_raw(w,"}");
}
static int key_order(const void *a,const void *b,void *unused){(void)unused;return str_compare(*(const Str *)a,*(const Str *)b);}
static Str *sorted_keys(JsonWriter *w,const Omap *map) {
    if(map->size>SIZE_MAX/sizeof(Str)){w->error=err_make(ERR_NOMEM,"pricing key overflow");return NULL;}
    Str *keys=malloc((map->size?map->size:1)*sizeof *keys);if(!keys){w->error=err_make(ERR_NOMEM,"pricing key allocation");return NULL;}
    size_t n=0;for(OmapEntry *entry=map->first;entry;entry=entry->next)keys[n++]=entry->key;
    Err e=stable_sort(keys,n,sizeof *keys,key_order,NULL);if(e.code){w->error=e;free(keys);return NULL;}return keys;
}
void pricing_models_json(JsonWriter *w,const PricingReport *report) {
    Str *keys=sorted_keys(w,&report->periods);if(!keys)return;jsonw_raw(w,"{");
    for(size_t i=0;i<report->periods.size;i++){PricingPeriods *group=omap_get(&report->periods,keys[i]);if(i)jsonw_raw(w,",");jsonw_string(w,keys[i]);jsonw_raw(w,":{\"priced\":");jsonw_raw(w,group->count?"true":"false");jsonw_raw(w,",\"periods\":[");for(size_t j=0;j<group->count;j++){if(j)jsonw_raw(w,",");period_json(w,group->items[j]);}jsonw_raw(w,"]}");}jsonw_raw(w,"}");free(keys);
}
void pricing_diagnostic_json(JsonWriter *w,const Omap *map,const char *field,bool clock,bool keys_only) {
    Str *keys=sorted_keys(w,map);if(!keys)return;jsonw_raw(w,"[");
    for(size_t i=0;i<map->size;i++){if(i)jsonw_raw(w,",");if(keys_only){jsonw_string(w,keys[i]);continue;}jsonw_raw(w,"{\"model\":");jsonw_string(w,keys[i]);jsonw_raw(w,",");jsonw_string(w,(Str){field,(uint32_t)strlen(field)});jsonw_raw(w,":");void *value=omap_get(map,keys[i]);if(clock)jsonw_i64(w,*(int64_t *)value);else jsonw_i128(w,*(__int128 *)value);jsonw_raw(w,"}");}jsonw_raw(w,"]");free(keys);
}
void pricing_report_json(JsonWriter *w,const PricingReport *report) {
    jsonw_raw(w,"{\"periods\":{");size_t n=0;
    for(OmapEntry *entry=report->periods.first;entry;entry=entry->next){if(n++)jsonw_raw(w,",");jsonw_string(w,entry->key);jsonw_raw(w,":[");PricingPeriods *group=entry->value;for(size_t i=0;i<group->count;i++){if(i)jsonw_raw(w,",");period_json(w,group->items[i]);}jsonw_raw(w,"]");}
    jsonw_raw(w,"},\"unpriced\":");count_map_json(w,&report->unpriced,false);
    jsonw_raw(w,",\"history_begins\":");count_map_json(w,&report->history_begins,true);
    jsonw_raw(w,",\"priority_without_multiplier\":");count_map_json(w,&report->priority_without_multiplier,false);
    jsonw_raw(w,",\"unrecorded\":[");
    if(report->unrecorded.size>SIZE_MAX/sizeof(Str)){w->error=err_make(ERR_NOMEM,"pricing key overflow");return;}
    Str *keys=malloc((report->unrecorded.size?report->unrecorded.size:1)*sizeof *keys);
    if(!keys){w->error=err_make(ERR_NOMEM,"pricing key allocation");return;}
    n=0;for(OmapEntry *entry=report->unrecorded.first;entry;entry=entry->next)keys[n++]=entry->key;
    Err e=stable_sort(keys,n,sizeof *keys,key_order,NULL);if(e.code)w->error=e;
    for(size_t i=0;i<n;i++){if(i)jsonw_raw(w,",");jsonw_string(w,keys[i]);}free(keys);
    jsonw_raw(w,"],\"untimed\":");count_map_json(w,&report->untimed,false);jsonw_raw(w,"}");
}
void pricing_report_destroy(PricingReport *report) {
    for(OmapEntry *entry=report->periods.first;entry;entry=entry->next){PricingPeriods *group=entry->value;free(group->items);}
    omap_destroy(&report->periods);omap_destroy(&report->unpriced);omap_destroy(&report->history_begins);omap_destroy(&report->priority_without_multiplier);omap_destroy(&report->unrecorded);omap_destroy(&report->untimed);arena_destroy(&report->arena);*report=(PricingReport){0};
}
static Err recording_add(Omap *models,Arena *arena,Str key,Str source) {
    Str *copy;Err e=arena_alloc(arena,sizeof *copy,_Alignof(Str),(void **)&copy);if(e.code)return e;
    *copy=source;return omap_put(models,key,copy);
}
static Err recording_record(Omap *models,Arena *arena,const LogRecord *record) {
    for(size_t i=0;i<record->token_stream.count;i++) {
        const TokenObservation *observation=&record->token_stream.observations[i];Str raw={0};
        if(observation->tag==TOKEN_C||observation->tag==TOKEN_XC) {
            if(observation->model_state.kind==MODEL_SET)raw=observation->model_state.model;
        } else if(observation->tag==TOKEN_T||observation->tag==TOKEN_B)raw=observation->model;
        if(raw.p) {Str normalized=normalize_codex_model(raw);if(!str_equal(normalized,STR_LIT("unknown"))){Err e=recording_add(models,arena,normalized,normalized);if(e.code)return e;}}
    }
    return ERR_SUCCESS;
}
Err pricing_recording_models(const Corpus *corpus,const PriorityTurns *priority,ModelsDevIndex *index,yyjson_doc **out) {
    *out=NULL;Omap models={0};PricingReport owner={0};yyjson_mut_doc *doc=NULL;Err error=ERR_SUCCESS;
    for(OmapEntry *entry=corpus->sessions.first;entry;entry=entry->next) {
        const SessionModel *session=entry->value;for(size_t i=0;i<session->record_count;i++){error=recording_record(&models,&owner.arena,session->records[i]);if(error.code)goto done;}
    }
    for(size_t i=0;i<corpus->skipped_count;i++){error=recording_record(&models,&owner.arena,corpus->skipped[i]);if(error.code)goto done;}
    for(OmapEntry *entry=priority->turns.first;entry;entry=entry->next) {
        const PriorityEntry *metadata=entry->value;Str raw=metadata->model;
        if(!raw.p||!codex_api_fast_multiplier(raw))continue;
        Str normalized=normalize_codex_model(raw);error=recording_add(&models,&owner.arena,normalized,normalized);if(error.code)goto done;
        Str key;error=override_key(&owner,index,raw,normalized,&key);if(error.code)goto done;
        if(key.p){error=recording_add(&models,&owner.arena,key,raw);if(error.code)goto done;}
    }
    doc=yyjson_mut_doc_new(NULL);if(!doc){error=err_make(ERR_NOMEM,"recording models allocation");goto done;}
    yyjson_mut_val *root=yyjson_mut_obj(doc);yyjson_mut_doc_set_root(doc,root);if(!root){error=err_make(ERR_NOMEM,"recording models allocation");goto done;}
    for(OmapEntry *entry=models.first;entry;entry=entry->next) {
        Str source=*(Str *)entry->value;yyjson_mut_val *key=yyjson_mut_strncpy(doc,entry->key.p,entry->key.n),*value=yyjson_mut_strncpy(doc,source.p,source.n);
        if(!key||!value||!yyjson_mut_obj_add(root,key,value)){error=err_make(ERR_NOMEM,"recording models allocation");goto done;}
    }
    error=json_freeze(doc,out);
done:
    yyjson_mut_doc_free(doc);omap_destroy(&models);pricing_report_destroy(&owner);return error;
}
