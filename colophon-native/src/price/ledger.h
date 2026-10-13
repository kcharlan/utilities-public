#ifndef CP_PRICE_LEDGER_H
#define CP_PRICE_LEDGER_H
#include "catalog.h"
typedef struct { Str *items; size_t count,capacity; } PriceMessages;
typedef struct {
    Arena arena;
    yyjson_val **entries;
    size_t count,capacity;
    PriceMessages errors,warnings;
    Omap numeric_tickets; /* Pointer keys borrow this validation's input only. */
    Err numeric_error;
} LedgerCheck;
/* Validation entries borrow input. Message bytes belong to check.arena.
 * Caller retains input through consumption and always destroys the check. */
Err validate_ledger(yyjson_val *document,bool curated,LedgerCheck *out);
void ledger_check_destroy(LedgerCheck *check);
void ledger_check_json(JsonWriter *writer,const LedgerCheck *check);
bool ledger_json_equal(yyjson_val *left,yyjson_val *right,bool omit_notes);
typedef struct {
    yyjson_val *value;
    PriceEntry rates;
    PricePriority priority;
    bool null_time,has_priority;
    int64_t effective_ms;
    unsigned rank;
} HistoryEntry;
typedef struct { Str key;HistoryEntry **entries;size_t count,capacity; } HistoryGroup;
typedef struct {Arena arena;Omap groups;yyjson_doc *curated,*user;} PriceHistory;
typedef struct {const HistoryEntry *entry;size_t index;bool before_first;} HistoryPick;
Err price_history(yyjson_val *curated,yyjson_val *user,PriceHistory *out);
const HistoryGroup *history_entries_for(const PriceHistory *history,Str model);
bool history_has_any(const PriceHistory *history,Str model);
HistoryPick history_pick(const PriceHistory *history,Str model,int64_t at_ms);
void history_destroy(PriceHistory *history);
void history_entries_json(JsonWriter *writer,const HistoryGroup *group);
void history_pick_json(JsonWriter *writer,HistoryPick pick);
Err record_catalog_rates(const PriceHistory *history,ModelsDevIndex *index,
                         int64_t fetched_at_ms,yyjson_val *recording_ids,int64_t now_ms,
                         yyjson_doc **out);
typedef struct {Arena arena;bool appended;Str warning;} LedgerAppend;
Err append_user_ledger(const char *path,yyjson_val *new_entries,bool start_present,
                       int64_t start_mtime_ns,LedgerAppend *out);
void ledger_append_destroy(LedgerAppend *append);
typedef struct LedgerDiagnostic {Str level,message;struct LedgerDiagnostic *next;} LedgerDiagnostic;
typedef struct {
    Arena arena;
    yyjson_doc *curated,*document,*entries;
    LedgerCheck check;
    Str reason;
    LedgerDiagnostic *diagnostics,*last;
    bool available;
} RuntimeLedger;
/* Owns generic dictionary entries and diagnostic text until payload/summary
 * rendering finishes. Load parses runtime bytes once with constant rejection. */
Err runtime_ledger_load(const char *path,RuntimeLedger *out);
Err runtime_ledger_history(const RuntimeLedger *ledger,yyjson_val *new_entries,PriceHistory *out);
Err runtime_ledger_warning(RuntimeLedger *ledger,const char *path,Str warning);
void runtime_ledger_json(JsonWriter *writer,const RuntimeLedger *ledger);
void runtime_ledger_destroy(RuntimeLedger *ledger);
#endif
