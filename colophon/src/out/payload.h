#ifndef CP_PAYLOAD_H
#define CP_PAYLOAD_H
#include "jsonw.h"
#include "scan/scan.h"
#include "corpus/assemble.h"
#include "price/pricing.h"
#include "claude/scan.h"
#include "opencode/db.h"
/* Borrowed typed product owners; each remains live through rendering. */
typedef struct {
    int64_t snapshot_ms;
    const char *codex_home,*source_host,*timezone;
    size_t page_size;
    bool over_limit;
    size_t logs,parsed,cached;
    const ScanResult *scan;
    const Corpus *corpus;
    const CodexMetadata *metadata;
    const char *source_codex_home;
    const CorpusStrings *workspace_errors;
    const PricingReport *pricing;
    const CatalogResult *catalog;
    const RuntimeLedger *ledger;
    bool codex_present;
    const ClaudeScan *claude;
    const OpencodeStore *opencode;
} PayloadInputs;
void payload_empty(JsonWriter *w,const PayloadInputs *inputs);
#endif
