#ifndef CP_CLAUDE_PARSE_H
#define CP_CLAUDE_PARSE_H
#include "corpus/assemble.h"
#include "price/compose.h"
typedef struct {
  UsageUnit unit;
  Str message_id, request_id, session_id;
  bool incomplete, sidechain, subagent;
} ClaudeUsageRow;
typedef struct {
  Str turn, id, name;
  bool identified, failed;
} ClaudeToolFact;
/* Separate record ownership: never masquerades as a Codex LogRecord. */
typedef struct {
  Arena arena;
  DiscoveredLog key;
  Str id, search_root, config_dir, parent_session;
  Str parent_agent, tool_use_id, description, agent_type;
  Str custom_title, ai_title;
  bool retained; /* Runtime lifecycle; not part of immutable record facts. */
  bool has_spawn_depth;
  int64_t spawn_depth;
  Omap tool_turns; /* record-arena tool_use ID -> turn key */
  Omap canonical_turns; /* Runtime only: local key -> corpus-owned display key. */
  SessionMeta meta;
  CorpusStrings aliases;
  ReaderResult reader;
  TurnFact **turns;
  Request *requests;
  Str *answers;
  MaybeMs *answer_ms;
  CorpusTools *tools;
  size_t turn_count;
  bool reader_facts; /* CLCD2 tool identities and answer clocks are available. */
  size_t reader_copies; /* Temporary reader view only; never persisted. */
  ClaudeToolFact *tool_facts;
  size_t tool_count, tool_capacity;
  MaybeMs first_ms, last_ms;
  ClaudeUsageRow *usage_rows;
  size_t usage_count, usage_capacity;
  Omap rows_dropped; /* record-arena uint64_t values */
} ClaudeRecord;
Err claude_tool_count(Arena *arena, CorpusTools *tools, Str name, bool failed);
bool claude_known_type(Str kind);
Err claude_parse(const DiscoveredLog *key, Str root, Str config,
                 ClaudeRecord *out);
void claude_record_destroy(ClaudeRecord *record);
Err claude_corpus_add(ClaudeRecord *records, size_t count, int64_t snapshot,
                      Corpus *corpus, CorpusStrings *collisions);
#endif
