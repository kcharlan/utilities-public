#ifndef CP_ASSEMBLE_H
#define CP_ASSEMBLE_H
#include "meta/metadata.h"
#include "model/logrecord.h"

enum {
  F_NO_META = 1u,
  F_COLLAPSED = 2u,
  F_HISTORY = 4u,
  F_LIVE = 8u,
  F_ABORTED = 16u,
  F_INTERRUPTED = 32u,
  F_ABANDONED = 64u,
  F_UNCERTAIN = 128u,
  F_UNKNOWN = 256u,
  F_REPORTED = 512u,
  F_START_COMPLETION = 1024u,
  F_ORPHAN = 2048u,
  F_FORKED = 4096u,
  F_FORK_BASELINE = 8192u,
  F_RETAINED = 16384u
};
typedef struct {
  Str *items;
  size_t count, capacity;
} CorpusStrings;
typedef struct {
  __int128 shell, shell_failed, file_edits, web, image;
  /* Aggregate map values are arena-owned signed __int128. */
  Omap mcp, other;
} CorpusTools;
typedef struct {
  MaybeMs at_ms;
  Str text, kind;
  uint64_t images;
  bool before_turn, time_unreliable;
  const VoiceRequest *voice;
} Request;
typedef struct {
  Str id, status;
  size_t n;
  MaybeNum start_ms, end_ms, duration_ms, ttft_ms;
  unsigned flags;
  Request **requests;
  size_t request_count;
  Str final_answer;
  bool final_voice;
  struct UsageSummary *usage;
  CorpusTools tools;
  VoiceReply *voice_replies;
  size_t voice_reply_count;
  CorpusStrings spawned, used;
} TurnModel;
typedef struct {
  const LogRecord *record;
  JScalar meta_id;
  bool typed_clocks;
  JScalar creation;
  const JScalar *spawn_clocks;
  size_t spawn_clock_count;
} AssemblyRecord;
/* Production descriptors borrow canonical facts. Typed overrides borrow the
 * record arena; each spawn clock corresponds to one raw spawn in order. */
AssemblyRecord assembly_record(const LogRecord *record);
typedef enum { PROVIDER_CODEX, PROVIDER_CLAUDE, PROVIDER_OPENCODE, PROVIDER_ANTIGRAVITY } Provider;
typedef struct {
  Str id, key, identity, title, title_full, title_source;
  Provider provider;
  bool history_only;
  Str resume_config_dir;
  Str opencode_database; /* Borrowed absolute source path, OpenCode only. */
  const LogRecord *record;
  const LogRecord **records;
  size_t record_count, record_capacity;
  TurnModel *turns;
  size_t turn_count;
  unsigned flags;
  Request *requests;
  size_t request_count;
  Request **ordered_requests;
  Request **voice_requests;
  size_t voice_request_count;
  VoiceReply *voice_replies;
  size_t voice_reply_count;
  CorpusTools tools;
  MaybeMs start_ms, end_ms, user_span_ms;
  MaybeNum idle_ms;
  const MetadataThread *db_info;
  JScalar meta_id;
  const AssemblyRecord *input;
  bool archived, has_meta, is_subagent, has_link;
  Str archive_reason; /* Corpus-arena owned; empty for existing providers. */
  Str log_path;
  SessionMeta meta;
  AssemblyRecord meta_input;
  Str kind, parent_id, agent_path, forked_from, spawn_turn, link_method;
  Str agent_label;
  Str workspace, subfolder;
  MaybeNum created_at_ms;
  bool has_depth;
  __int128 depth;
  CorpusStrings children, interaction_turns;
  size_t graph_visit, graph_position;
  struct UsageUnit *units;
  size_t unit_count, unit_capacity;
  struct UsageSummary *own_usage, *outside_usage;
  struct UsageBucket *buckets;
  size_t bucket_count;
} SessionModel;
typedef struct {
  Str path;
  uint64_t count;
} DiagnosticFile;
typedef struct {
  __int128 total;
  DiagnosticFile *files;
  size_t count;
} FileDiagnostic;
typedef struct { Str path, reason; } SkippedFile;
typedef struct {
  Arena arena;
  Omap sessions, unknown_types;
  AssemblyRecord *inputs;
  size_t input_count;
  const LogRecord **skipped;
  size_t skipped_count;
  SkippedFile *skipped_files;
  size_t skipped_file_count;
  FileDiagnostic malformed, truncated, recovered;
  size_t db_threads_without_logs;
  CorpusStrings orphaned_subagents, inferred_links;
  CorpusStrings claude_orphaned_subagents;
  Omap workspaces;
  bool linked;
  Arena usage_arena;
  CorpusStrings trace_messages, fork_baselines;
  Omap duplicate_ids; /* Raw diagnostic id -> usage-arena CorpusStrings. */
  CorpusStrings duplicate_order;
  unsigned char diagnostic_order[7];
  size_t diagnostic_order_count;
  bool composed;
} Corpus;
/* Corpus owns derived arrays, map nodes and tool maps; raw record and metadata
 * facts are borrowed until teardown. Intern must outlive every corpus string.
 */
Err corpus_build(const AssemblyRecord *records, size_t count,
                 const CodexMetadata *metadata, int64_t snapshot_ms,
                 Intern *intern, Corpus *out);
void corpus_destroy(Corpus *corpus);
Err corpus_tool_merge(Arena *arena, CorpusTools *out, const ToolCounts *source);
bool corpus_quiet(int64_t snapshot_ms, int64_t mtime_ms);
#endif
