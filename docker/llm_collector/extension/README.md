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

The collector receives only hostname/count deltas, a generated client ID, a
sequence number, and an event timestamp. Request and response content is not
sent.

The popup also shows the current collector connection state. A green indicator means the extension received a valid response from the authenticated `/counters` endpoint. A red indicator distinguishes an unreachable collector, timeout, API-key rejection, server error, invalid response, or missing extension configuration.

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

## Installation

1.  Open your web browser's extension management page (e.g., `chrome://extensions`).
2.  Enable "Developer mode".
3.  From the `llm_collector` project root, run `./setup.sh` so it generates `extension/config.local.js`.
4.  Click "Load unpacked" and select this `extension` directory.

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
    of session capture/debug storage and remain after **Clear Pending**.

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
    startup, installation and **Force Push** request the same drain. Force Push
    confirms the request, while subsequent status reports delivery errors and
    outstanding counts. **Clear Pending** clears only queued observations and
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
    again every ten seconds while open, and **Reload** triggers an immediate
    retry. No connection polling runs while the popup is closed.

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

The capture is on by default. Use **Capture: On/Off** in the popup to switch it
(the choice is kept), and **Clear Capture** to start a clean test. It holds the
newest 3000 requests within about 8 MB in `chrome.storage.session`: it survives
the service worker stopping, is cleared when the browser quits, and is never
sent to the collector. **Export JSON** includes it under `capture`.

## Validation

Run the dependency-free extension tests with Node.js:

```bash
node --test test_*.js
```

For a manual failure-path check, open the popup with the collector running, stop the collector, and use **Reload**. The indicator should change from green to red within two seconds. Start the collector and reload again to verify recovery.

## Customization

The extension is designed to be easily customizable for different LLM providers. To add support for a new provider, you will need to modify the `background.js` file to:

1. Add the required host permission and observation pattern if the existing
   manifest/filter does not cover the provider.
2. Add a narrow host/path rule to `HOST_ALLOW`; add `HOST_DENY` rules for noisy
   endpoints where appropriate.
3. Reload the extension and use its debug buffer to verify that one user send
   produces one count without counting telemetry or background traffic.
