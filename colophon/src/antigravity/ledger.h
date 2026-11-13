#ifndef CP_ANTIGRAVITY_LEDGER_H
#define CP_ANTIGRAVITY_LEDGER_H
#include "db.h"
#include "price/compose.h"

typedef struct {
    size_t order;
    uint64_t tokens[6];
    bool reasoning,step_clock;
    MaybeMs at_ms;
    Str model_raw,ids[3];
    const char *model_source;
    int64_t model_number;
    bool has_model_number;
} AntigravityLedgerEvent;
typedef struct {
    SessionModel header;
    AntigravityLedgerEvent *events;
    size_t event_count,event_capacity,previous_count;
    bool retained,unreadable,live;
    Str path,original;
    int64_t source_size,source_mtime_ns;
} AntigravityLedgerRecord;
typedef struct AntigravityLedger {
    Arena arena;
    AntigravityLedgerRecord **records;
    size_t count,capacity;
    Omap by_id;
    char *directory;
} AntigravityLedger;
Err antigravity_ledger_load(const char *runtime_home,AntigravityStore *store,AntigravityLedger *out);
bool antigravity_ledger_present(const AntigravityLedger *ledger);
Err antigravity_ledger_corpus_add(AntigravityLedger *ledger,AntigravityStore *store,Corpus *corpus);
Err antigravity_ledger_begin(AntigravityLedger *ledger,SessionModel *session,const AntigravitySession *source);
Err antigravity_ledger_capture(AntigravityLedger *ledger,SessionModel *session,AntigravityLedgerEvent event);
Err antigravity_ledger_commit(AntigravityLedger *ledger,const AntigravityStore *store,const Corpus *corpus,volatile sig_atomic_t *interrupted);
void antigravity_ledger_destroy(AntigravityLedger *ledger);
#endif
