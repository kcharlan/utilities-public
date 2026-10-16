# LLM Collector Popup Skins Implementation Plan

**Goal:** Replace the LLM Usage Counter extension popup with one reorganized layout that has two skins, Meter and Native. Both skins support light and dark appearance, and the popup gets an Appearance setting (Automatic, Meter, Native). Add a Chromium browser test category to the project, with its dependencies tracked so every venv rebuild and every `migrate.sh` run installs them.

Every design and scope decision is settled in this document. Implement it as written. Paths are relative to the repository root unless a section names another base.

## Execution scope

- Work on a local feature branch `llm-popup-skins` in the existing checkout, created from current `main`.
- Commit once per task (Task 1, Task 2). Each commit has an imperative subject and a body saying what changed and why. Before each commit, inspect the staged file list and staged diff for sensitive data, as required by `agents.md` (**Public repository: no sensitive data**). Every fixture in this plan is synthetic.
- Execution ends with both commits on the local branch and the full suite passing. Pushing, opening a PR, merging and deployment are outside this plan's execution. **Deployment** below documents the post-merge procedure.
- The installs in **Development environment** are part of this plan: `pip install` of the tracked dev requirements and `playwright install chromium`. Install into the existing `docker/llm_collector/.venv`. Never delete or recreate that venv.
- Do not run `docker/llm_collector/migrate.sh` (with or without `--dry-run`); it touches live installs. Validate the edited script with `bash -n` and by running its `source_test` steps by hand, as listed in each task's acceptance section.

## Sources

Read these before starting:

| Area | Source |
|---|---|
| Project overview, tests, deployment | `docker/llm_collector/README.md`, `docker/llm_collector/INSTALLATION.md` |
| Extension behavior, release rules, validation | `docker/llm_collector/extension/README.md` (**Release and update requirements**, **Validation**) |
| Popup today | `docker/llm_collector/extension/popup.html`, `docker/llm_collector/extension/popup.js` |
| Popup tests | `docker/llm_collector/extension/test_popup_status.js` |
| Status payload | `docker/llm_collector/extension/background.js` (`get_status`, `clear_pending`, `force_push`, `set_capture`, `clear_capture`, `get_capture` handlers); `delivery.js` `status()`, `run()`, `clearQueued()`; `collector_status.js` |
| Suite runner | `docker/llm_collector/migrate.sh` `source_test()` |
| Browser-test helpers | `tools/testkit.py` `guard_browser_errors` |
| Lessons | `docs/lessons_learned.md`, entries dated 2026-10-15: *Verify extension release identity during deployment* and *Redacted diagnostics still need text-only rendering* |
| Deployment | PKM project `utilities-public` (id 6), knowledge entry 250: deploy local copies from merged main |
| Approved design | [`docs/llm_collector_popup_skins_mock.html`](llm_collector_popup_skins_mock.html). Open it in a browser. It is the visual reference for both skins, both themes and the Appearance menu. It uses invented data and is not shipped. Where it differs from this plan, this plan wins. |

The extension is a browser extension, so the repository's **UI Shapes** rules (Preact, vendored stack) do not apply (rule 0). Keep the existing plain JavaScript.

## Current state (verified in code)

- `popup.html` is a 360 px page with one inline `<style>` block and `popup.js` loaded with `defer`. Element IDs: `status`, `statusLabel`, `statusDetail`, `persistenceStatus`, `reload`, `forcePush`, `reset` (Clear Pending), `export`, `captureToggle`, `clearCapture`, `notice`, `list`, `out` (export textarea).
- `popup.js` functions: `$`, `fmt`, `textElement`, `counterRow`, `setNotice`, `renderConnectionStatus(status, configError)`, `renderCaptureState({captureEnabled, captureCount})`, `renderPersistenceStatus({capturePersistence, debugPersistence})`, `showCheckingStatus`, `renderStatus(data)`, `sendMessageWithTimeout`, `refresh({showChecking})`, `bind`, plus a `DOMContentLoaded` handler that binds the six buttons, runs `refresh`, and polls every 10 s.
- `renderStatus` rebuilds `#list` on every poll: server totals (top 10), pending (top 10), a delivery error line, `client_id`/`seq`/debug count, and the last five debug records. It uses `innerHTML` only for static section titles. The catch block in `refresh` writes a static help block through `innerHTML`.
- `get_status` returns `...persistence()` (`capturePersistence`, `debugPersistence`), the `delivery.status()` fields, `serverCounters`, `collectorStatus`, `collectorUrl`, `debug`, `captureEnabled`, `captureCount` and `configError`. The `delivery.status()` fields are `available`, `client_id`, `seq` (last acknowledged sequence), `pending` (queued plus in-flight deltas, per host), `inFlight` (`null` or `{client_id, seq, deltas, ts}`) and `deliveryError`.
- **The status payload exposes no retry time.** The mock's "retry in 8 s" is not available. Do not change `background.js` or `delivery.js` to add it; the popup shows "N waiting, retrying" instead.
- `clear_pending` replies `{ok, cleared, inFlight}`, where `inFlight` is a count (`delivery.js` `clearQueued`). That differs from the `inFlight` in `get_status`, which is a batch object.
- The extension reads `extension/config.local.js` (generated by `setup.sh`, ignored by Git), which sets `globalThis.LLM_USAGE_CONFIG = { collectorUrl: "…", apiKey: "…" };`.
- Collector contract used by the extension:
  - `GET /counters` with the `X-API-KEY` header returns `{"counters": {host: n}}`. A 401 or 403 means authentication failed.
  - `GET /client_status?client_id=…` returns `{"client_id": …, "last_seq": n}`.
  - `POST /add` with a JSON batch `{client_id, seq, deltas, ts}` returns `{"ok": true, "last_seq": seq, "applied": n}`, where `applied` is 0 or the sum of `deltas`.
  - `GET /health` returns 200.
- Tests are dependency-free Node (`node --test test_*.js` from `extension/`). `test_popup_status.js` loads `popup.js` in a `vm` context with fake elements. `attachStatusList` supplies fake nodes that support `style`, `appendChild`, a `textContent` getter and setter, and an `innerHTML` setter that records every string, so tests can assert that dynamic values never reach the HTML parser. Fake nodes are plain objects, so assigning scalar properties (`className`, `title`, `disabled`, `checked`, `open`) works without harness changes. Nested writes need the factory to supply the object first: the `attachStatusList` nodes have `style` but no `dataset`. `setAttribute` and `replaceChildren` are not supported.
- **Python environment:**
  - `docker/llm_collector/.venv` is Python 3.14, created from `/opt/homebrew/opt/python@3.14/bin/python3.14`, with Flask 3.1.3, gunicorn and pytest 9.1.1. It is ignored by Git.
  - The only tracked requirements file is `collector/requirements.txt` (`flask==3.1.3`, `gunicorn==26.2.0`). The Dockerfile installs exactly that file.
  - `migrate.sh` `source_test` creates `.venv` with a bare `python3 -m venv` when it is missing. It then installs `collector/requirements.txt` plus an unpinned `pytest`, and runs `pytest collector snapshots`, `tests/test_local_config.zsh` and `node --test extension/test_*.js`.
  - `agents.md` lists `migrate.sh` among the scripts that create venvs with a bare interpreter. Its Validation Matrix has no `llm_collector` entry.
- `manifest.json` version is `0.5.1`.

## Design

**One layout, two skins.** `popup.html` holds a single static structure. Skins are CSS only, selected by `data-skin="meter"` or `data-skin="native"` on `<html>`. There is no skin-specific markup and no skin-specific JavaScript branch, apart from resolving Automatic.

**Static skeleton, dynamic slots.** Buttons, the capture switch and the three folds are static HTML, bound once. Polling refreshes only text slots and row lists. That keeps listeners attached and keeps folds open or closed across the 10 s poll. `renderStatus` never rebuilds a fold.

**Layout, top to bottom:**

1. **Header** (`#status`, `data-state` = `connected` | `error` | `checking`): app name "LLM usage" (shown in Meter, hidden in Native), a status mark, `#statusLabel` and `#statusDetail`.
   - Keep every label and detail string that `renderConnectionStatus` produces today. In the `unreachable` and `timeout` states, append " Counts keep queuing here and send once it is back." to the detail.
   - Meter shows the label in a pill and the detail as a muted line under the header row. In the `error` state, the detail line becomes a red alert box.
   - Native shows a colored badge (check mark, or exclamation in `error`; amber with no glyph in `checking`), the label in bold, and the detail as its subtitle.
   - *Deviation from the mock:* the mock's Meter hid the detail and used a separate alert element. Here one `#statusDetail` element serves both skins and keeps the latency visible.
2. **Requests register** (`#registerHeading` with `#registerTotal`, and the row list `#register`): one row per host, merging `serverCounters` with `pending`, sorted by total plus queued, descending, top 10.
   - Each row has the host (ellipsized, full value in `title`), a "+N queued" marker when the host has pending counts and the collector is connected, and the count.
   - Meter adds a proportional bar per row: an element `.bar` holding `.bar-total` and `.bar-queued`. Their widths are a percentage of the largest row's total plus queued, set with `element.style.width`. Native hides `.bar`.

   States:

   | Condition | Heading | Total | Rows |
   |---|---|---|---|
   | `configError` set | "Setup needed" | empty | One text row with `configError` |
   | `available === false` | "Requests" | empty | One text row: "Counts unavailable: {deliveryError, or 'local delivery storage failed'}" |
   | collector connected | "Requests since last reset" | sum of `serverCounters` | merged rows; if none: "No requests yet. Send a prompt on a supported site and it shows up here." |
   | collector not connected | "Waiting to send" | sum of `pending` | pending rows with their pending count and no marker; if none: "Nothing waiting to send." |
   | `refresh` fails (no reply from the service worker) | "Extension not responding" | empty | Text rows: "Check again to wake the background worker." and "If it still fails, reload the extension from the browser's Extensions page and reopen this popup." |
3. **Delivery fold** (`<details id="deliveryFold">`). The summary shows "Delivery" and `#deliveryState`:
   - `deliveryError` set: "{pending sum} waiting, retrying" (warning tone);
   - pending > 0: "{n} queued" (warning tone);
   - otherwise "Up to date";
   - `available === false`: "Unavailable" (error tone).

   The body (`#deliveryDetails`) has key-value rows:

   | Row | Value |
   |---|---|
   | Queued | pending sum minus the `inFlight.deltas` sum |
   | Sent, unconfirmed | "{in-flight sum} in batch {inFlight.seq}", or "0" |
   | Last error | only when `deliveryError` is set; error tone |
   | Sequence | `seq` |
   | Client | `client_id` in monospace, full value in `title` |

   Below the rows are the actions **Send now** (`#forcePush`, disabled when pending is 0) and **Discard queued** (`#reset`, destructive, disabled when Queued is 0). The fold opens automatically only when `deliveryError` changes from empty to set between two renders, so the user's choice is never overridden on later polls. Track the previous value in a module variable.
4. **Request capture fold** (`<details id="captureFold">`). The summary shows "Request capture" and `#captureState`: "On, {count} held" or "Off". It is in error tone when either persistence state is `error`.

   The body holds the switch, rows, and one action:
   - The switch is `<input type="checkbox" role="switch" id="captureToggle">`, labeled "Record full requests from LLM pages".
   - Rows: Held (`#captureHeld`, "{n} requests"), Kept until ("Browser quits"), and Storage (`#persistenceStatus`).
   - `#persistenceStatus` reads "Working" when both states are ready. Otherwise it lists each store that is not ready in the existing format, for example "Debug persistence: error (synthetic read failure)".
   - **Discard capture** (`#clearCapture`, destructive) is disabled when the count is 0.
5. **Recent decisions fold** (`<details id="logFold">`). The summary shows "Recent decisions" and `#logState`: "{debug.length} logged" or "None". The body (`#logList`) lists the last five debug records, newest first. Each record shows:
   - the time (`toLocaleTimeString`);
   - the decision, in success tone for `counted`, error tone for `recording-failed`, `channel-invalid` and `config-missing`, neutral otherwise;
   - `host + path`, plus ` [rpcids=…]` when present, in monospace;
   - the `reason` line when present.

   Empty state: "Nothing observed since the browser started."
6. **Footer** (`position: sticky; bottom: 0`), left to right:
   - `#notice` (`role="status"`). With no notice, it shows "Version {chrome.runtime.getManifest().version}". Guard the call so it does nothing when `getManifest` is unavailable, as in the Node `vm` context.
   - `#appearanceButton` (sliders icon from the mock, `aria-label="Appearance"`, `aria-haspopup="menu"`, `aria-expanded`).
   - **Check again** (`#reload`).
   - **Export** (`#export`, primary).

   The Appearance menu (`#appearanceMenu`, `role="menu"`, three `role="menuitemradio"` buttons with `aria-checked`) opens above the footer.
   - On open, focus moves to the checked item.
   - ArrowDown and ArrowUp move focus between items, wrapping at the ends. Enter or Space selects the focused item.
   - The menu closes on selection, on Escape and on a click outside it, and returns focus to `#appearanceButton` on close.

**Copy changes:**

| Old | New |
|---|---|
| Reload | Check again |
| Force Push | Send now |
| Clear Pending | Discard queued |
| Export JSON | Export |
| Capture: On (n) / Off (n) | Switch "Record full requests from LLM pages", plus summary "On, n held" / "Off" |
| Clear Capture | Discard capture |
| Server totals / Pending (queued or unacknowledged) | One register: "Requests since last reset" or "Waiting to send" |
| Capture persistence: ready · Debug persistence: ready | Storage: Working (details appear only on error) |
| Recent Debug Logs | Recent decisions |

Keep the existing `setNotice` result messages unchanged ("Clearing pending data…", "Queued data cleared.", "Queued data cleared; outstanding submission (n) retained.", "Clear failed: …", "Requesting pending-data push…", "Push requested.", "Push failed: …", "Full capture turned on/off.", "Capture toggle failed: …", "Capture cleared.", "Clear capture failed: …", "Exporting diagnostics…", "Export failed: …"). The tests assert them. The export success message changes as described under **Export**.

**Text-only rendering.** Every dynamic value goes through `textContent` or `textElement`. Remove every `innerHTML` assignment from `popup.js`, including the static titles and the `refresh` catch-block help, which becomes the text rows above. Clear a container with `el.textContent = ""`, which works in both the real DOM and the fake nodes; do not use `replaceChildren`. Set tones with `className`, for example `state warn`, not `dataset`.

**Export.** Remove the `#out` textarea. Reviewing the exported file shows exactly what a debugging session receives, so the textarea preview is no longer needed. Keep the file download exactly as today (`llm_usage_export_{timestamp}.json`, same payload fields). Copy with `navigator.clipboard.writeText(json)`.
- On success, the notice reads "Exported and copied to clipboard."
- If `navigator.clipboard` is missing or the call rejects, the notice reads "Exported. Copy to clipboard failed: {message}" in success tone, because the download happened.
- Remove the `document.execCommand("copy")` path.

**Appearance setting.**
- The preference lives in `localStorage` under the key `llmUsageCounter.appearance`, with the values `auto`, `meter` and `native`. A missing value, an invalid value or a read that throws means `auto`. Wrap every read and write in try/catch.
- New file `extension/popup_appearance.js`, loaded as the first element in `<head>` after `<meta charset>`, with no `defer` or `async`. MV3's extension CSP blocks inline scripts, so this must be a file.
  - On load it sets `document.documentElement.dataset.skin` synchronously, so the popup never draws the wrong skin first.
  - It exposes `globalThis.LLMPopupAppearance = { PREF_KEY, readPreference(storage), writePreference(storage, value), resolveSkin(pref, platform), applySkin(doc, storage, platform), currentPlatform() }`.
  - `currentPlatform()` returns `navigator.userAgentData?.platform || navigator.platform || ""`.
  - `resolveSkin("auto", platform)` returns `"native"` when `platform === "macOS"` or `/Mac/.test(platform)`, otherwise `"meter"`. `resolveSkin` returns explicit `meter` and `native` unchanged.
  - `writePreference` returns `true` on success and `false` when storage throws.
- `popup.js` uses that module. Choosing a menu item writes the preference, applies the skin immediately and closes the menu. When the write fails, the skin still changes for this popup session and the notice reads "Appearance applied for now; it could not be saved."
- Menu labels and hints:
  - "Automatic", hinted "Native on this Mac" or "Meter here", using `resolveSkin("auto", currentPlatform())`;
  - "Meter", with no hint;
  - "Native", hinted "macOS style".

  The menu footer reads "Light and dark follow your system setting."

**Light and dark.** Set `:root { color-scheme: light dark; }`. Each skin defines its color tokens for light, with a dark override inside `@media (prefers-color-scheme: dark)`.
- Take the token values from the mock's `[data-skin="…"]` and `[data-skin="…"][data-theme="dark"]` blocks. The mock's `data-theme` attribute is only a demo device; the extension uses the media query.
- Respect `prefers-reduced-motion`. Keep visible `:focus-visible` outlines in both skins.
- There is no theme override separate from the system appearance.

**Size and type.** The body is 360 px wide with no horizontal scrolling. The browser caps popups at 600 px tall and scrolls the document past that; the sticky footer stays visible while scrolling.
- Meter uses `"Avenir Next", Avenir, "Segoe UI", sans-serif`, with numerals in `"DIN Alternate", Bahnschrift, "Avenir Next", sans-serif` and `font-variant-numeric: tabular-nums`.
- Native uses `-apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif`.
- Monospace everywhere: `ui-monospace, "SF Mono", Menlo, Consolas, monospace`.
- No bundled fonts.

**Version.** The release is `0.6.0`, set in `extension/manifest.json` once, in Task 2.

## Development environment

Both tasks depend on this setup. Task 1 creates it.

New tracked file `docker/llm_collector/requirements-dev.txt`:

```text
# Everything the full llm_collector test suite needs, including the Chromium
# popup tests. The collector container installs only collector/requirements.txt.
-r collector/requirements.txt
pytest==9.1.1
playwright==1.64.0
```

pip resolves Playwright's own dependencies (`greenlet`, `pyee`) from that pin. The Chromium build is tied to the Playwright version and is installed with `python -m playwright install chromium`, which does nothing when the matching build is already cached.

From `docker/llm_collector`:

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
```
```bash
.venv/bin/python -m playwright install chromium
```
```bash
.venv/bin/python -m pip check
```

Expected: the install succeeds, Chromium downloads or is reported as present, and `pip check` prints `No broken requirements found.`

Make every rebuild path install the same set:
- **`migrate.sh` `source_test()`:**
  - Create a missing venv from `LLM_COLLECTOR_PYTHON`, defaulting to `/opt/homebrew/opt/python@3.14/bin/python3.14`. That matches the Dockerfile's Python 3.14 and the current venv. If the interpreter is not executable, exit with: "Python 3.14 not found at $LLM_COLLECTOR_PYTHON. Install it with 'brew install python@3.14' or set LLM_COLLECTOR_PYTHON."
  - Replace `-m pip install -r "$SOURCE_DIR/collector/requirements.txt" pytest` with `-m pip install -r "$SOURCE_DIR/requirements-dev.txt"`.
  - Add `"$SOURCE_DIR/.venv/bin/python" -m playwright install chromium` after the install.
  - Change the pytest call to `-m pytest "$SOURCE_DIR/collector" "$SOURCE_DIR/snapshots" "$SOURCE_DIR/extension"`.
  - Update the dry-run log line to name the dev requirements and the Chromium install.
  - Keep `pip install --upgrade pip`.
- **Docs:** `docker/llm_collector/README.md` gets a **Development and tests** section listing the three setup commands above, then the three suite commands from Task 2's acceptance section (pytest, zsh, Node). `INSTALLATION.md` links to it from its prerequisites.
- **`agents.md`:**
  - Remove `plus docker/llm_collector/migrate.sh` from the bare-interpreter example list in **Execution Guidance for Agents**, since the script no longer uses one. The new Validation Matrix entry below records that agents still never run it.
  - Add this Validation Matrix entry after `div_conv`:

    ```markdown
    - `docker/llm_collector` (from `docker/llm_collector/`):
      - Setup: `.venv/bin/python -m pip install -r requirements-dev.txt`, then `.venv/bin/python -m playwright install chromium`.
      - `.venv/bin/python -m pytest collector snapshots extension` (collector, snapshot and Chromium popup tests; no skips).
      - `zsh tests/test_local_config.zsh` and `node --test extension/test_*.js`.
      - `migrate.sh` deploys to the live install and rebuilds the container; agents never run it, including `--dry-run`.
    ```

## Task 1: New layout, Meter skin, and the browser test category

Deliverable: the popup uses the new layout with the Meter skin in light and dark, and every existing control and message still works. The project has a tracked dev environment and a Chromium test. This task adds no Appearance menu: leave `#appearanceButton` and `#appearanceMenu` out of the markup, and hard-code `<html data-skin="meter">`.

Changes:
- **Development environment:** everything in the section above (`requirements-dev.txt`, `migrate.sh`, docs, `agents.md`).
- **`extension/popup.html`:** replace the markup and styles per **Design**. Drop the grid-paper background. Use classes for all styling. `popup.js` sets no inline `style.*` values except bar widths.
- **`extension/popup.js`:**
  - Rewrite `renderStatus` to fill `#registerHeading`, `#registerTotal`, `#register`, `#deliveryState`, `#deliveryDetails`, `#captureState`, `#captureHeld`, `#logState` and `#logList`, and to set the disabled state of `#forcePush` and `#reset`.
  - Rewrite `renderCaptureState` to set `captureToggle.checked`, `captureToggle.dataset.enabled`, `#captureState`, `#captureHeld` and `#clearCapture.disabled`.
  - Update `renderPersistenceStatus` for the Storage row and the summary tone.
  - Keep `renderConnectionStatus`, `showCheckingStatus`, `refresh`, `sendMessageWithTimeout`, `setNotice` and `bind` with their current names and signatures.
  - Capture switch: keep binding `click` and keep deciding with `dataset.enabled !== "true"`, so the decision uses the last rendered state. After the reply, `refresh` re-renders `checked`, so a rejected change snaps back.
  - Export per **Export**.
  - Remove `counterRow` and `fmt` if they end up unused.
- **`extension/test_popup_status.js`:**
  - Make `loadPopupStatusRenderer` serve fake nodes for every new ID through `getElementById`, built by the same node factory as `attachStatusList`. Add `dataset: {}` and `disabled`, `checked` and `open` defaults to that factory.
  - Update `attachStatusList` to attach every dynamic container and to return a helper that joins their `textContent`. Keep the `innerHTML` markup recorder on every container.
  - Rewrite **"shows whether full capture is on and how much it holds"** to assert `#captureState` ("On, 42 held" / "Off"), `#captureHeld`, `captureToggle.checked` and `dataset.enabled`. The old button text no longer exists; this is a deliberate copy change, and the test comment says so.
  - Update **"adjacent diagnostic and status values render as literal text"**. The `client_id: ` prefix is gone, so assert the payload appears as text in `#deliveryDetails`, and that `[rpcids=` plus the payload appears in `#logList`. Keep the assertion that nothing reaches `innerHTML`.
  - Make **"unavailable delivery renders counts as unavailable"** use the shared fake nodes and assert against `#register`.
  - Add tests:
    - Register merging: a host in both maps shows its total and "+N queued"; a pending-only host shows total 0 and its marker.
    - The disconnected register shows "Waiting to send" with pending counts and no marker, and "Nothing waiting to send." when empty.
    - The `refresh` failure path renders the "Extension not responding" rows.
    - The four `#deliveryState` texts. Queued and unconfirmed are computed from `inFlight.deltas`.
    - The Delivery fold auto-opens when the error first appears and stays closed on the next render after the test sets `open = false`.
    - `#forcePush`, `#reset` and `#clearCapture` disabled states.
    - Log ordering (newest first, five maximum), tone classes and the empty state.
    - `popup.js` source contains no `innerHTML` (`readFileSync` plus `assert.ok(!src.includes("innerHTML"))`).
    - Export through a stubbed `navigator.clipboard.writeText`: the success message, and on rejection the failure message, with `blobs.length` still incremented.
- **`extension/test_popup_browser.py`** (new, pytest, sync Playwright API):
  - **Stub collector:** a small `StubCollector` class wrapping a stdlib `http.server.ThreadingHTTPServer` on `127.0.0.1`, served on a daemon thread.
    - It implements the four endpoints in **Current state**. It checks the API key (403 on a mismatch) and serves `/counters` from a mutable dict that defaults to `{"chatgpt.com": 42, "gemini.google.com": 17}`.
    - `stop()` calls `shutdown()` and `server_close()`. `start()` binds again to the same port, with `allow_reuse_address = True`.
    - A module-scoped fixture picks a free port once (bind to port 0, read the port, close), starts the stub, and stops it at module teardown.
    - The "down" case calls `stop()` and, in a `finally` block, `start()` again.
  - **Extension copy:** a module-scoped fixture copies `extension/` to a module temp directory, without `config.local.js`. It writes a synthetic `config.local.js` in the format above, with `collectorUrl` set to the stub's `http://127.0.0.1:{port}` and `apiKey: "synthetic-popup-test-key"`.
  - **Browser:** a function-scoped `popup` fixture launches a fresh persistent context per test, with its own `tmp_path / "profile"`, so stored preferences never leak between tests. Launch with `playwright.chromium.launch_persistent_context(user_data_dir=tmp_path / "profile", channel="chromium", headless=True, args=[f"--disable-extensions-except={ext}", f"--load-extension={ext}"], viewport={"width": 360, "height": 600}, color_scheme=…)`. `channel="chromium"` is required for extensions in headless mode.
  - Get the extension ID from `context.service_workers[0].url`, waiting for the `serviceworker` event if the list is empty. Open `chrome-extension://{id}/popup.html` in a new page.
  - Wrap each test body in `with guard_browser_errors(page):`. It is a context manager in `tools/testkit.py` and imports only the standard library. Import it by adding the repository root (`Path(__file__).resolve().parents[3]`) to `sys.path`. Also record every request on the context with `context.on("request", …)`, and assert at the end that every URL starts with `chrome-extension://{id}/` or the stub's `http://127.0.0.1:{port}/`.
  - Parametrize cases 1–6 over `color_scheme` `"light"` and `"dark"`. Case 7 is not parametrized: it launches one light and one dark context, each with its own profile directory, and compares them. Cases:
    1. Stub up: `#status` has `data-state="connected"`, `#registerHeading` reads "Requests since last reset", two register rows, `#registerTotal` reads `59`.
    2. Stub down: after clicking **Check again**, `#status` has `data-state="error"` and the heading reads "Waiting to send".
    3. `document.documentElement.scrollWidth <= 360`.
    4. With all three folds open, scroll to the bottom; the footer's bounding box lies inside the 600 px viewport.
    5. Open the Delivery fold, call `refresh({showChecking:false})` through `page.evaluate`, and check the fold is still open.
    6. Clicking the capture switch flips `checked` and the `#captureState` text.
    7. The computed `background-color` of `body` differs between the light and dark contexts.
  - Save a full-page screenshot per case to `tmp_path` and print the paths.
  - The test must fail, not skip, when Chromium is missing.
- **Docs:** rename the old controls wherever they appear. Today that is `docker/llm_collector/README.md` line 18 (**Export JSON**) and `docker/llm_collector/extension/README.md` lines 115, 140–142, 155, 203, 207, 228 and 248 (**Clear Pending**, **Force Push**, **Reload**, **Clear Capture**, **Export JSON**). Describe the Export clipboard behavior. Replace the extension README **Validation** section with a pointer to the project README's **Development and tests** section, plus the existing manual failure-path check using **Check again**.

Acceptance, from `docker/llm_collector`:

```bash
.venv/bin/python -m pip check
```
Expected: `No broken requirements found.`

```bash
bash -n migrate.sh
```
Expected: no output, exit 0.

```bash
grep -c innerHTML extension/popup.js
```
Expected: `0`.

```bash
grep -n -E "Export JSON|Force Push|Clear Pending|Clear Capture|\*\*Reload\*\*" README.md INSTALLATION.md extension/README.md
```
Expected: no output.

Then run the first three suite commands from Task 2's acceptance section (pytest, zsh, Node). Expected: all pass with 0 failures and 0 skips; the manifest still reads `0.5.1` at this point. Compare the printed Meter screenshots with the Meter frames in the mock. Fix visible differences that are not listed as deliberate deviations.

## Task 2: Native skin, Appearance setting and release

Deliverable: both skins in light and dark, the Appearance menu switching between them and remembering the choice, and version `0.6.0`.

Changes:
- **`extension/popup_appearance.js`** (new) per **Appearance setting**. Load it in `popup.html` as described, and remove the hard-coded `data-skin`.
- **`extension/popup.html`:** add the Native skin styles and the Appearance button and menu markup. Take the visual details from the mock:
  - grouped inset rows with hairline separators;
  - row-style buttons inside folds;
  - pill buttons in the footer;
  - a check mark on the selected menu item;
  - the fold chevron on the right in Native and on the left in Meter.
- **`extension/popup.js`:** menu open and close (button, Escape, outside click, focus return), `aria-expanded` and `aria-checked` updates, the Automatic hint, writing the preference on selection and an immediate skin change, plus the failed-save notice.
- **`extension/test_popup_appearance.js`** (new, Node, loads the file in a `vm` context):
  - `resolveSkin` for `auto`, `meter` and `native` with `"macOS"`, `"MacIntel"`, `"Windows"` and `""`;
  - `readPreference` with missing, invalid and throwing storage returns `auto`;
  - `writePreference` returns `false` when storage throws;
  - `applySkin` sets `dataset.skin` on a fake document.
  - No-flash ordering, checked statically: read `popup.html` with `readFileSync` and assert that the first `<script` in the file is `<script src="popup_appearance.js">` with no `defer` or `async`, and that it appears before `<style`.
- **`extension/test_popup_status.js`:** add menu tests.
  - Choosing Native writes `llmUsageCounter.appearance=native` to a fake `localStorage` and sets `<html>`'s `dataset.skin`.
  - Escape closes the menu.
  - A throwing `localStorage` still changes the skin and shows "Appearance applied for now; it could not be saved."
- **`extension/test_popup_browser.py`:** parametrize Task 1's cases over `skin` `"meter"` and `"native"`, as well as the color scheme. Set the skin the same way in every case: open `popup.html`, run `localStorage.setItem("llmUsageCounter.appearance", skin)` with `page.evaluate`, call `page.reload()`, and assert `data-skin` before continuing. Add these cases:
  1. With no stored preference, `dataset.skin` equals `"native"` when `sys.platform == "darwin"` and `"meter"` otherwise.
  2. Choosing Meter from the menu, closing the page and opening a new popup page shows `data-skin="meter"`.
  3. Keyboard: with the preference set to `meter`, focus `#appearanceButton` and press Enter. Focus lands on Meter. Press ArrowDown, so focus is on Native, then Enter. `data-skin` becomes `native`, the menu is hidden, and `document.activeElement` is `#appearanceButton`.
- **`extension/manifest.json`:** `"version": "0.6.0"`.
- **`extension/README.md`:** document the Appearance setting, its storage key, Automatic's platform rule, and that light and dark follow the system.

Acceptance, the full project suite from `docker/llm_collector`:

```bash
.venv/bin/python -m pytest collector snapshots extension -v
```
```bash
zsh tests/test_local_config.zsh
```
```bash
node --test extension/test_*.js
```
```bash
grep -n '"version"' extension/manifest.json
```

Expected:
- pytest passes with 0 failures and 0 skips, covering 2 skins × 2 schemes for every browser case.
- The zsh test passes.
- The Node tests pass with 0 failures.
- The manifest line reads `"version": "0.6.0"`.

Name every failure with its output and fix it before committing. Compare the printed screenshots with all four mock frames (Meter and Native, light and dark).

## Hand-off checklist

Include this in the completion report for Kevin to run in his own browser, after loading the branch's `extension/` directory unpacked:
- Both skins in system light and dark.
- Collector up, then stopped with `llm_collector_container/down.sh`. Use **Check again**: the header turns red within two seconds and the register switches to "Waiting to send". Restart it with `up.sh` and check that it recovers.
- Export downloads a file, and the clipboard holds the same JSON.
- The Extensions page shows `0.6.0`.

## Deployment (post-merge procedure)

After merge, deploy from merged main with `docker/llm_collector/migrate.sh`, per PKM entry 250. Run `--dry-run` first. Its `source_test` now installs `requirements-dev.txt`, ensures Chromium, and runs the browser tests before touching the live install. Then reload the unpacked extension. Verify that the source manifest, the deployed `~/docker/llm_collector/extension/manifest.json` and the browser's Extensions page all show `0.6.0`, and include the version in the completion report.

## Out of scope

- Any change to `background.js`, `delivery.js`, `capture.js` or the collector, including exposing the retry time.
- A theme override separate from the system appearance.
- Bundled fonts.
- Syncing the Appearance preference across devices.
- Changes to the Dockerfile or `collector/requirements.txt`.
