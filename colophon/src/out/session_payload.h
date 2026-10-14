#ifndef CP_SESSION_PAYLOAD_H
#define CP_SESSION_PAYLOAD_H
#include "corpus/assemble.h"
#include "jsonw.h"
typedef struct { Arena arena; Omap ids; } PayloadIds;
Err payload_ids_init(const Corpus *corpus,const char *codex_home,PayloadIds *out);
void payload_ids_destroy(PayloadIds *ids);
void payload_reference(JsonWriter *w,const PayloadIds *ids,Str id);
void payload_references(JsonWriter *w,const PayloadIds *ids,const CorpusStrings *strings);
void payload_sessions(JsonWriter *w, const Corpus *corpus,
                      const PayloadIds *ids);
void payload_subagents(JsonWriter *w, const Corpus *corpus,
                       const PayloadIds *ids);
void payload_file_diagnostic(JsonWriter *w, const FileDiagnostic *diagnostic);
void payload_unknown_types(JsonWriter *w, const Corpus *corpus);
void payload_corpus_strings(JsonWriter *w, const CorpusStrings *strings);
void payload_workspaces(JsonWriter *w, const Corpus *corpus);
void payload_corpus_tools(JsonWriter *w, const CorpusTools *tools);
void payload_corpus_flags(JsonWriter *w, unsigned flags, bool turn);
/* A NULL writer counts the same selected history rows for CLI diagnostics. */
size_t payload_unresolved_history(JsonWriter *w,const Corpus *corpus,const PayloadIds *ids);
#endif
