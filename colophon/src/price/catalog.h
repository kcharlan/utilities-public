#ifndef CP_PRICE_CATALOG_H
#define CP_PRICE_CATALOG_H
#include "cost.h"
#include "model.h"
#include "util/omap.h"
#include "out/jsonw.h"
typedef struct {
    Str model_id;
    double rates[4], extended[4];
    uint8_t present, extended_present;
    bool has_extended;
    bool has_context_tier;
    int64_t context_tier_size;
} CatalogModel;
typedef struct { Arena arena; Omap models, normalized, lookups, normalizations, claude_providers; } ModelsDevIndex;
typedef struct { const CatalogModel *model; Str identity; } CatalogLookup;
Err models_dev_index(yyjson_val *catalog,ModelsDevIndex *out);
Err models_dev_pricing(ModelsDevIndex *index,Str provider,Str raw,CatalogLookup *out);
Err claude_catalog_pricing(ModelsDevIndex *index,Str provider,Str raw,CatalogLookup *out);
/* Interned result is borrowed until index destruction; raw keys remain distinct. */
Err models_dev_normalize(ModelsDevIndex *index,Str raw,Str *out);
void models_dev_destroy(ModelsDevIndex *index);
void catalog_lookup_json(JsonWriter *writer,const CatalogLookup *lookup);
typedef struct { Str model[2]; size_t count; } PricingTargets;
Err codex_models_dev_pricing_targets(Arena *arena,Str raw,PricingTargets *out);
Err resolve_rates(Str raw,ModelsDevIndex *index,PriceEntry *out,bool *found);
void price_entry_json(JsonWriter *writer,const PriceEntry *entry);
void price_entry_fields_json(JsonWriter *writer,const PriceEntry *entry);
/* Sole raw catalog decoder. Invalid input yields *out=NULL without a fatal
 * error; allocation failures propagate. Result owns all bytes independently.
 * Safe for a 512KiB fetch thread; no index/history state is shared. */
Err catalog_decode(Str raw,yyjson_doc **out);
typedef struct CatalogMessage {Str text;struct CatalogMessage *next;} CatalogMessage;
typedef struct {
    Arena arena;
    yyjson_doc *artifact,*catalog;
    Str url,etag;
    bool has_etag,has_fetched_at,has_checked_at;
    int64_t fetched_at_ms,checked_at_ms;
    const char *status;
    CatalogMessage *messages,*last_message;
} CatalogResult;
/* Offline cache loader reads original bytes once through the sole raw decoder.
 * Artifact retains URL/ETag strings; sanitized catalog has an independent owner.
 * Caller always destroys, even after failures, after index/render consumption. */
Err catalog_load_offline(const char *path,Str configured_url,CatalogResult *out);
void catalog_result_json(JsonWriter *writer,const CatalogResult *result);
void catalog_result_destroy(CatalogResult *result);
/* Thread owns URL/path, response bytes and result until finish/cancel joins it.
 * cancel serializes with cache commit before returning; no subsequent writes.
 * finish waits connect+body+5 seconds, cancels on expiry, joins then loads cache.
 * A finished result is transferred to the caller, which always destroys it. */
typedef struct CatalogFetch CatalogFetch;
Err catalog_fetch_start(const char *path,Str url,bool offline,bool refresh,int64_t now_ms,CatalogFetch **out);
Err catalog_fetch_finish(CatalogFetch **fetch,CatalogResult *out);
void catalog_fetch_cancel(CatalogFetch **fetch);
#endif
