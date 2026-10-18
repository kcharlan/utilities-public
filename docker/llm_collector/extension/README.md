# Browser Extension

This directory contains the Chromium Manifest V3 extension that counts selected
outbound LLM requests.

## Functionality

The background service worker uses `chrome.webRequest` to observe matching
outbound POST requests. There is no injected content script and no response
body or token parser. Host/path allowlists identify likely prompt sends, a
short per-tab/host/path debounce suppresses bursts, and accepted events add one
request to the pending count for that hostname.

The service worker keeps the last 200 observed POST decisions in a debug buffer
that the popup shows and exports. The buffer is mirrored to
`chrome.storage.session`, so it survives the browser stopping the idle service
worker and is cleared when the browser quits; it is never written to disk
storage. Each record holds the hostname, path, and, when the URL carries one
(Google `batchexecute` calls do), only the `rpcids` query parameter, which
names the RPCs in the batch; other query parameters such as session ids are
not recorded.

The popup renders diagnostic fields and other dynamic list values as literal
text. Sanitized paths may contain decoded markup characters; those characters
cannot create elements or load resources in the popup.

The collector receives only hostname/count deltas, a generated client ID, a
sequence number, and an event timestamp. Request and response content is not
sent.

The popup also shows the current collector connection state. A green indicator means the extension received a valid response from the authenticated `/counters` endpoint. A red indicator distinguishes an unreachable collector, timeout, API-key rejection, server error, invalid response, or missing extension configuration.

## Appearance

The footer's **Appearance** button offers **Automatic**, **Meter** (tally bars
and cards), and **Native** (macOS-style grouped rows). The choice is stored
locally under `localStorage` key `llmUsageCounter.appearance`, with values
`auto`, `meter`, or `native`; it is not synced between devices. Automatic is
the default for missing, invalid, or unreadable preferences. It selects Native
when the platform is `macOS` or contains `Mac`, and Meter elsewhere. If saving
fails, the chosen skin still applies to the current popup and a notice explains
that it could not be saved.

Skins are CSS only, selected by `data-skin` on `<html>`; both share one static
popup structure. Polling updates only text slots and row lists, so listeners
stay bound and folds keep their open or closed state. `popup_appearance.js` is
the first script in `popup.html`, loaded without `defer` before any styles, so
the chosen skin is applied before the first paint; it must stay a separate file
because the extension's Manifest V3 CSP blocks inline scripts.

Both skins follow the system's light or dark setting. Open the menu with Enter
or Space, move with the arrow keys, and select with Enter or Space. Escape or
clicking outside closes it and returns focus to Appearance.

## Supported Providers

The extension currently supports tracking usage on the following platforms:

*   **OpenAI (ChatGPT):** `chatgpt.com`, `chat.openai.com`
*   **Perplexity:** `perplexity.ai`
*   **Google Gemini:** `gemini.google.com`, through either of two send paths:
    `StreamGenerate` on `gemini.google.com`, or the WebChannel endpoint
    `geminiweb-pa.clients6.google.com/v1/processSession` (first seen with
    Gemini 4 Argon). One WebChannel turn makes several POSTs (handshake, setup,
    prompt, end of turn, terminate beacon). The extension counts only the prompt
    message, protobuf field 2, by decoding the first byte of each `reqN___data__`
    form field; the counting classifier never decodes or stores prompt text.
    Transport retries count only previously unseen message IDs (`ofs + N`),
    including sparse or reordered batches. Invalid identities produce a
    `channel-invalid` diagnostic without counting. These counts are credited to
    `gemini.google.com`.
*   **Abacus.ai:** `abacus.ai`
*   **T3 Chat:** `t3.chat`
*   **Browser calls to provider APIs:** `api.openai.com` chat completions,
    responses, and completions, and Google `generateContent` /
    `streamGenerateContent` calls on `generativelanguage.googleapis.com` and
    other `googleapis.com` hosts. These are counted under the API hostname.

## Installation

1.  Open your web browser's extension management page (e.g., `chrome://extensions`).
2.  Enable "Developer mode".
3.  From the `llm_collector` project root, run `./setup.sh` so it generates `extension/config.local.js`.
4.  Click "Load unpacked" and select this `extension` directory.

## Release and update requirements

Every extension release must bump `version` in `manifest.json` in the same
change as the released code. Follow the existing versioning scheme; ask the
owner which increment to use if it is unclear. Releasing changed code under
the previous version is not permitted.

Before handing off an update, verify that the source and deployed manifests
declare the new version. Load or reload the extension and verify the browser's
Extensions page reports that version, then include it in the release report.
Preserve local configuration and browser accounting state during the update.

## Configuration

Do not edit `background.js` for local secrets. From the `llm_collector` project root, run `./setup.sh` (or `../setup.sh` from this `extension` directory). It reads `~/.config/llm_collector/secret.env` and generates `config.local.js` with:

*   `API_KEY`: Must match the collector server API key.
*   `COLLECTOR_URL`: The collector server URL, usually `http://127.0.0.1:9000`.

## How it Works

The extension's `background.js` script is the core of the extension. It performs the following functions:

1.  **Client ID Management:** The extension assigns a unique client ID to your browser to distinguish it from other instances. This ID is stored in local storage.

2.  **Request observation:** The extension uses `chrome.webRequest` to observe
    allowlisted POST request URLs.

3.  **Usage detection:** Each qualifying, non-debounced POST increments that
    hostname's pending request count by one. Gemini WebChannel prompt messages
    are classified by message type and durable transport identity instead and
    are not debounced. Updates to
    the pending counts are queued so overlapping updates are not lost.

4.  **Data Buffering:** `delivery.js` owns local accounting through a serialized
    transaction queue. It persists `llm_delivery_v2` with a stable client ID,
    acknowledged sequence, baseline marker, queued counts, and one immutable
    in-flight wire batch. A successful storage callback precedes publication.
    Pending includes both queued and unacknowledged counts. Failed local reads
    make counts unavailable; failed writes retain the last committed state and
    appear in delivery status.
    Counted diagnostics are published only after the observation write commits.
    Rejected observations produce a `recording-failed` diagnostic in the session
    debug buffer; the worker also retains the recording error in status through
    unrelated successful drains. A successful delivery cannot recover that
    rejected observation.

    Gemini channel history lives in the same local record as queued counts.
    A generated, persisted salt and SHA-256 of
    `JSON.stringify([salt, transportOrigin, transportPath, SID])` identify a
    channel; tab IDs are diagnostic metadata only. Neither the SID nor message
    payload is kept in accounting. Sorted disjoint inclusive intervals retain
    all observed message IDs, including setup/end messages, and commit atomically
    with new prompt counts. The salt and history survive worker suspension,
    extension disable/reload/update, and browser restart. They are independent
    of session capture/debug storage and remain after **Discard queued**.

    History is limited to 1 MiB serialized UTF-8, 4096 channel keys, 128 intervals
    per channel, and 16384 intervals overall. Adjacent IDs compact into intervals.
    At a limit, committed identities remain intact and known replays are still
    recognized without another write. New identities that exceed a limit are
    refused atomically with a `recording-failed` debug decision and a
    `channel-history-full` delivery error; no count is published. Stop provider
    sessions and explicitly decide operational history maintenance before
    resuming. Restarting the browser or reloading the extension does not clear
    history or recover refused observations. There is no automatic eviction or
    history-clearing lifecycle handler. Destructive maintenance requires an
    explicit operational decision with provider sessions quiescent.

5.  **Idempotent Submissions:** Concurrent pushes join one drain. Each sequence
    identifies a persisted batch whose deltas and timestamp remain unchanged
    through timeouts, lost acknowledgements and worker restarts. New observations
    queue separately. Only an acknowledgement with the exact sequence and an
    applied count of zero or the batch sum releases that batch. Sequence gaps
    retain it and expose an error; they never renumber an uncertain submission.

    Requests abort after five seconds, including response-body consumption.
    Body transport failures retry; malformed JSON remains a visible error.
    Network and server failures retry after
    1, 2, 4, 8, 16, then 30 seconds while the worker stays awake. Initialization,
    startup, installation and **Send now** request the same drain. Send now
    confirms the request, while subsequent status reports delivery errors and
    outstanding counts. **Discard queued** clears only queued observations and
    reports any outstanding submission it retained.

    Migration imports the represented legacy client, sequence and pending
    values without deleting the old keys. It durably marks the baseline as
    unresolved before recording observations. An authenticated, validated
    `/client_status` response resolves the sequence and marker together; offline
    restarts preserve this gate and cannot submit prematurely. This does not
    reconstruct already lost legacy history. Deploy the collector's receipt-
    preserving reset contract before using this delivery client.

6.  **Connection diagnostics:** Opening the popup asks the service worker to
    probe authenticated `/counters` with a two-second timeout. The popup checks
    again every ten seconds while open, and **Check again** triggers an immediate
    retry. No connection polling runs while the popup is closed.

    If the background worker cannot reply, the popup shows **Extension not
    responding** and recovery instructions. Previously confirmed capture
    values are marked **stale**; before the first reply they read **Unknown**.
    Capture, delivery, and export controls stay disabled until a successful
    status check restores current values.

## Full Request Capture

For working out how a site sends prompts, `capture.js` records every request
made by an LLM page (Gemini, ChatGPT, Perplexity, Abacus.ai, T3 Chat) to any
host, with any method and resource type. That is why the manifest requests
`<all_urls>`: a site can move its prompt traffic to a host the counter does
not watch. Requests from other sites are ignored. Each record holds:

*   method, resource type, initiator, tab and frame;
*   the URL, request body, and request and response headers, all redacted;
*   status, redirects, network errors, and duration.

Redaction (`capture_redact.js`) replaces the value of any query parameter,
form field, header or JSON member whose name looks like a credential or
session or account identifier (`SID`, `gsessionid`, `f.sid`, `at`, `verify`,
cookies, `Authorization`, API keys, account and device ids, and similar), plus
OAuth, `Bearer`, `SAPISIDHASH` and Google API-key tokens wherever they appear,
including percent-encoded. Valid JSON is inspected structurally: a sensitive
member's entire value is replaced, including objects, arrays, and scalar values.
Nested JSON and URL strings use the same policy. Header blocks carried in
`$httpHeaders` are recognized even when they contain only one line. `Location`,
`Content-Location`, `Referer`, `Refresh`, and `Link` URL targets are sanitized,
including relative targets. Unchanged query values keep their original encoding.
`user-<id>` path segments are masked in capture and debug records before storage
or console logging. Names stay visible, so the
capture shows which fields were present. Prompt text in request bodies is kept;
each body value is cut at 16 KB. Uploaded files are recorded as `<file>`.
Live JSON bodies are fully sanitized before truncation, so admission preserves
their safe prefix. Restored truncated JSON has no such provenance and is omitted
when it cannot be parsed. A malformed entry anywhere in a `Link` header causes
the entire container to be omitted.

Inspection is limited to 32 structural levels, 10000 visited values, and two
percent-decoding layers. Malformed JSON-looking content, invalid recognized
containers, and content that cannot be fully inspected are represented as
`<omitted>`, without retaining a raw prefix. An over-budget form keeps an empty
`formData` map and an `omitted` marker; an uninspectable header list keeps an
omission marker. Unsafe diagnostic records are discarded. Session records from
older workers are sanitized before publication and rewritten to session storage;
discarded records are counted without logging their original contents.

`chrome.webRequest` cannot see response bodies or WebSocket frames, so those
are never captured.

The capture is on by default. Use the **Record full requests from LLM pages** switch in the popup to change it
(the choice is kept), and **Discard capture** to start a clean test. It holds the
newest 3000 requests within a 6 MiB serialized UTF-8 budget. Debug holds at most
200 decisions within 256 KiB. Both use `chrome.storage.session`: they survive
the service worker stopping, are cleared when the browser quits, and are never
sent to the collector. **Export** includes records and each store's
`capturePersistence` / `debugPersistence` status. The Request capture fold shows **Storage: Working** when both stores are ready,
and names each pending or failed store otherwise. Its summary shows whether
capture is on and how many requests it holds.

Capture records are limited to 128 KiB, bodies to 64 KiB, body strings to 16 KiB
(and 16384 characters), and URL/header strings to 8 KiB. Raw bodies over 1 MiB
are omitted before joining or decoding. Content is sanitized before reduction.
Oversized forms omit their content; oversized records omit bodies and then
oldest redirect/header detail, retaining truncation indicators and safe
metadata. Records whose metadata cannot fit are dropped. Restoration, new
records, and late lifecycle updates all respect these limits. Evicted requests
cannot return through late completion events; retained records are their only
long-lived owner.

Listeners register immediately and queue sanitized lifecycle events until both
record and enable-setting initialization settle. Waiting work is bounded to
1000 events and 1 MiB; additional events increment `captureDiagnostics.droppedEvents`
without retaining content. A failed enable-setting read refuses capture until
the setting can be read or explicitly saved successfully. A failed session read
allows bounded sanitized memory staging but never overwrites unread records.
The `reload_capture` runtime command retries failed reads and merges restored
records before staged records; it also retries failed writes. **Discard capture**
intentionally replaces only the capture key and reports success after its empty
write completes. A failed clear reports failure and can be retried.

Serialized budgets differ from Chrome's session-memory accounting. Quota
callback errors evict the oldest half and retry at most three times, including
an empty store. Other failures, or exhausted quota retries, leave bounded memory
records and a visible persistence error. A later successful write clears that
error. Writes are serialized by generation, so an obsolete retry cannot replace
a newer change or clear. Diagnostics failures remain separate from durable
prompt-count accounting.

## Validation

Follow the project [Development and tests](../README.md#development-and-tests)
section for the tracked environment and complete collector, snapshot, shell,
Node, and Chromium popup suites.

For a manual failure-path check, open the popup with the collector running, stop the collector, and use **Check again**. The indicator should change from green to red within two seconds. Start the collector and use **Check again** to verify recovery.

**Export** downloads diagnostic JSON and copies the same text to the clipboard.
A clipboard failure is reported after the successful download.

## Customization

The extension is designed to be easily customizable for different LLM providers. To add support for a new provider, you will need to modify the `background.js` file to:

1. Add the host to `URL_FILTERS`, and to the manifest's `host_permissions` if
   the existing entries do not cover it.
2. Add a narrow host/path rule to `HOST_ALLOW`; add `HOST_DENY` rules for noisy
   endpoints where appropriate.
3. Reload the extension and use its debug buffer to verify that one user send
   produces one count without counting telemetry or background traffic.
