# Telltale: Claude provider design

Status: **approved by Kevin**, 2026-10-28. Base documents:
[design spec](telltale_design_spec.md) (approved 2026-10-27, "the spec"),
[visual design](telltale_visual_design.md). Section references (§n) point into the spec unless
they say "this doc".

Decisions marked **(my call)** were made by the author of this document, not by Kevin. Kevin's
decisions are listed in this doc §12. Everything else follows the spec's own
decisions, applied to Claude.

## 1. Intent

Kevin runs Claude Code agents alongside Codex. The spec's two questions apply unchanged:

1. **Is something off?** Claude is slower or faster than usual, failing, or retrying.
2. **Is it them or me?** Anthropic's service, or Kevin's own workload or configuration.

The spec already defines Claude as a later plugin (§2 goals, §5 notes: Claude Code transcripts
under `~/.claude/projects` and status.claude.com). This document turns that note into a design,
grounded in transcript format analysis and the Claude status page (this doc §3). The intent of the Codex design carries over:

- Size- and mode-adjusted speed against a usual that never adapts silently (§8).
- Alert within about 15 minutes; one notification per episode; no flapping (§7.2).
- A durable record of failures, retries, provider incidents and baseline changes.
- Metadata only; never prompt or response content (§2 anti-goals, §11).
- Plugins are compiled in and registered in one list (§5).

## 2. Goals, non-goals, anti-goals

**Goals**

- A Claude usage source and a Claude status source that snap into the existing collector, rule
  engine, store and UI, with the smallest set of core changes the analysis shows are needed
  (this doc §4).
- Claude models appear in the sidebar and panel beside Codex's, with their own usual, episodes,
  lasting-shift prompts and acceptances.
- Claude failures and retries feed the Errors and Link lamps; Claude Code and model status
  incidents feed the Provider lamp; context compactions feed the Load lamp.

**Non-goals (for now)**

- Claude usage-limit percentages. Claude Code's transcripts record the limit only when a
  request is rejected (§5.6 of this doc). Reading Anthropic's usage API needs the OAuth token,
  which is a credential and a network call to something other than a status page.
- Time-to-first-token as a rule. The transcripts allow a rough proxy (this doc §3.2); it is not
  a signal in this release.
- Claude.ai web or desktop chat outside Claude Code, the Claude API used by Kevin's own scripts
  outside Claude Code, Cowork.
- Cost or token accounting (Colophon and CodexBar do that).

**Anti-goals** (the spec's, plus two Claude-specific ones)

- **Noise.** In particular: a persistently lit Load lamp, and incident notifications
  for models Kevin isn't using or for connector outages (this doc §3.4, §3.6).
- **Blaming Anthropic for Kevin's own errors.** A 404 for an invalid model id in headless tooling, or a plan's 5-hour limit, must never light Errors red as a provider failure.
- **Reading content.** Claude Code transcripts hold full prompts, tool inputs, tool outputs and
  thinking in the same lines as the metadata. The parser must reach only the fields in this doc
  §5.3 and §5.9 and discard each line.
- **Holding files open or locking them.** Transcripts are plain append-only files; reads are
  plain reads.

## 3. Format and design evidence

This section records format facts and design implications, not personal usage measurements.
Any examples elsewhere in this document are invented examples, not observations.

### 3.1 What the transcripts record

One JSONL file per session (`<project-dir>/<session-uuid>.jsonl`), and one per subagent
(`<project-dir>/<session-uuid>/subagents/agent-<id>.jsonl`, with `isSidechain: true` and
`agentId`). Relevant line types:

| Line | Fields used | Notes |
|---|---|---|
| `assistant` | `timestamp`, `message.id`, `message.model`, `message.usage.*`, `effort`, `isSidechain`, `version`, `requestId` | One line per content block, sharing message and request identifiers. |
| `user` | `timestamp` only | Prompts, tool results and meta lines are input events for the start rule. |
| `system` `subtype: "api_error"` | `timestamp`, `retryAttempt`, `maxRetries`, `retryInMs`, `error.status` | One line per retry. |
| `assistant` with `isApiErrorMessage: true` | `timestamp`, `error`, `apiErrorStatus`, `quotaLimits` | A terminal failure; `message.model` is `<synthetic>`. |
| `api-request` | `timestamp`, `id` (= `requestRef` on assistant lines) | Available in newer versions. Its `params`/`tail` contain request content and are not used. |

`message.usage` holds `input_tokens` (uncached), `cache_creation_input_tokens`,
`cache_read_input_tokens`, `output_tokens` (including thinking),
`output_tokens_details.thinking_tokens` (newer versions), `service_tier`, `speed`
(`standard` or `fast`, absent in older versions), and `inference_geo`. The top-level
`effort` can be `low`, `medium`, `high`, `xhigh`, or `max`, and can be absent.

Earlier lines can have partial output totals; use the largest. Tool-result lines can interleave
between blocks of a response, and `stop_reason` can be null throughout, so a different line type
is not a completion marker. Resumed or forked sessions and copied subagent history can duplicate
messages across files. Claude transcripts are plain JSONL rather than Codex's compressed rollouts
or SQLite logs.

Colophon, CodexBar and ccusage scan project JSONL files including subagents, deduplicate using
message and request identity, and distinguish uncached input from cache reads and writes. Fast
mode is `usage.speed == "fast"`; advisor sub-usage can appear as `usage.iterations[]` entries
of type `advisor_message`. `CLAUDE_CONFIG_DIR` interpretation differs among readers; this design
specifies its own handling in §5.1. Parse ISO 8601 timestamps with and without fractional seconds;
unknown token components stay unknown rather than zero.

### 3.2 Response start and first-block timing

Use the spec's start rule: the latest input event after the preceding response, or that response's
end when no such input exists. The `api-request` timestamp offers a cross-check where present, but
its content-bearing fields are not needed. A first-block timestamp is completion of that block,
not time to first token, and is not used as TTFT.

### 3.3 Usual speed

Throughput is output tokens divided by elapsed time, with the spec's 300-token minimum. Keep the
model, effort, service tier and input bucket in the baseline key; output length can affect measured
throughput, and sparse models may not have enough samples. Do not add a time-of-day key.

### 3.4 Anomalies and error classification

Replay privately to assess rule behavior (§10). Speed swings need not coincide with a published
incident. Classify overload and server failures as provider-side; a plan limit or invalid model
identifier is not a provider failure. The defaults remain those of the spec.

### 3.5 Prompt sizes and the Load lamp

A large prompt alone is not a sufficiently reliable Claude load signal for this design. Keep
prompt-size charts, but use compaction for Claude's Load lamp (§3.7, §7.3 and §12).

### 3.6 The status page

status.claude.com is an Atlassian Statuspage (page id `tymt9n04zgry`) with components for
claude.ai, Claude Console, Claude API, Claude Code, Claude Cowork and Claude for Government.
Model incidents may list several components, and connector incidents may list Claude Code.
Titles can name several versions of a family: `Fable 5` must not match only `Fable 5.1`.
Impact statuses include `degraded_performance`, `partial_outage`, and `major_outage`;
normalize `major_outage` for Telltale's severity ranking. Some incident updates omit
`affected_components` and need the fallback described in §6.1.

### 3.7 What shows load or stress for Claude

Context compaction can discard session context and can block a session. Claude Code records it
as a `system` line, `subtype: "compact_boundary"`, with
`compactMetadata.{trigger, preTokens, postTokens, durationMs, precomputed}`. Trigger is `auto`
or `manual`; `content` is a summary and is never read. Precomputed compaction may avoid a stall
but still removes context. The threshold can change; use the observed recent median (§7.3), not
a hard-coded threshold. Compactions are the input for Claude's Load lamp (§7.3).

## 4. Integration changes

The gaps in the following table describe the 0.1.1 starting point, not current
behavior. The changes in its final column are implemented contracts.

The plugin interface (§5, `Sources/TelltaleCore/Plugins.swift`) fits Claude without change:
`UsageSource.ingest(cursor:backfillFrom:now:)` returning `IngestBatch` and an opaque cursor, and
`StatusSource.fetch(known:)` returning components and incidents. Records (`ResponseRecord`,
`FailedTurnRecord`, `ConnectionEventRecord`, `UsageLimitSnapshot`) carry everything Claude
provides. The store keys every table by provider (`Schema.swift`); baselines, epochs, episodes
and acceptances are per provider and model; the panel already merges lamps across providers and
captions the Provider lamp "Status" when there are two status sources (`PanelSnapshot.labels`).
The incident rule already pairs each status source with its usage providers
(`RuleStatusSource.providers`) and asks each provider's `ModelNaming` about titles. The schema
needs a migration only for the compactions table Kevin added to this release (G8).

The integration adds two targets (§5–§6 of this doc) to
`Sources/Telltale/Registry.swift`, with distinct ids for the usage source (`claude`) and the
status source (`anthropic`; §5 of this doc says why). Six original core gaps (G1–G6),
and two changes for incidents and the Load lamp (G7, G8), are recorded here:

| # | Gap | Where | Change |
|---|---|---|---|
| G1 | **A new source joining an existing database is never backfilled.** Evaluation progress is one global point (`Store.lastEvaluatedPoint`, rule state `provider "*"`). Claude's 30 days of responses would be ingested, but no points, episodes or flagged exclusions would exist before the day it was added, so earlier anomalies would enter usual unflagged, and the speed chart would be blank before that day. Worse, failed turns are counted at the first point evaluated after their time however late they were ingested (`RuleEngine` failed-turn pass; `Store+Rules` `evaluated_at`), so the first live run would post every provider-side Claude failure of the past 30 days as one "Failed turns" notification. | `RuleEngine.evaluate`, `Store+Rules.swift`, `CollectorRun` | Decided (§12 of this doc): evaluation progress per evaluation unit. Each usage provider is a unit (speed, failed turns, disconnects, its Load rules); each status source is its own unit (the incident rule), so a page later shared with Cowork (§8.2 of this doc) keeps one history. A unit with no progress is backfilled without notifying, once its source is ready. |
| G2 | **Rules ignore declared signals.** The panel hides episodes for signals a source doesn't declare (`PanelSnapshot`, line 163), but `RuleEngine` evaluates speed and large-prompt rules for every provider and posts their notifications. | `RuleEngine.evaluate(…providers:…)` | Pass each provider's declared signals and the rules its source supports (`UsageSource.supportedRules`, default every rule but `.compactions`; Claude's is every rule but `.largePrompts`, §7.3 of this doc); run a rule only when it is supported and its lamp is declared (large prompts and compactions ↔ `.load`, speed ↔ `.speed`, failed turns ↔ `.errors`, disconnects ↔ `.link`). |
| G3 | **Codex wording in shared copy.** `Copy.formatProblem` says "Codex changed its log format", Settings says "Rebuild from Codex logs…" | `Copy.swift`, `SettingsView.swift`, `CollectorRun` log line | Name the source: "Claude Code changed its log format. Telltale can't read Claude Code responses since 09:12." "Rebuild from provider logs…" **(my call)**. `CollectorHealth` already has the source row; pass its display name. |
| G4 | **One provider's paths in `TelltalePaths`.** Only `codexHome`. | `Paths.swift`, `Registry.swift` | Add `claudeHome`: `CLAUDE_CONFIG_DIR` when set and non-empty, else `~/.claude`, mirroring the `CODEX_HOME` handling. Tests inject it like `codexHome`. |
| G5 | **Shared status plumbing lives in the OpenAI plugin.** `HTTPTransport`, `URLSessionTransport`, the RSS parser (`RSSFallback.swift`, `StatusDecoding.rss`) and `StatusError` are in `TelltaleOpenAIStatus`; a second status source would either depend on that plugin or copy them. | `TelltaleOpenAIStatus/StatusClient.swift`, `RSSFallback.swift`, `StatusDecoding.swift` | Move them to `TelltaleCore` (or a small shared target) unchanged (no duplicate logic). |
| G6 | **Notifications assume one provider.** Panel alerts name the provider, but notification titles and bodies (`NotificationPolicy`, `Copy` for failed turns, disconnects, large prompts and usage limit) and Events don't. Failed-turn coalescing is one global state (`Store.failureNotices`, provider `"*"`), so a Codex and a Claude failure 10 minutes apart would merge into "2 turns failed: …" with no provider. `Copy.failedTurnReason(code:)` maps only Codex's codes. | `NotificationPolicy.swift`, `Copy.swift`, `Store+Rules.swift`, `EventFeed.swift` | Coalesce failed turns per provider **(my call)**. Name the provider in every provider-scoped notification and event ("Claude Code: 2 requests failed: model overloaded"; "Codex: 2 turns failed: model at capacity"), which also changes Codex's existing wording **(my call)**. Add Claude's codes to `failedTurnReason` (§5.5 of this doc). |
| G7 | **Watched components can't skip other models' incidents, and defaults belong to the core.** Any watched-component impact makes an incident relevant (`RuleEngine.incidents`, the `relevant` line), so watching Claude Code would also fire on incidents naming only models not in use. The default watched list is Codex's names hard-coded in `SettingKey.watchedComponents` (`Settings.swift`), and once Kevin saves the checklist the stored list never gains a new source's defaults. | `Plugins.swift`, `RuleEngine.swift`, `Settings.swift`, `CollectorRun` | `ModelNaming` gains `incidentTitleIsModelSpecific(_:) -> Bool`, defaulting to false in a protocol extension (Codex unchanged). An incident a watched component would open is skipped while any of the source's providers says the title is model-specific and no recently used model matches it; an open episode is never skipped (§6.3 of this doc). `StatusSource` gains `defaultWatchedComponents: [String]` (default empty): OpenAI's is today's list, Claude's is `["Claude Code"]`. The setting's default becomes the union of the registered sources'. A new setting lists the status source ids whose defaults have been applied (absent means `["openai"]`, today's database); the collector appends a newly registered source's defaults to a stored list once and records its id. While no list is stored, the collector records every registered id as applied, since the union default already holds their components; and whenever the app saves the checklist it records every id it knows. Either way a component Kevin unchecked is never re-checked **(my call)**. |
| G8 | **No record of context compactions, and no rule for them.** `IngestBatch` has nowhere to put them, and Load has only the large-prompt rule. | `Plugins.swift`, `Records.swift`, `Schema.swift`, `Store+Ingest.swift`, `RuleEngine.swift`, `Settings.swift`, `SettingsView.swift` (Rules) | `CompactionRecord`, `IngestBatch.compactions`, a `compactions` table (schema version 2 with a migration), the `.compactions` rule gated on `.load` (G2) and its Rules row, per §7.3 of this doc. Per-provider Rebuild discards that provider's compactions with its responses. |

Two settings stay shared across providers:

- **Watched components** stay one flat list of names, matched per page
  (`RuleEngine` line 333). The OpenAI and Claude pages share no component names, so G7's defaults
  can't collide.
- **Input-size buckets** (`InputBucket`: <50k … 300k+) stay shared. Per-provider buckets would be a core change without a demonstrated need **(my call)**.

## 5. Claude usage source (`TelltaleClaude`)

New library target `TelltaleClaude`, depending on `TelltaleCore` only. `ClaudeUsageSource`:

| Property | Value |
|---|---|
| `provider` | `ProviderID("claude")` (add `ProviderID.claude`) |
| `displayName` | "Claude Code" **(my call; the sidebar groups by this name)** |
| `statusSourceID` | `"anthropic"`. It must differ from the provider id: usage and status sources share the `source_state` table, keyed by id (`CollectorRun.ingest`, `Store+Status.swift`), and one row would let every status fetch reset a Claude format problem's "since" time. The id is persisted in incidents, episodes and events, so it is fixed from the first release. |
| `signals` | `[.speed, .errors, .link, .provider]`, plus `.load` for the Context compactions rule (G8, this doc §7.3) |

Setup states: `notSetUp("Claude Code's data folder wasn't found.")` when `<claudeHome>/projects`
doesn't exist; `formatProblem` per §5.7 of this doc; else `ready`.

### 5.1 Files and identity

- Roots: `CLAUDE_CONFIG_DIR` as one literal directory when set and non-empty (as Colophon and
  CodexBar treat it), else `~/.claude`; plus `~/.config/claude` when it exists. Claude Desktop's
  Cowork roots are not read (Cowork is a non-goal) **(my call)**.
- Discover `<root>/projects/*/*.jsonl` and `<root>/projects/*/*/subagents/agent-*.jsonl`.
  Ignore other files (`.meta.json`, images, `tool-results/`). Project directories are opaque; the
  path encodes the working directory and is never stored or shown.
- A file is identified by its path relative to `projects` **(my call)**; a main session's
  `sessionID` is the file's UUID stem, a subagent's is `<session-uuid>/agent-<id>`, so parallel
  subagents count as separate active sessions in Workload, as Codex subagent rollouts do.
- `isSubagent` = the file is under `subagents/`, or the line's `isSidechain` is true.
- Files are plain and append-only. Keep a per-file cursor (below). A file that shrank or whose
  identity changed (inode or size below the offset) is re-read from the start; duplicates
  resolve by response id (§5.4).
- Backfill: a file with no cursor whose modification time is before `backfillFrom` is skipped,
  as Codex does.

### 5.2 Reading lines without reading content

Each line is parsed as JSON only to reach the fields in §5.3 and §5.9, then discarded. Never retain or
log `message.content`, `toolUseResult`, `attachment`, `api-request*` bodies, titles, prompts,
`cwd`, `gitBranch` or `quotaLimits.upgradePaths`. **(my call)** Skip lines whose `type` is not
`assistant`, `user` or `system` by a cheap prefix check before decoding, since attachment and
`api-request-blob` lines are large. Decode only into structs that declare the needed keys
(Swift `Decodable` ignores the rest), never into a dictionary.

### 5.3 Responses

| Response field | Source |
|---|---|
| `model` | `message.model` (skip `<synthetic>`) |
| `effort` | top-level `effort` |
| `serviceTier` | `"fast"` when `usage.speed == "fast"`, else `usage.service_tier` (so lines with and without `speed` key alike, as `standard`) **(my call)** |
| `responseID` | `message.id` and `requestId` joined (`msg_…/req_…`), or `message.id` alone when `requestId` is missing: the key all three reference readers use |
| `turnID` | nil (Claude has no turn id that failed requests share; §5.5) |
| `start` | the spec's §6.1 rule, bounded on both sides: the latest `user` line that comes after the previous response's last line and before this message's first line, else the previous response's last line. A tool result written between two lines of a message (§3.1 of this doc) is never a candidate for that message, and counts for the next one only if it comes after this message's last line. A file's first response with neither has no start and is dropped. This is the rule §3.2 of this doc describes. |
| `end` | the timestamp of the message's last line |
| `inputTokens` | `input_tokens + cache_creation_input_tokens + cache_read_input_tokens` of the final usage |
| `cachedInputTokens` | `cache_read_input_tokens` |
| `outputTokens` | the largest `output_tokens` on any line of the message (§3.1 of this doc) |
| `reasoningTokens` | `output_tokens_details.thinking_tokens` when present |

The ≥ 300-token throughput minimum and the 0.3 s floor apply unchanged. A response whose usage
has an `advisor_message` iteration, or any server tool use (`server_tool_use` web search or fetch
requests above zero), spent part of its duration on server-side work, so its throughput would read
falsely slow. The source doesn't emit such responses and counts them in its ingest log line
**(my call)**. This avoids a core flag; if they become common, an "exclude from speed" field on `ResponseRecord` is
the follow-up.

Timestamps are parsed as ISO 8601 with and without fractional seconds (Colophon's lesson).

**When a message is complete.** Its lines can be separated by tool results and need not carry a
`stop_reason`, so a message is complete when (a) a line of a different assistant message follows
it in the file, or (b) the file hasn't been modified for 2 minutes **(my call)**. The cursor's
byte offset stops at the first line of the newest incomplete message; the next run re-reads from
there. A run therefore never emits a partial response, and the final response of a quiet session
waits at most one collector interval plus 2 minutes.

### 5.4 Duplicates

The store's rule (same `response_id`: keep the longer duration) already handles Claude's copies,
which are exact (§3.1 of this doc). Nothing else is needed.

### 5.5 Failures and retries

| Line | Record | Lamp |
|---|---|---|
| `system` `api_error` | `ConnectionEventRecord`, kind `retry`, `retries` = `retryAttempt`, `maxRetries`, detail "HTTP 529 overloaded" or "connection error" when `error.status` is absent. `sourceID` = the line's `uuid`. | Link (Disconnects rule) |
| `isApiErrorMessage` with a provider-side code (`server_error`, `overloaded_error`, any 5xx `apiErrorStatus`, timeouts, connection failures) | `FailedTurnRecord`, `threadID` = the session id, `turnID` = the line's `uuid`, `model` = the model of the file's most recent real response (kept in the cursor), `errorCode` normalized to `overloaded`, `serverError`, `timeout` or `connection` **(my call)**, `message` = a fixed phrase for the code, **never** the message text. `Copy.failedTurnReason(code:)` gains these four ("model overloaded", "server error", "request timed out", "connection failed"); it maps only Codex's codes today (G6). | Errors |
| `isApiErrorMessage` with `rate_limit` (429) | Usage-limit snapshot (§5.6 of this doc), not a failed turn | none |
| `isApiErrorMessage` with a client-side code (`model_not_found`, invalid request, authentication, 4xx other than 429) | Counted in the ingest log line only **(my call)** | none |

Synthetic error lines also appear in copied files; dedupe by line `uuid` (the store's failed-turn
key is provider and turn id). A retry burst that ends in success leaves only retry events; one
that is exhausted leaves the retry events and one failed request.

An exhausted retry burst can light both Link and Errors. The spec's "60-minute websocket limit" exemption has no Claude counterpart.

### 5.6 Usage limit

Only a rejected request records the limit: `quotaLimits.{rateLimitType, resetsAt, status}`.
Emit a snapshot with `usedPercent` 100, `windowMinutes` from the type (`five_hour` 300,
`seven_day` 10,080; others skipped), `resetsAt`, at the line's time. The Usage limit rule (off by
default) would then fire only on rejection. The dashboard readout shows "Limit reached, resets
14:00" for 5 hours after it and nothing otherwise **(my call)**.

### 5.7 Format drift

Claude Code's format is internal and changes often. Record
the newest `version` seen as `sourceVersion`. Report `formatProblem` instead of guessing when:

- a file has `assistant` lines with `message.id` but none decode a `usage` with `output_tokens`;
- a file written in the last 24 hours has `user` lines and `assistant` lines but no line has a
  parsable `timestamp`;
- the `projects` folder holds files modified in the last 24 hours but none match the layout in
  §5.1.

The message names the source: "Claude Code changed its log format. Telltale can't read Claude
Code responses since 09:12." (G3).

### 5.8 Cursor

`ClaudeCursor`, JSON-encoded like `CodexCursor`: per file path, the byte offset just after the
last line consumed (§5.3's completion rule), the file's inode and size at that point, the pending
input time, the previous response's end, the most recent model (for failed requests), and whether
the file has shown a usage line (for §5.7). Entries for files that no longer exist are dropped.
When a response is deferred, events, diagnostics and version observations after its checkpoint
are deferred with it, so a later pass cannot duplicate them or advance metadata beyond the cursor.

### 5.9 Compactions

`system` lines with `subtype: "compact_boundary"` become `CompactionRecord`s (G8, this doc §7.3),
from `compactMetadata` only. A line without `compactMetadata.trigger` or `preTokens` is skipped
and counted toward §5.7's format checks **(my call)**. The cursor needs nothing new: the line is
read in the same pass as the responses.

## 6. Claude status source (`TelltaleStatuspage`)

### 6.1 A Statuspage client, instantiated for Claude

status.claude.com is an Atlassian Statuspage; OpenAI's page is not (its proxy JSON is
incident.io's). Build a generic `StatuspageSource(id:displayName:baseURL:transport:)` target,
`TelltaleStatuspage`, and register it as id `"anthropic"`, display name "Claude", base
`https://status.claude.com` **(my call: generic, since OpenRouter and others also use
Statuspage)**. Unlike the spec's warning about OpenAI's `/api/v2/summary.json` (§10), the v2 API
is Statuspage's own and was current on 2026-10-28 (page `updated_at` 20:45Z during an incident).

The fetch follows the OpenAI source's pattern, so `StatusSource.fetch(known:)` needs no change
(it receives only the stored open incidents, and the source is recreated each run):

| Request | Use |
|---|---|
| `GET /api/v2/summary.json` (2 KB) | every run: components (id → name) and open incidents |
| `GET /api/v2/incidents/{id}.json` (about 5 KB) | an open incident that is new or has a newer `updated_at` than the stored one, and a stored open incident the summary no longer lists (to record its resolution) |
| `GET /history.rss` | fallback for titles and links when the JSON fails, as `RSSFallback` does |

No history is fetched for the 30-day backfill **(my call)**: the OpenAI source fetches none, so
Codex's charts have no past incident bands either, and `incidents.json` (about 190 KB) every run
would be about 55 MB a day at the 5-minute interval. Rebuild keeps stored incidents.

### 6.2 Mapping to `IncidentRecord`

- `id`, `name`, `status` (`investigating`, `identified`, `monitoring`, `resolved`,
  `postmortem`), `publishedAt` = `created_at`, `updatedAt` = `updated_at`, `link` = `shortlink`,
  `history` from `incident_updates[].{created_at, status}`.
- Impacts per component: from each update's `affected_components[].{code, new_status}`, a
  component's impact starts at the first update where it isn't `operational` and ends at the
  update where it returns to `operational`, or at `resolved_at`. Updates without
  `affected_components` fall back to the incident's `components` from `started_at` to
  `resolved_at`, with status from `impact` (`minor` → degraded, `major` → partial,
  `critical` → full).
- **Normalize `major_outage` to `full_outage`** in the plugin, so the core's severity rank (red at
  partial or full) applies unchanged.
- Network or decode failures mark the source unavailable, as for OpenAI (§10).
- If a new incident's detail fetch fails, leave its summary unstored and retry detail on the next
  fetch; a sparse summary may omit the watched-component impacts. Keep an existing record on a
  detail failure so its older timestamp causes another attempt.

### 6.3 Which incidents fire

Kevin decided (2026-10-28): Claude Code should be watched for interruptions and outages, along with the models he uses; Claude API, claude.ai, Console and Cowork don't matter
for now. The spec's rule (a watched component, or a title naming a model used in the last 24
hours) gains one filter, G7:

- **Claude Code is watched by default.** The Claude status source declares it as its default
  watched component (G7). Kevin can uncheck it, or check others, in Settings.
- **A watched component doesn't open an incident whose title names only models Kevin isn't
  using.** "Model-specific" means the title names at least one Claude model and has no
  all-models phrase (`ClaudeModelNames.incidentTitleIsModelSpecific`, §7.1 of this doc). Such an
  incident opens only when its title names a model used in the last 24 hours, by the existing
  title rule. "Elevated errors for Claude Sonnet 5.5" stays quiet while Kevin is on Opus 5.5; it
  fires if he used Sonnet 5.5 that day, or starts using it while the incident is open.
- **The filter applies only to opening.** Once an incident's episode is open, it follows its
  watched components as today, so it doesn't close early because 24 hours of model use rolled
  off during a long incident **(my call)**.
- **Title matching** (`ClaudeModelNames.incidentTitle`, §7.1 of this doc) returns true when the
  title names the model, or contains an all-models phrase ("multiple models", "other models",
  "all models", "Claude services") **(my call on the list)**. It is called only for models used
  in the last 24 hours, as for Codex. It catches a model incident for one of Kevin's models even
  if Claude Code were unchecked. "Claude Code" and "Claude API" are no longer title phrases: the
  Claude Code component covers the first, and Kevin doesn't watch the API.
- **Connector incidents** (some connectors list Claude Code) fire. They can affect Claude Code sessions that use those connectors. A title filter
  for them is easy to add later if they prove to be noise **(my call: not now)**.
- A watched component fires whether or not Kevin used Claude that day, as Codex's do: an outage is
  worth knowing before he starts a session.


## 7. Models, baseline and rules for Claude

### 7.1 Model names

- Speed and baselines key on the literal `message.model` (`claude-opus-5-5`), as §6.1 does.
- Display: drop `claude`, family capitalized, then the version with dots: `claude-opus-5-5` →
  "Opus 5.5", `claude-fable-5` → "Fable 5", `claude-haiku-4-5-20251001` → "Haiku 4.5" (a trailing
  8-digit date is dropped). Anything else shows its id. This is the reverse of Codex's order
  ("6.1 Sol") because Anthropic's own titles say "Claude Opus 5.5" **(my call)**. Full id in
  tooltips.
- Title match: the family word as a whole word, case-insensitive, followed by its first version
  before any other Claude family mention, as a whole number that isn't followed by `.digit`. "Fable 5" matches "Claude
  Fable 5 and Claude Fable 5.1" but not "Claude Fable 5.1".
- Model-specific title (G7): "Claude", a capitalized word and a digit ("Claude Mythos 5.1"), with
  none of this doc §6.3's all-models phrases. The pattern doesn't list families, so a new family is
  covered.
- A context-window variant id (for example a `[1m]` suffix), if Claude Code ever records one in
  `message.model`, is its own model key; the suffix is shown ("Opus 5.5 (1M)").

### 7.2 Baseline and speed rules

Unchanged: the key is model, effort, service tier (with fast mode), and input bucket; 14 active
days; 20-sample bucket minimum; 3 active days of cold start; acceptance and epochs per model.
A model with too little data shows "Not enough recent responses to judge speed"; that is correct, not a fault.

### 7.3 Large prompts and the Load lamp

Kevin decided (2026-10-28): no large-prompt rule for Claude, and a **Context compactions** rule
lights Claude's Load lamp in this release (G8), to be tuned or removed once it has run. It will
light during long-running sessions; that is the point: a prod to start a fresh session, or to
farm work out to subagents, before context is lost and (on older Claude Code) the session stalls.
The Prompt sizes chart and Workload stay, since they describe Kevin's own behavior.

- **Record.** The usage source emits `CompactionRecord` (provider, session id, agent id or none,
  time, trigger `auto` or `manual`, tokens before and after, duration, precomputed), from §3.7 of
  this doc's `compact_boundary` lines. Never the summary text or anything else from `content`.
  Duplicates across files collapse on the line's `uuid`, which copies of a line share
  **(my call)**.
- **Core (G8).** A new `IngestBatch.compactions` field (default empty, so Codex compiles
  unchanged), a `compactions` table keyed by provider and line `uuid` (schema version 2, with a
  migration from 1 and its test), a rule `.compactions` gated by G2 (it runs only for providers
  that support it and declare `.load`), and a Rules row in Settings. The app never migrates
  (ruling R27): until the collector's next run has, its settings writes report that Telltale is
  updating its data **(my call)**.
- **Fires** when a provider has at least 2 automatic compactions in the last 60 minutes, across
  all its sessions and subagents **(my call on the defaults; both are settings)**; clears after
  60 minutes with none. Manual compactions are Kevin's choice and don't count. Amber, notify on,
  clear notice off, like Large prompts. Copy, after G6's provider prefix: "3 automatic
  compactions in the last 60 minutes. Fresh sessions or subagents would keep more context." When
  any of them blocked its session for 10 s or more, it adds the summed time of those, "They held
  sessions for 3 min 40 s."
- **Precomputed compactions still count.** Precomputed compaction need not stall the session, but it still discards most of its context, which is what Kevin
  wants to be prodded about **(my call)**. The stall shows only in the blocked-time readout.
- **Workload readouts** for a Claude model: automatic compactions in the last 3 hours, time
  blocked by them, and the latest automatic compaction point (the median tokens before of the
  last 5, since Claude Code's threshold isn't recorded and can change).
- **Codex.** Codex rollouts record compactions too (`compacted` lines), but without tokens or timing. The record and rule are generic; Codex keeps Large
  prompts and doesn't emit compactions in this release **(my call)**. Large prompts and
  compactions are the two Load rules; each provider's declared signals and its source decide
  which run.

### 7.4 Other rules

Failed turns, Disconnects, Provider incident and Usage limit apply per §5.5–§6.3 of this doc with
the spec's defaults. Collector health covers the Claude source's format problems through the
existing source-state rows.

## 8. The app

The provider integration uses the existing views:

- Sidebar: a "Claude Code" group with its models; "Not set up" dimmed when `~/.claude/projects`
  is absent.
- Panel: Claude models active in the last 3 hours get rows beside Codex's; panel alerts already
  name the provider (`PanelSnapshot`). Notifications and Events name it too (G6). The Provider lamp
  is captioned "Status" with two status sources (existing behavior); the incident copy already
  names the page ("Claude: Elevated errors for Claude Opus 5.5").
- Settings: a new Providers section (§8.3 of this doc). The watched-components checklist gains
  the Claude page's six components, with Claude Code checked (G7). A Context compactions row
  joins Rules (G8). The Data section's button becomes "Rebuild all
  providers…" (G3). Rules stay global, one row per rule, as the spec has it.
- Workload for a Claude model: the existing measures; the effort mix shows Claude's effort names;
  the usage-limit line shows §5.6 of this doc's text.

### 8.1 Naming carryover (so 0.1.1's "Sol, Sol, Sol" doesn't repeat)

An audit of every place a model or provider is named, with what Claude needs:

| Where | Today | Change |
|---|---|---|
| Panel model rows (`PanelView` `ModelRowView`) | Name in a fixed 60 pt column, one line: "Sonnet 5.5" truncates, and "Haiku 4.5" is at the edge | Size the column to the longest name shown, up to 96 pt; with two providers active, a provider line above each group (mockup's last section) |
| Any list of models (sidebar, panel, Events, notifications) | `displayName(model:)` per id; two ids with one name look identical | A shared core helper disambiguates names that collide within what's shown, adding the part that differs ("Opus 5.5 (2026-11-01)", "Opus 5.5 (1M)"); the full id stays in tooltips |
| Claude display names (§7.1 of this doc) | none | "Opus 5.5", "Fable 5", "Fable 5.1", "Haiku 4.5": version always kept; a date suffix dropped only when no collision |
| Failed-turn wording (`Copy.failedTurns`, chart legend "Failed turn", Settings rule labels) | "turn" | The usage source names its unit: Codex "turn", Claude Code "request" ("Claude Code: 2 requests failed: model overloaded"). The rule keeps its name "Failed turns" in Settings, with the per-provider noun in copy **(my call)** |
| Effort mix (`ModelView` line 293) | Missing effort shows "default" | Unchanged for Codex; Claude's missing effort (older versions) shows "not recorded" **(my call)** |
| Service tier in the usual explanation (`Copy` line 163) | "effort and service tier" | Claude Code's fast mode keys as tier `fast`; the explanation says "service tier or fast mode" when the model has fast-mode responses |
| Provider lamp caption | "OpenAI" with one status source, "Status" with two | Unchanged; alerts and notifications already name the page |
| Format problem, Rebuild copy, collector log line | "Codex" | Provider-named (G3) |
| Notifications and Events | No provider for failed turns, disconnects, large prompts, usage limit | Provider-named (G6) |

Snapshot scenes gain two-provider panel and dashboard states, including a long Claude name and two
colliding ids, so the snapshot review catches this class of problem.

### 8.2 Leaving room for Cowork and ChatGPT Work

Neither is read now. Nothing in this design may box them out:

- Each product is its own usage source and `ProviderID` (for example `claude-cowork`), even when it
  shares a status source; `statusSourceID` is already many-to-one. The Claude Code source never
  claims files outside its own roots.
- The Claude Code source's roots are a list, so a Cowork source can take Claude Desktop's
  `local-agent-mode-sessions` without touching it; the parser for the shared transcript format
  lives in a type both could use.
- The Providers section (§8.3 of this doc) and per-provider progress mean a later source arrives,
  backfills and can be rebuilt on its own.

### 8.3 Providers section, per-provider Rebuild and the arrival note

Kevin chose option B and arrival 2 of [the options mockup](mockups/telltale_rebuild_options.html)
on 2026-10-28.

**Per-unit history state** (the store side of G1 (a)). Each evaluation unit (a usage provider,
or a status source) keeps, in `rule_state` under its own id: its last evaluated point, a pending
backfill with its reason (`new` or `rebuild`), and when its last backfill started and finished.
A unit with no state is backfilled with reason `new`; a usage provider only once its source
reports it is set up.

The collector adopts legacy global progress first, applies rebuild requests, then prepares new
status-source backfills in one transaction. A new usage provider starts its backfill only after a
ready ingest; other units continue independently. Each unit commits evaluation in day-sized
chunks and retains its own backfill boundary across interruptions. A completed undismissed
arrival is stored separately so a later rebuild cannot erase it.

**Requests.** Settings stores per-provider rebuild requests (provider id → when requested, so the
state line can show the time) beside the
existing global request, which now means "all providers". The collector applies them at the same
step as today's Rebuild, and the run that applies a request also backfills that provider. What a
per-provider rebuild discards and keeps is listed in this doc §12 (Decided, Rebuild). Failed-turn
and connection rows are kept, as today, with `evaluated_at` reset for that provider only.

**Providers section** in Settings, after Collector and before Watched status components **(my
call)**, one row per registered usage source in registry order:

| Part | Content |
|---|---|
| Name | The source's display name ("Claude Code") |
| State line | One of: "Reading normally." / the not-set-up reason / the format problem with its time (Collector health's wording) / "Reading 30 days of history, started 14:02. No notifications are sent for it." / "Rebuild requested at 14:01. Waiting for the collector." |
| Facts | "Claude Code 2.1.310 last seen at 14:05." (the source version and its last ingest); "History from Jan 01, 2000. Read in full Jan 31, 2000." (the oldest response held and the last backfill's finish); "Data folder ~/.claude" (from `TelltalePaths`, home abbreviated) |
| Action | **Rebuild…**, disabled while that provider has a backfill pending or running |

The Rebuild confirmation names the provider and says what it touches, as in the mockup: "Telltale
will re-read the last 30 days of Codex logs. Codex speed history before Jan 01, 2000 is removed. Claude
Code isn't touched and keeps watching. Accepted baselines are kept, and no notifications are sent
for the history it reads." Buttons: Cancel, **Rebuild Codex**. The Data section's **Rebuild all
providers…** keeps today's confirmation, naming every provider. Both follow today's rules: only
the installed copy offers them, and only once the collector's first run has created the database
(the existing notes apply). Closing the alert clears its presentation state before the button's
action runs (the 0.1.0 Rebuild bug, fixed in 0.1.1), so the provider travels with the action
itself, as Undo's event does, and is never read back from that state.

While a provider backfills, its sidebar group shows "Reading history…" under its name and its
models are dimmed; its panel rows appear when the backfill finishes **(my call: its usual isn't
ready before then)**.

**Arrival note.** When a provider's backfill with reason `new` finishes in a database that already
held another provider's evaluated history (an upgrade, not a fresh install) **(my call)**:

- The panel shows a standing note, placed like the lasting-shift prompt: "Telltale now watches
  Claude Code. It read 30 days of history; usual speeds are ready for Opus 5.5." The model list
  names the models past cold start; with none, "usual speeds are still being learned". Buttons:
  **Open Claude Code** (the dashboard on that provider's first model) and **Dismiss**.
- It stays until dismissed. The dismissal is stored through the existing read-write-existing path
  (a setting listing dismissed arrivals), so a relaunch doesn't bring it back.
- No notification is posted; backfill never notifies.
- Events records "Telltale now watches Claude Code. It read 30 days of history and sent no
  notifications for it." A per-provider rebuild records "Codex history rebuilt from 30 days of
  logs." and shows no panel note.

## 9. Privacy and safety

- Metadata only (§11). The parser's decode types declare only this doc §5.3's and §5.9's fields; nothing from
  content, paths, titles or `cwd` reaches the store or the log.
- The only new network requests go to status.claude.com.
- Reads of `~/.claude` are plain file reads; Telltale never writes there.
- Fixtures are synthetic: session ids `00000000-0000-4000-8000-0000000000NN`, message ids
  `msg_synthetic_NN`, agent ids `agent-synthetic-NN`, project folder `-Users-example-project`,
  and content fields filled with a fixed placeholder (so a test can assert they never reach the
  store).

## 10. Tests

Per the repository's Testing Scope, the complete `make -C telltale test`, plus:

- **Unit (TelltaleClaude):** multi-line messages with partial usage (largest wins); tool results
  interleaved inside a message; the completion rule (next message, quiet file, incomplete trailing
  message deferred and resumed by offset); the start rule (tool result, prompt, meta, previous
  end, none); fast mode and missing `speed`; effort missing; copies across files; subagent
  identity; retry lines; each error class of §5.5; `quotaLimits` → snapshot; format-drift cases;
  a file truncated or replaced; content fields never stored (assert on the placeholder).
- **Unit (TelltaleStatuspage):** summary and incidents fixtures (synthetic, shaped like the real
  page), impacts from `affected_components`, the fallback when they're absent, `major_outage`
  normalization, RSS fallback, unavailable source.
- **Unit (naming):** display names; title matching including "Fable 5" vs "Fable 5.1" and the
  all-models phrases; model-specific titles ("Claude Mythos 5.1" yes; "Claude services",
  "Claude Code and Claude Cowork", "Claude Sonnet 5.5 and other models" no).
- **Core:** G1 per its chosen option (a source added to an existing database is backfilled
  without notifying, 30-day-old failed turns included; the other provider's history and episodes
  are unchanged); G2 (an undeclared signal's rule neither fires nor notifies); G3 copy; G4
  `CLAUDE_CONFIG_DIR`; G6 (a Codex and a Claude failure inside 15 minutes post two notices, each
  naming its provider); the `claude`/`anthropic` source-state rows stay apart; G7 (a Claude
  Code incident naming only an unused model stays quiet, fires once that model is used, and an open episode isn't dropped when
  use rolls off; Codex's incidents unchanged; a stored watched list gains "Claude Code" once and
  an unchecked one stays unchecked); G8 (compactions ingested and deduplicated, never the summary
  text; the rule fires at 2 automatic in 60 minutes, ignores manual ones, clears after 60 quiet
  minutes, and doesn't run for a provider without `.load`; the schema 1 to 2 migration on a
  synthetic database).
- **Integration:** the collector run against a synthetic `CODEX_HOME` and a synthetic Claude
  home together, and against a Claude home alone.
- **Snapshots:** the panel with Codex and Claude rows (a long name and two colliding ids), the
  panel with the arrival note, the dashboard on a Claude model, and Settings' Providers section
  in its normal, not-set-up, format-problem and backfilling states, light and dark.
- **Per-provider Rebuild:** a Claude rebuild leaves Codex's responses, points, episodes and
  events byte-for-byte unchanged and Codex keeps evaluating live during it; the arrival note
  appears only for an upgrade, once, and stays dismissed across relaunch.
- **Isolation:** extend `check_test_isolation.sh` to fail on a test reaching the real `~/.claude`
  or `~/.config/claude`.
- **Private replay (manual and read-only):** run the real engine over private history. Publish only a non-sensitive qualitative summary of whether the rules behaved as intended; keep counts, dates, episodes and source data private.

## 11. Release

A new provider is a feature: version 0.2.0 (Kevin agreed 2026-10-28), bumped in
`TelltaleRelease` and the plist in the same change (`tools/deploy_telltale.mjs` reads the
plist's version and pins none). README sections
(purpose, How the collector runs: it also reads `~/.claude` read-only and requests
status.claude.com), the `AGENTS.md`/`CLAUDE.md` Validation Matrix entry if commands change, and
the deployment guide if the deploy contract changes.

## 12. Decisions for Kevin

Decided on 2026-10-28:

- **Rebuild:** both a global rebuild and a per-provider one. This needs G1 option (a),
  per-provider evaluation progress, which also backfills a newly added source; options (b) and (c)
  below are no longer in play. A per-provider rebuild discards that provider's responses, points,
  episodes, rule events, rule state, cursor and compactions, keeps acceptances, incidents and
  settings, and backfills it quietly while the others stay live. Its status source's incident
  episodes are kept: a status source is its own evaluation unit (G1), possibly shared with
  another provider, and only the global rebuild resets it.
- **Rebuild and arrival UI:** option B and arrival 2 of
  [the options mockup](mockups/telltale_rebuild_options.html): a Providers section in Settings
  with a Rebuild per provider, Rebuild all providers in Data, and a new provider announced once
  in the panel (this doc §8.3).
- **Load lamp:** no large-prompt rule for Claude; a Context compactions rule lights it in this
  release, to be tuned or removed once it has run (G8, this doc §7.3).
- **Incidents:** Claude Code is watched by default, and model incidents fire only for models
  Kevin is using; Claude API, claude.ai, Console and Cowork aren't watched for now (G7, this doc
  §6.3).
- **Version 0.2.0.**
- **Every notification and event names its provider** (G6), and the views get the naming
  carryover in this doc §8.1.
- **No incident history fetch** for the backfill.
- **Cowork and ChatGPT Work** aren't read, and nothing may box them out (this doc §8.2).

Nothing is open. For the record, the G1 options for backfilling a newly added source:

- (a) **Per-provider evaluation progress (recommended).** The rule engine keeps a last point per
  provider; a provider with none is backfilled from its 30-day lookback without notifying,
  while the others continue live. It's the durable plugin contract ("adding a source backfills
  that source"), and it needs a few rule-engine and store changes with tests.
- (b) **Automatic Rebuild** when a usage source has no cursor in an existing database. Little
  new code (the Rebuild path already backfills quietly, failed turns included), but it discards
  Codex's derived data and re-reads 30 days, losing Codex responses older than 30 days (a potential loss for any later plugin).
- (c) **Do nothing**, and tell Kevin to press Rebuild once after upgrading. Same loss as (b),
  and the first collector run after the upgrade posts 30 days of Claude failures as one
  notification before he can press it. Not recommended.

Kevin chose (a).

## 13. Left to the builder

- Decode types and how lines are pre-filtered before decoding (§5.2 of this doc).
- How the Statuspage client decides an incident changed, within §6.1 of this doc.
- Exact copy beyond the examples, following the visual design's copy rules.
- Test fixture shapes, within §9 of this doc.

## 14. Risks

- **Undocumented, fast-moving transcript format** (`api-request`, `speed`, `thinking_tokens` and `iterations` can vary by version). Mitigated by validation,
  a visible format problem (§5.7), and the start rule not depending on new fields.
- **Older layouts.** ccusage still accepts `progress` lines that carried subagent usage inside the
  parent's file (an older Claude Code layout). They aren't read; if they reappear, §5.7's checks don't catch them, and subagent speed would go missing.
- **Thin data for lightly used models.** Shown as unknown, never guessed.
- **Output-length mix.** A shift in output lengths can change observed throughput and add to real slowdowns.
  The same holds for Codex today.
- **Claude Code's transcript cleanup.** Claude Code deletes transcripts older than its
  `cleanupPeriodDays` setting (default 30 days). With the default, the 30-day backfill is the limit.
- **Status page wording.** The all-models phrases are a fixed list; a title that names a model and broadens it in new words
  ("Claude Sonnet 5.5 and others") would read as model-specific and stay quiet unless Kevin uses
  that model. Titles that name no model ("most models") aren't affected.
- **Compaction noise.** The rule will light on long working days. Kevin accepted this as a prod, to tune or remove after it has run; the threshold and
  window are settings.
