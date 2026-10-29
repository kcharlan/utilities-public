# Telltale design spec

Status: approved by Kevin, 2026-10-27. Implementation plan:
[telltale_implementation_plan.md](telltale_implementation_plan.md).
Companion documents:

- [Visual design](telltale_visual_design.md): look, type, color, copy rules.
- [Mockups](mockups/telltale_mockups.html): panel, dashboard and collector view.

Decisions marked **(my call)** were made by the author of this spec, not by
Kevin. Change them freely. Everything else was decided by Kevin in the
2026-10-27 design conversation.

## 1. Intent

Kevin runs Codex agents all day. Provider trouble (slowdowns, capacity
errors, disconnects, odd speedups) often shows up before or without an
official status post. On 2026-10-27 his own logs showed a Sol slowdown about
90 minutes before OpenAI posted an incident. On 2026-10-26 they showed a
morning of capacity failures that OpenAI never posted.

Telltale watches for that in the background and answers two questions at a
glance:

1. **Is something off?**
2. **Is it them or me?** Is it the provider, or my own workload (huge
   prompts, many agents)?

The second matters because large prompts are measurably slower. Sol decodes
about 44 tok/s with prompts under 50k input tokens and about 28 tok/s at 300k+.
Telltale should also prompt Kevin to hand a session off before context bloat
slows everything down.

A key behavior Kevin asked for: alert within about 15 minutes so he doesn't
spin up more agents "into the teeth of a slowdown".

## 2. Goals, non-goals, anti-goals

**Goals**

- Continuous background monitoring, even when the app is not open.
- Size-adjusted speed alerts in both directions (slower *and* faster).
- Workload view: prompt-size distribution, turns, sessions and other load
  characteristics against usual.
- Durable record of failures, disconnects, provider incidents and baseline
  changes.
- A collector that the app installs, controls and health-checks.
- Configurable alert rules: per-rule on/off, thresholds, durations,
  notifications.
- Provider plugins. Codex (OpenAI models) ships first; OpenRouter and Claude
  follow later.

**Non-goals (for now)**

- Measuring output quality. A speedup is flagged as suspicious, nothing more.
- Time-to-first-token. Codex logs don't record it.
- Cost or token accounting. Colophon and CodexBar do that.
- Model-list tracking. Model Sentinel does that.
- Sending synthetic probe requests to providers.
- OpenRouter and Claude plugins. Only their interface is defined here.

**Anti-goals** (failure even if it technically works)

- **Noise.** Repeated notifications for one ongoing problem, or flapping.
- **Silent baseline adaptation.** A bad week must never quietly become
  "usual".
- **Heavy infrastructure.** No OpenTelemetry collector, Docker or servers.
- **Reading or storing prompt or response content.** Telltale keeps
  metadata only.
- **Modifying provider records,** or holding locks that slow Codex. SQLite coordination follows the read-only SQLite contract in `colophon/docs/LESSONS_LEARNED.md`.
- **Committing real usage data to this public repository.**

## 3. Product shape

One macOS 27 app, `Telltale.app`, with three parts:

1. **Menu-bar status item**, always present. It shows a glyph and a dot in
   the most severe lit lamp's color, plus a 340 pt panel.
2. **Dashboard window**, opened from the panel. It's resizable, about
   1100 × 760 by default, with a provider sidebar plus Collector and Settings.
3. **Background collector.** The same executable runs with `--collect` from a
   user launchd job, every N minutes. It collects data, evaluates alert rules
   and posts notifications.

Identifiers follow the repo's `local.utilities.*` convention, used by
Brew Version and Prime Monitor:

| Thing | Value |
|---|---|
| App bundle | `Telltale.app`, executable `Telltale` |
| Bundle identifier | `local.utilities.telltale` |
| Collector job label | `local.utilities.telltale.collector` |
| Version | `0.1.0` for the first release |

The app is a menu-bar app (`LSUIElement`). It shows a Dock icon only while
the dashboard window is open, switching activation policy to `.regular` and
back to `.accessory` **(my call)**. It is not sandboxed: it reads `~/.codex`
and runs `launchctl`. It offers "Open at login", registered through
`SMAppService.mainApp`, ported from Brew Version's `LoginItem` (as Prime
Monitor did). Open at login is on by default **(my call)**.

## 4. Architecture

```
            ┌──────────── launchd (gui/$UID) ─────────────┐
            │ local.utilities.telltale.collector          │
            │ StartInterval = N min, RunAtLoad            │
            └───────────────┬─────────────────────────────┘
                            │ runs
                 Telltale --collect   (single writer)
     reads ┌────────────────┼──────────────────────┐ posts
 ~/.codex  │ provider plugins ─▶ normalized records │ notifications
 status    │ rule engine ─▶ episodes, events        │ (as Telltale)
 page      └────────────────┼──────────────────────┘
                            ▼
     ~/Library/Application Support/Telltale/telltale.sqlite (WAL)
                            ▲ read-only
                 Telltale (menu bar + dashboard)
     manages the launchd job; "Check now" = launchctl kickstart
```

### Rules

- **Single writer.** Only the collector writes data, evaluates rules and
  sends rule notifications. The app reads the database read-only, except for
  settings, acceptances and user actions (§9.4). The app never collects
  in-process. "Check now" kicks the launchd job.
- **One executable, two modes (my call).** Running the app executable with
  `--collect` makes notifications come from Telltale's own bundle identity,
  even when the UI isn't running.
  - **Required spike** before building on this: confirm that
    `UNUserNotificationCenter` posts as Telltale from a launchd-started
    `Telltale --collect` while the UI is not running, and while it is.
  - **Fallback if the spike fails:** the collector records pending
    notifications, and the running UI delivers them (it is a login item).
    The spec's behavior is unchanged except that notifications need the UI
    running.
- **Overlap guard.** Each collector run takes an exclusive `flock` on
  `~/Library/Application Support/Telltale/collector.lock`. A run that can't
  get the lock exits 0 and records "skipped: previous run still active".
- **Catch-up.** A run evaluates every 5-minute evaluation point since the last
  evaluated one (§7.1). Results don't depend on the interval or on missed
  runs (sleep, logout).
- **The UI refreshes** by watching the database file for changes, with a
  30-second poll as backup (builder's choice of mechanism).

### Storage (my calls)

| What | Where |
|---|---|
| Database | `~/Library/Application Support/Telltale/telltale.sqlite`, SQLite in WAL mode, through the system `SQLite3` module (no package dependency) |
| Collector log | `~/Library/Logs/Telltale/collector.log`, rotated at 5 MB, 3 kept |
| Settings | the `settings` table, read by both processes at start of use |

Retention:

| Data | Kept |
|---|---|
| Response rows | 180 days |
| Events, episodes, incidents, baseline acceptances | indefinitely (small) |
| Collector run records | 30 days |

The database schema is the builder's, but it must hold at least:

- normalized responses
- failed turns
- connection events
- incidents
- episodes (§7)
- events
- baseline epochs (§8)
- collector runs
- per-source ingest cursors
- settings

## 5. Provider plugin interface

Plugins are compiled into the app. "Snap in" means adding a module that
conforms to the protocols and registering it in one list; there is no
dynamic loading **(my call)**. There are two kinds:

- **Usage source.** Reads the user's own activity for one provider and emits
  normalized records:
  - **Response:** provider, model, effort or variant (required when the
    provider has one, because it changes speed; see §8), service tier when recorded, session id,
    is-subagent, turn id, response id, start time, end time, input tokens,
    cached input tokens, output tokens, reasoning tokens (optional).
  - **Failed turn:** time, model (optional), error code, message.
  - **Connection event:** time, kind (disconnect, retry, reconnect), detail.
  - **Usage-limit snapshot** (optional): percent used, window, reset time.
  - Plus a setup state (`ready`, `notSetUp(reason)`, `formatProblem(detail)`, `readProblem(detail)`)
    and an incremental cursor the core persists.
- **Status source.** Reads a provider's public status page and emits incidents
  with id, title, status and its history, component impacts with start and
  end times, and a link. Each usage source names its status source.

Each plugin also declares which signals it can feed, so the UI shows only
lamps a provider supports. Records must not carry prompt or response text.

Later plugins are out of scope. Notes only, not binding:

- **OpenRouter** could use per-generation stats or activity exports.
- **Claude** could use Claude Code transcripts under `~/.claude/projects`,
  and status.claude.com.

## 6. Codex usage source

All reads are read-only. SQLite files are opened with `mode=ro` and a short
busy timeout. On `SQLITE_BUSY` or a locked file, the source skips and retries
next run (it never blocks Codex).

**Closed WAL databases.** When Codex closes a WAL-mode database, system SQLite can
fail a read-only statement with `SQLITE_CANTOPEN`. A WAL header and absent `-wal`
are evidence for `ReadOnlySQLite.Closed`, not proof that no process has the file
open; a writer can reopen after the post-clone check. An unreadable header still
produces a read failure. For a changed or never
read selected file, the reader uses a private APFS clone as described in §11;
an unchanged file with the same name and modification date is skipped. A busy or
closed skip preserves the previous read stamp and verdict. A successful read or
format problem records the selected filename and pre-read modification date; a
read failure clears that stamp so the next run retries. A new filename requires a
read even if its date matches. A kept format problem is dropped when a different
file is selected; older cursors without a problem filename retain it for the
current file. A read failure is reported for that run, while a matching earlier
format problem takes precedence and remains kept.

### 6.1 Rollouts: responses

**Files.** `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl[.zst]` and
`~/.codex/archived_sessions/rollout-*.jsonl[.zst]`.

- Codex compresses finished rollouts to `.jsonl.zst` and later deletes the
  plain file. Most history is compressed: 395 of 602 files over Oct 13–27.
  Discovery must take both suffixes.
- **zstd** is decoded with a vendored decompressor, the same upstream v1.5.7
  decompression sources Colophon vendors (BSD), as a SwiftPM C target with
  its license and digests. Copy them; don't link across projects. Heed
  Colophon's lessons on streaming end-of-frame and truncated files
  (`colophon/docs/LESSONS_LEARNED.md`).

**Identity and resume.**

- A session is identified by the UUID in its filename (also
  `session_meta.payload.id`).
- Plain files grow while a session is live. Keep a per-session cursor (last
  processed `ordinal` and byte offset). When a plain file is replaced by its
  `.zst` sibling, resume by ordinal, not path.
- `response_id` is unique. Forked subagent files copy part of their parent's
  history with rewritten timestamps. Handling:
  - When `session_meta.payload.subagent_history_start_ordinal` is present,
    skip records below it. Colophon uses this field. No first-line
    `session_meta` in the Oct 13–27 files had it, but older files did.
  - Otherwise, on a duplicate `response_id`, keep the copy with the longer
    duration. A copied record shows a near-zero duration, so this works
    whichever file is ingested first **(my call)**.

**Model names** **(my call)**:

- Speed and baselines key on the literal `turn_context.payload.model`, for
  example `gpt-6.1-sol`.
- Display name: drop the vendor prefix, put the version first and capitalize
  the rest ("6.1 Sol"). The version stays because Codex logs hold several
  versions of one family at once (`gpt-6.1-sol`, `gpt-6-sol`, `gpt-5.6-sol`),
  and without it they all read "Sol" (changed in 0.1.1). Show the full id in
  tooltips.
- Incident titles match a model when they contain both its family word ("Sol")
  and its version ("6.1"), case-insensitive. For example: "6.1 Sol Degraded
  Model Performance", "GPT-6.1 Sol Codex".

**Records used** (each line has `timestamp`, `ordinal`, `type`, `payload`):

| Line | Used for |
|---|---|
| `session_meta` | `payload.id`. The session is a subagent when `payload.parent_thread_id` or `payload.forked_from_id` is present. |
| `turn_context` | `payload.model`, `payload.effort`. They apply to later responses in the file. |
| `event_msg` with `payload.type == "thread_settings_applied"` | `payload.thread_settings.service_tier`, applied to later responses; see §8. |
| `response_item` with `payload.type` `function_call_output` or `custom_tool_call_output`; `response_item` `message` with `payload.role == "user"`; `event_msg` `task_started` | Input events: candidates for a response's start time |
| `token_usage_record` | One per model response: `payload.response_id`, `payload.turn_id`, `payload.usage.{input_tokens, cached_input_tokens, output_tokens, reasoning_output_tokens}`. Its timestamp is the response end. |

**Response start rule** (validated against two weeks of data):

- Start is the latest input event after the previous `token_usage_record` in
  the same file. If none exists, use the previous record's time.
- Duration = end − start.
- Drop responses under 0.3 s. Forked subagent files copy their parent's
  prefix with rewritten timestamps.
- Duration includes queueing, time-to-first-token and decoding. It's an
  honest "how long did I wait" number, not a pure decode speed.

The cursor must persist the pending start time and the current model,
effort and service tier, because a run can stop mid-response.

**Throughput** = output tokens ÷ duration, computed only for responses with
**≥ 300 output tokens**. Shorter responses are dominated by fixed latency.
They still count for workload metrics.

**Never read** message contents, reasoning text, tool arguments or tool
output. Parse each line as JSON only to reach the fields above, then discard
the line.

### 6.2 Failed turns

Source: `~/.codex/thread_history_*.sqlite`, the highest number present (today
`thread_history_1.sqlite`), table `thread_turns`.

- Columns used: `thread_id`, `turn_id`, `status`, `error_json`,
  `started_at`, `completed_at`.
- Rows with `status = 'failed'` are failed turns.
- `error_json.codexErrorInfo` is the error code: `serverOverloaded` means
  "Selected model is at capacity", and `cyberPolicy` was also seen.
  `error_json.message` is user-facing text.
- Model: join `turn_id` to ingested responses. If unknown, it's attributed to
  "Codex" without a model.
- This table survives restarts. It had 33 failed turns from July to October
  2026.
- Incremental by `started_at`, rescanning the last 2 hours, since a row is
  written at start and updated at the end.

### 6.3 Disconnects and retries

Source: `~/.codex/logs_2.sqlite` (the highest `logs_*` number), table `logs`.

- Rows with `target = 'codex_core::responses_retry'` and `level = 'WARN'`.
- Parse from `feedback_log_body`: `retries=N`, `max_retries=M`, and the
  `sampling_error=` text. Examples: "stream disconnected before completion:
  WebSocket protocol error: Connection reset without closing handshake";
  "Responses websocket connection limit reached (60 minutes)".
- Classify the 60-minute websocket limit as routine (kind `reconnect`, not
  counted toward the disconnect rule) **(my call)**.
- Incremental by `id`.
- **This table keeps only about the last 15 hours.** The collector must run
  at least that often to keep a complete record. Gaps are recorded as
  "connection history incomplete".

### 6.4 Usage limit

`event_msg` lines with `payload.type == "token_count"` carry
`payload.rate_limits.primary.{used_percent, window_minutes, resets_at}`.
Keep the latest snapshot for display. It has a rule, off by default (§7.4).

### 6.5 Format drift

Codex's files are internal and change often (`cli_version` in `session_meta`,
for example `0.164.0-alpha.11.1`). The source must:

- Validate the fields it needs.
- Report `formatProblem` instead of guessing when they're missing: for
  example, no `token_usage_record` lines in a session that clearly ran turns,
  or missing table columns.
- Record the Codex version seen.

A format problem lights the Collector lamp red with a plain message: "Codex
changed its log format. Telltale can't read responses since 09:12."

**Format-problem policy.** The lamp and the panel message appear from the first
collector run that reports a format problem, but the Collector health
notification (§7.4) waits until a second consecutive run reports it, so a
problem that clears on the next run (a transient one) never posts, and so never
posts a recovery either. "Since" is when the source entered its current kind of
unavailable state: it is kept while the same kind of state continues, whatever
its text, and restarts when a source moves between "not set up" and "format
problem" (or from ready). Telltale judges "second consecutive report" from the
stored source state: a report after the one that began the problem has an
`updatedAt` later than `unavailableSince`. With two sources reporting format
problems, the notification names a confirmed one, even when the panel lists a
newer one first.

**Read problems.** A failure to read a provider's file is a read problem, not
format drift. It shares the format-problem lamp, message and two-consecutive-run
notification policy. If one ingest reports both kinds, the first format problem
wins; otherwise the first read problem wins. The since time persists while the
same kind continues, regardless of detail, and restarts on a transition between
format and read problems or any other state.

## 7. Rule engine

### 7.1 Evaluation

- **Evaluation points** are every 5 minutes on wall-clock boundaries
  (`:00`, `:05`, …).
- **Speed index** at a point, per model: the median, over responses ending in
  the trailing 15 minutes with throughput computed, of `throughput ÷ usual`.
  Usual uses that response's baseline key (§8).
- **Input-size buckets** (input tokens): < 50k, 50–100k, 100–200k,
  200–300k, 300k+.
- **Thin data:** fewer than **10** qualifying responses in the window makes
  the point *unknown*. Unknown points neither advance nor clear anything.
  The UI says "Not enough recent responses to judge speed".

### 7.2 Episodes

Applies to the speed rules and the large-prompt rule:

- **Fire** when the condition has been true at every point over the rule's
  duration. 15 minutes means 3 consecutive points.
- **Clear** when it has been within the rule's clear band for its clear
  duration. The speed default is within 8% of usual for 30 minutes.
  - The clear band must be stricter than the trigger.
  - Clearing posts "Sol is back to usual speed" when the rule's
    "Notify when it clears" is on.
- **Idle end:** if a model has no qualifying responses for **2 hours**, its
  open episode ends silently. The next activity starts fresh.
- One notification when an episode fires, and one when it clears. Nothing in
  between.
- A long shift therefore notifies about once per active day. Each morning's
  slowdown is a new episode. Kevin wants this.
- **Onset** = the time of the first true point minus the window. This is the
  start of the excluded period for baselines (§8).
- **Severity:** amber at the threshold, red at **2× the threshold**, for
  example 30% slower, after the same duration **(my call)**. A rise to red
  within an episode sends one extra "now 34% slower" notification.

Failed turns belong to an episode only when the rule engine counts them. Each
counted batch records its ordered turn IDs and reason codes with the episode's
canonical total, rule state and evaluation marks in one transaction. Rows settled
before a lookback cutoff are excluded, including old arrivals on later runs. A turn
completing at the cutoff is eligible even if it started earlier.

These rules were replayed against Oct 13–27 (§12). Without the stricter clear
band, a single day produced 7–9 slowdown notifications. Without the idle end,
the Oct 26 episode masked the Oct 27 slowdown.

### 7.3 Catch-up, backfill and history (my calls)

**History is a fixed record.**

- Episodes and events are written once, as evaluated at the time, against the
  usual in effect then.
- Each evaluation point stores its speed index and the usual it used. Charts
  draw those stored values, so history doesn't change color when the
  baseline changes.
- Accept and Undo change the baseline **from that moment forward** and change
  which past responses feed it. They never rewrite past episodes or events.

**Backfill** (cold start) replays the 30 days chronologically, using only
earlier data for usual at each hour. That's the same engine as live
evaluation. It **never notifies**. On every ingest, including catch-up, the collector keeps responses
ending at or after the 30-day cutoff and compactions and connection events at or
after it. It preserves failed turns, connection gaps, usage limits, source version
and exclusion counts; older failed turns follow the existing settlement path.
Already stored rows are governed by retention, not this ingest filter.

**Rebuild from Codex logs** discards derived data:

- discarded: responses, evaluation points, episodes, rule events
- kept: acceptances and their epochs, which are replayed as dated inputs at
  their creation times

It then backfills. It never notifies.

**Catch-up** after sleep, logout or an overdue run evaluates every missed
point in order, then notifies only on what's still relevant:

- An episode that fired and is still open at the latest point notifies once:
  "Sol has been 22% slower since 09:40".
- An episode that fired and cleared entirely inside the gap is recorded only.
- Clears and escalations more than one interval old are recorded only.

### 7.4 Default rules

Every value is editable in Settings. Each rule has: on/off, its parameters,
"Notify" (on/off), and "Notify when it clears" (on/off).

| Rule | Lamp | Fires when (defaults) | Clears when | Notify |
|---|---|---|---|---|
| Slower than usual | Speed, amber or red | Speed index ≤ 0.85 for 15 min | > 0.92 for 30 min | On, clear notice on |
| Faster than usual | Speed, blue | Speed index ≥ 1.15 for 15 min | < 1.08 for 30 min | On, clear notice on |
| Large prompts | Load, amber | ≥ 3 of the model's last 10 responses had input ≥ 300k | ≤ 1 of the last 10 | On, clear notice off |
| Failed turns | Errors, red | Any failed turn | 30 min with no failure **(my call)** | On, coalesced: at most one per 15 min, "2 turns failed: model at capacity" **(my call)** |
| Disconnects | Link, amber | ≥ 3 disconnect or retry events in the last 60 min | < 3 in the last 60 min | Off |
| Provider incident | OpenAI, amber; red for partial or full outage status | An open incident affects a watched component, or its title names a model used in the last 24 h | Incident resolved | On, clear notice on |
| Collector health | Collector, red | Job should be on but isn't loaded, 2 failed runs in a row, no successful run for 3× the interval, or a format or read problem reported by two consecutive collector runs (§6.5) | Condition gone | On (posted by the UI, §9.3) |
| Usage limit | none (readout only) | Primary window ≥ 90% used | < 90% | Off, rule off by default **(my call)** |

When two lamp colors are possible, the lamp shows the most severe one.
Severity order: red, amber, blue.

An open failed-turn alert reports the episode's total and onset. After a count
increase beyond an acknowledgement, it reports the new count and acknowledgement
time, with the episode total beneath it. Reasons come from counted membership.
**Legacy failed-turn reasons:** when an older episode has no recorded membership,
retain its canonical count without inferring reasons from evaluation timestamps;
omit the reason suffix for any range containing unknown members. Retained events
are unchanged.

**Watched components**, editable, are matched by the names in the status
page's component list. Defaults **(my call)**: CLI, VS Code extension, Codex
in ChatGPT Desktop, Codex API, Codex Web, Responses.

## 8. Baseline ("usual")

Kevin decided: **a lasting change never becomes usual without his OK.**

- **Usual speed** is the median throughput per **model, effort, service tier and
  input-size bucket**. It's computed from the most recent **14 active days** of
  **unflagged** responses.
  - **Effort is part of the key.** In Oct 13–27 data, Sol at high effort ran
    about 17% slower than at medium for the same prompt size (34.7 vs
    41.9 tok/s at 100–200k input). Without the key, switching effort would
    fire false alerts. The service tier (`default` or `priority`) is in the key
    for the same reason. Codex records it per thread in `event_msg`
    `thread_settings_applied` events (`payload.thread_settings.service_tier`),
    not in `turn_context`; a response with no recorded tier keys as "none"
    **(my call)**.
  - An active day is a local calendar day with at least one qualifying
    response for that model.
  - Unflagged means the response is outside every speed episode, from onset
    to clear or idle end. Large-prompt and other episodes don't exclude data.
- A bucket with fewer than **20** samples has no usual. Responses in it are
  left out of the speed index, and the dashboard says "Not enough history yet
  for 300k+ prompts" **(my call)**.
- Usual is recomputed at least hourly **(my call)**.
- **The one "usual" number shown per model** (panel row, dashboard readout,
  sparkline scale) is matched to the recent mix **(my call)**. It's the median,
  over the same responses as the tok/s beside it, of each response's own
  usual (using the baseline key defined above). "31 tok/s, usual 42" therefore always means
  "42 for what you've been running". A slowdown fully explained by prompt size
  or effort or service tier shows no gap.
- The acceptance confirmation reports the change as a percentage: "Sol's
  usual speed is now 24% lower than before."
- **Small drift** below the trigger enters the baseline as ordinary variation.
  The dashboard shows the current usual against the usual at the last
  acceptance: "Usual is 6% slower than when you accepted it on Oct 12."
- **Lasting shift prompt.** When same-direction speed episodes have fired on
  **3 consecutive active days** for a model, the panel and dashboard show a
  standing prompt (not a notification) **(my call on exact trigger)**:

  > Sol has been about 25% slower than usual for 3 days. Accept as usual?

  The prompt links to the status-page incidents in that period. It offers:

  - **Accept as usual…**: pick a since-date, defaulting to the first episode
    day. This starts a new **baseline epoch**: usual is computed only from
    responses on or after that date, and it fills up to 14 active days as
    time passes. Responses from that date that were inside episodes now count
    as normal. Confirmation: "Sol's usual speed is now 24% lower than
    before."
  - **Keep as abnormal**: dismisses the prompt for this shift. A new prompt
    appears only after a clear followed by a new 3-day run.

  Kevin can also accept from the dashboard at any time.
- Every acceptance is an event with **Undo**. Epochs are kept, and undo
  restores the previous one.
- **Cold start.** The first collector run backfills the last 30 days from
  rollouts (including `.zst`) and `thread_history`. The collector applies the same
  cutoff and preserved-field contract described in §7.3. Speed rules stay quiet
  until a model has 3 active days. Until 14 days, the dashboard shows
  "Learning usual: 5 of 14 days".

## 9. The app

### 9.1 Status item and panel

- **Status item:** port Brew Version's macOS 27 handling exactly:
  `StatusItemController.swift`, `StatusPanel.swift`,
  `SettingsWindowController.swift`, with their tests and the real-click
  acceptance gate. See `docs/lessons_learned.md`, the 2026-10-17 status-item
  entries, and PKM knowledge #253. Don't substitute `MenuBarExtra`,
  `NSPopover` or button actions.
- **Glyph:** the lamp-lens template image, plus a dot in the most severe new
  lamp's color. If lamps are lit but all acknowledged, draw a 1.5 pt ring in
  the most severe lit color; otherwise leave the lens plain. Accessibility text
  names the lit lamps and appends " (acknowledged)" when only acknowledged items light one.
- **Panel**, as in the mockup:
  - header with "Checked HH:MM" and Check now
  - lamp strip: Speed, Errors, Link, OpenAI, Load
  - alert list, or "Nothing to report."
  - one row per model active in the last 3 hours: tok/s, usual, 3-hour
    sparkline
  - the lasting-shift prompt when present
  - footer with collector state, version with build help, and Open dashboard

  With several providers, the strip shows one lamp per signal across all
  providers, and the alert text names the provider.
  When a newly watched provider has stored models but none responded within
  the 14-day sidebar window defined in §9.2, its arrival note says so and
  offers no first model to open.

- **Acknowledging:** each open episode is identified by rule, provider, scope
  and onset. Acknowledging preserves the lamp and row but resets attention.
  New rows precede acknowledged rows; within each group sort by severity and
  recency. A new row offers Acknowledge; an acknowledged row shows a hollow
  diamond, acknowledgement time and Mark as new. Acknowledge all appears for
  more than one new rendered row and acts on those rendered rows. Collector
  health has its own acknowledgement and footer toggle; its acknowledged dot
  is a ring. Notifications keep their posting policy; acknowledgement removes
  the corresponding delivered notifications. No acknowledgement event is added.

  | Alert | Acknowledgement holds | Becomes new |
  |---|---|---|
  | Failed turns | Count is at most the acknowledged count | Another failure is counted, including between render and click |
  | Any rule | Severity is at most the acknowledged severity | Severity rises |
  | A new episode of the same rule and scope | Never, when onset differs | Always |
  | Collector health | All current problem keys were acknowledged | A new problem key appears |

  A worse value at unchanged severity does not make an alert new. Recreated
  episodes with the same natural key retain acknowledgement; rebuilds that
  change the key produce new alerts.

  The Collector footer toggle is offered only by the installed copy with a
  readable initialized database and a red Collector lamp, even before a
  successful run. A retained stale snapshot never enables writes.

### 9.2 Dashboard window

Sidebar: providers and their models (unconfigured providers dimmed, "Not set
up"), then Collector and Settings. A provider lists only the models with a response
in the last 14 days (`ModelDetail.sidebarWindow`, the longest chart range).
Display names are still made unique over every stored model, so a model
keeps its name when it leaves the sidebar and returns, and a stale model that is opened still
shows that name. A provider whose models are all older than the window shows "No responses in
the last 14 days" (`Copy.noRecentModels`), dimmed; one with no stored response shows "No
responses yet". The arrival note's first model and the models it names come from the same
recent list. If stored models are all idle, the arrival note states that none responded within the window. The sidebar foot shows the version with build help. Model view, as in the mockup:

- Lamp strip, including Collector.
- Alert list.
- **Speed against usual:**
  - range control (6h, 24h, 7d, 14d)
  - readouts: last-hour tok/s with usual, median response time with usual
  - hourly speed-index dots colored by severity
  - dashed usual line
  - incident bands
  - failed-turn markers
  - usual explanation
  - **Accept as usual**
  - drift note
- **Prompt sizes:** a bucket histogram of the last 3 hours against usual.
- **Workload,** last 3 hours against usual:
  - median prompt
  - responses per hour
  - active sessions
  - cached-input share
  - reasoning share of output
  - subagent share
  - effort mix

  Workload usual is the median over the same 14 active days, counting active
  hours only, not matched to hour of day **(my call)**. It describes Kevin's
  own behavior, so it isn't gated by acceptance and excludes nothing. It
  triggers no alerts except the large-prompt rule, which uses a fixed
  threshold.
- **Events:** slowdowns, speedups, failures, disconnects, incidents, baseline
  acceptances (with Undo), and collector problems.

Charts use Swift Charts. Colors, type and copy follow the visual design doc.
Barlow Semi Condensed is bundled (OFL 1.1, license in the app's Resources) and
registered at launch.

### 9.3 Collector management

The app installs and controls the job directly. It doesn't use
`SMAppService.agent` **(my call)**. The reasons:

- The interval must be editable.
- The job stays visible to `launchctl` and Launchmaster.
- It matches Model Sentinel.

| Action | Mechanism |
|---|---|
| Turn on | Write `~/Library/LaunchAgents/local.utilities.telltale.collector.plist`: `ProgramArguments` = [this app's executable, `--collect`], `StartInterval`, `RunAtLoad`, `ProcessType` Background, stdout and stderr to the collector log. Then `launchctl bootstrap gui/$UID <plist>`. |
| Turn off | `launchctl bootout gui/$UID/local.utilities.telltale.collector`, then remove the plist |
| Change interval | Rewrite the plist, then bootout and bootstrap. 1–60 minutes, default 5. |
| Run now / Check now | `launchctl kickstart gui/$UID/local.utilities.telltale.collector` |
| Repair | Shown when the plist's executable path doesn't match the running app (app moved or replaced). Rewrites the plist and reloads. |
| Show log file | Reveal the log in Finder |

Collector lamps:

| Lamp | Lit green when | Lit red when |
|---|---|---|
| Installed | Plist exists and points to this app | Collector is on in settings, but the plist is missing or points elsewhere |
| Loaded | `launchctl print gui/$UID/<label>` succeeds | On, but not loaded |
| Last run | The last run record succeeded | The last run failed. The message says why and when the next try is. |
| On schedule | The last run started within 2× the interval + 1 minute | Overdue |

- **When the collector is off** by choice, its lamps are unlit, not red, and
  the panel footer says "Collector off. Turn it on to keep watching."
- **Truth comes from run records** in the database, which the collector
  writes at start and end of each run. `launchctl print` is used only for
  Loaded, because its output format isn't stable.
- **The UI app checks collector health every minute** and posts the
  Collector health notification. The collector can't report its own absence.
  If both the app and the job are down, nothing alerts; the panel says so on
  next open.
- **Collector acknowledgement:** a red job/run lamp or a repair requirement
  uses the key `collector`; each format or read problem uses `source.<id>`.
  Changes among job problems or among problem kinds for one source retain the
  acknowledgement. A successful non-red check clears it; a failed assessment
  does not. A problem that clears and returns with the same key while the app
  is quit remains acknowledged (the Collector acknowledgement limit).

### 9.4 Settings

| Section | Contents |
|---|---|
| Rules | One row per rule (§7.4): toggle, parameters, Notify, Notify when it clears, Reset to default |
| Collector | Interval, on/off |
| Watched status components | Checklist from the status page's component list |
| Data | Retention, plus "Rebuild from Codex logs", which re-ingests the last 30 days |
| General | Open at login; Dashboard appearance: Dark (default), Light or Match system **(my call)**. The panel always follows the system. |

The provider state line can show `Copy.readProblem` for a read failure.

The app writes settings to the `settings` table. The collector reads them at
the start of each run.

## 10. Status source: OpenAI

- `GET https://status.openai.com/proxy/status.openai.com` returns
  `summary.ongoing_incidents`, `summary.components` (ids to names) and
  `summary.affected_components`.
- `GET …/proxy/status.openai.com/incidents/{id}` returns `incident.{name,
  status, published_at, updates[].{published_at, to_status},
  component_impacts[].{component_id, status, start_at, end_at}}`.
- Fetched once per collector run. Store incidents and their history. Fetch
  details for new or changed incidents only.
- `https://status.openai.com/feed.rss` is a fallback for titles and links.
- **Do not use `/api/v2/summary.json`.** On 2026-10-27 it reported "All
  Systems Operational" during an active incident (page `updated_at` was
  Oct 16).
- Network failures mark the source "unavailable since HH:MM". They don't
  fire the incident rule.

## 11. Privacy and safety

- Telltale keeps metadata only: timestamps, token counts, model, effort and service tier,
  error codes and messages, status-page incidents.
- The only network calls are to the status pages. There's no telemetry.
- Provider access follows §6 and the read-only SQLite contract cited in §2.
  For a closed WAL database, Telltale checks that the selected source is a regular
  file and records its size and modification date, then uses `clonefile` with
  `CLONE_NOFOLLOW` into a private mode-0700 `codex-snapshots` root and per-read
  directory on the same volume as its database. It rejects an existing insecure
  or symlink root. If the source changes or a WAL appears during cloning, it
  discards the clone as busy. It opens the clone without following links and
  verifies a regular file with a different device/inode pair and a complete WAL
  SQLite header before changing its journal bytes through the open descriptor.
  The clone is read through a normal read-only SQLite connection, then removed.
  Cleanup failures are read failures; leftover entries are removed before another
  clone is made, without following symlinks. A clone failure, including an
  unsupported or cross-volume filesystem, takes the closed-file skip path. No
  full-copy or immutable-mode fallback is used.
- **This repository is public.** Tests and fixtures use synthetic data with
  conspicuously fake ids. Real logs may be read for manual checks, but are
  never committed, and screenshots must not show real session ids.

## 12. Evidence the defaults rest on

The analysis scripts were scratch work outside the repo. Results were taken
from Kevin's Oct 13–27 Codex data: 602 rollouts, 27,061 responses.

- Size-adjusted anomalies matched OpenAI's Oct 13 incident. They also found
  unposted events:
  - Oct 16–17: a full day 1.3–1.6× faster
  - Oct 22 evening: slow, with capacity failures
  - Oct 26 morning: slow, with 4 capacity failures
  - Oct 27: slow from 08:30, before OpenAI's 10:02 post
- With 15%/15 minutes, the stricter clear and the idle end, the rule produced
  7 slowdown notifications over Oct 20–27, using a 7-day trailing baseline.
  The production baseline in §8 excludes flagged hours, so it stays further
  from a bad week than that replay did.
- The replays keyed usual by model and bucket only. Rechecked with effort in
  the key, every anomaly above remains:
  - Oct 13: 0.64–0.72×
  - Oct 17: 1.3–1.7×
  - Oct 22 evening: about 0.8×
  - Oct 26 morning: 0.63–0.77×

  Oct 27 08–09 was milder at about 0.8×: that day was almost all high
  effort, which explained part of the dip. It still crosses the 15% trigger.

## 13. Build, test and release

Follow Brew Version's layout and conventions. Project folder `telltale/`:

- SwiftPM package.
- Swift 6 language mode, macOS 27.
- No external package dependencies. Vendored zstd is a C target.
- Library targets:
  - `TelltaleCore`: models, rule engine, baseline, storage.
  - `TelltaleCodex` and `TelltaleOpenAIStatus`: plugins.
- One executable target, `Telltale`.
- `Makefile` targets: `build`, `test`, `release` (app bundle signed with a stable identity,
  `CodexBar Local` by default, never ad-hoc: an approved deviation, as in `anker_charge_monitor`),
  `snapshots`, `acceptance`.

**Tests (all required, per the repo’s Testing Scope):**

The maintained dashboard snapshots include an idle sidebar in light and dark appearances.

- **Unit**
  - Rollout parsing: plain and `.zst`, truncated zstd frames, the
    plain-to-compressed handoff by ordinal, fork-prefix duplicates, cursor
    resume mid-response.
  - `thread_turns` and `logs` parsing, including format-drift detection.
  - Status JSON parsing.
  - Rule engine: fire, hysteresis clear, flapping suppressed, idle end, thin
    data, both directions, severity escalation, catch-up across missed runs.
  - Baseline: flagged exclusion, 14 active days, bucket minimum, epochs,
    accept and undo, cold start.
- **Integration**
  - The collector run against a synthetic `CODEX_HOME`-style tree and a
    temporary database.
  - Plist generation, and launchctl calls through an injected command runner
    (a fake `launchctl`, as Model Sentinel's tests use).
  - Tests must never touch the real `~/Library` or `~/.codex`. Inject every
    path; don't rely on `HOME` alone (see the CodexBar isolation lesson:
    Foundation caches ignore `HOME`).
- **Snapshots:** panel quiet, panel alerting, acknowledged, lasting-shift prompt, dashboard
  model view, collector view in its problem state, and settings. Light and
  dark, inspected like Brew Version's.
- **Acceptance:** the ported real-click status-item gate. A live check that
  a launchd-run collector posts a notification. The §4 spike, run first.

**Release and deploy:**

- Add `tools/deploy_telltale.mjs` modeled on `tools/deploy_brew_version.mjs`.
  It installs to `/Applications/Telltale.app`.
- Add a section to `docs/local_deployment_sync.md`.
- Add a README entry and Validation Matrix lines in `AGENTS.md`/`CLAUDE.md`.
- After deploying, if the collector is on, the app's Repair check confirms
  the plist still points to the installed executable.
- Version bump rules per the repo.

## 14. Left to the builder

- Database schema and indexes, within §4's list.
- How the UI notices database changes.
- Sparkline and chart details within the visual design.
- Exact copy beyond the examples, following the visual design's copy rules.
- How usual is cached between recomputations.

## 15. Risks

- **Undocumented Codex formats.** Mitigated by validation and a visible
  format-problem state (§6.5), and by sources being independent: failures
  still work if rollout parsing breaks.
- **15-hour retention in `logs_2.sqlite`.** If the collector is off longer,
  disconnect history has gaps. Shown, not hidden.
- **Notifications from a launchd-run app binary.** Spiked first (§4), with a
  fallback.
- **Status-page JSON is an undocumented proxy endpoint.** RSS is the
  fallback, and failure is shown as "status unavailable".
