#ifndef CP_CLAUDE_PARSE_H
#define CP_CLAUDE_PARSE_H
#include "corpus/assemble.h"
/* Separate record ownership: never masquerades as a Codex LogRecord. */
typedef struct {
  Arena arena;
  DiscoveredLog key;
  Str id, search_root, config_dir, parent_session;
  SessionMeta meta;
  CorpusStrings aliases;
  ReaderResult reader;
  TurnFact **turns;
  Request *requests;
  Str *answers;
  CorpusTools *tools;
  size_t turn_count;
  MaybeMs first_ms, last_ms;
} ClaudeRecord;
bool claude_known_type(Str kind);
Err claude_parse(const DiscoveredLog *key, Str root, Str config,
                 ClaudeRecord *out);
void claude_record_destroy(ClaudeRecord *record);
Err claude_corpus_add(ClaudeRecord *records, size_t count, int64_t snapshot,
                      Corpus *corpus, CorpusStrings *collisions);
#endif
