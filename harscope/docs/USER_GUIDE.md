# harscope User Guide

A walkthrough for analyzing, redacting, and exporting HAR files with harscope.

---

## 1. Getting Started

### Launch

```bash
# Open a HAR file directly
./harscope capture.har

# Launch without a file (load one in the browser)
./harscope

# Custom port
./harscope capture.har --port 9000
```

harscope starts a local web server and opens your browser automatically. The default port is **8200**; if it's busy, ports 8200–8219 are probed until one is available. You can run multiple instances side by side.

### First-Time Setup

On first run, harscope creates a private virtual environment at `~/.harscope_venv` and installs its dependencies (FastAPI, uvicorn, python-multipart). This happens once — subsequent launches start instantly.

**Requirements:** Python 3.8+ and an internet connection on first run (CDN resources: React, Tailwind, fonts).

### Loading a HAR File

Three ways to load a file once the browser is open:

| Method | How |
|--------|-----|
| **CLI argument** | Pass the path when you launch: `./harscope capture.har` |
| **Drag-and-drop** | Drag a `.har` file onto the welcome screen's drop zone. The border turns blue when hovering. |
| **File picker** | Click the drop zone to open your OS file browser, or type a full file-system path into the text field and click **Load**. |

### How to Capture a HAR File

1. Open Chrome DevTools (**F12**)
2. Go to the **Network** tab
3. Load or use the page you want to analyze
4. Right-click in the Network panel → **Save all as HAR with content**

---

## 2. The Interface

### Tab Bar

Seven tabs run across the top of the screen. The active tab has a blue underline.

| Tab | Icon | Purpose |
|-----|------|---------|
| **Waterfall** | BarChart3 | Paginated request timeline with timing bars and filters |
| **Inspector** | Search | Full request/response detail with inline redaction |
| **Security** | Shield | All security findings with severity/category filters |
| **Decisions** | ClipboardList | Audit trail of every redaction decision |
| **Sequence** | GitBranch | Sequence diagram of browser-to-server flows |
| **Dashboard** | LayoutDashboard | Summary statistics and charts |
| **Export** | Download | Download sanitized output and validate EDLs |

### Header

The header shows the loaded filename, file size, and entry count. On the right side:

- **Dark mode toggle** — click the moon/sun icon to switch themes. On first load, harscope follows your OS preference (`prefers-color-scheme: dark`).

---

## 3. Waterfall

The Waterfall is the default view. It shows every HTTP request as a row with a stacked timing bar.

### Reading the Timing Bars

Each bar is a horizontal stack of colored segments:

| Segment | Color | Meaning |
|---------|-------|---------|
| Blocked | Slate | Time spent waiting in the browser queue |
| DNS | Cyan | DNS lookup |
| Connect | Green | TCP connection |
| SSL/TLS | Purple | TLS handshake |
| Send | Blue | Sending the request |
| Wait (TTFB) | Yellow | Waiting for the first byte of the response |
| Receive | Emerald | Downloading the response body |

### Filtering

Four filters sit above the table. All can be combined — the results are the intersection of all active filters.

| Filter | Control | What it does |
|--------|---------|--------------|
| **Domain** | Dropdown | Show only requests to a specific domain |
| **Status** | Dropdown | Filter by status group (2xx, 3xx, 4xx, 5xx) |
| **Type** | Dropdown | Filter by content type (application/json, text/html, etc.) |
| **Search** | Text input | Case-insensitive full-text search across URL, headers, and body |

Changing any filter resets the page to 1.

### Security Shield Icons

Every row has a shield icon on the right:

- **Red shield** — critical or warning findings exist for this request
- **Green shield** — no actionable findings

Hover over the shield to see the count breakdown (e.g., "2 critical, 1 warning").

### Clicking a Row

Click any row to jump to the **Inspector** tab with that request loaded. This is the primary way to drill into a request's details.

### Pagination

The waterfall shows **50 requests per page**. Navigation controls at the bottom show `Page X / Y` with Previous/Next buttons.

---

## 4. Inspector

The Inspector shows full detail for a single request. Select a request by clicking a Waterfall row, clicking **Inspect** in the Decisions view, or navigating from a Security finding.

### Request / Response Toggle

Two buttons at the top switch between the request and response sides. A **red badge** appears on either button if security findings exist on that side.

### Sub-Tabs

Below the request/response toggle, sub-tabs break the content into sections:

| Sub-Tab | Shows | Badge |
|---------|-------|-------|
| **Headers** | HTTP header name/value pairs | Count + red alert if findings |
| **Cookies** | Cookies with HttpOnly/Secure flag indicators | Count + red alert if findings |
| **Query** | URL query string parameters (request only) | Count + red alert if findings |
| **Body** | Syntax-highlighted JSON body with expandable structure | Red alert if findings |
| **WebSocket** | WebSocket messages, if present | Count + red alert if findings |
| **Timings** | Timing breakdown (Blocked, DNS, Connect, SSL, Send, Wait, Receive) | — |
| **Findings** | Security findings for this specific entry | Count (red) |
| **Raw** | Full raw JSON for request or response | — |

### Auto-Navigation from Findings

When you click a finding in the Security tab, the Inspector opens the correct entry, switches to the right request/response side, and selects the sub-tab where the finding lives. This lets you jump straight to the flagged value.

### Finding Badges

Red badges on sub-tab labels tell you at a glance which sections contain security findings without clicking through each one.

---

## 5. Redaction

Redaction is harscope's core workflow. Every value in the Inspector — headers, cookies, query parameters, JSON body keys, and WebSocket messages — has an inline checkbox for toggling redaction.

### The 4-State System

Each value falls into one of four visual states:

| State | Badge | Color | Meaning |
|-------|-------|-------|---------|
| **FLAGGED** | `FLAGGED` | Red | Security scanner detected this value; it will be redacted on export |
| **KEPT** | `KEPT` | Teal | Scanner detected it, but you chose to keep the original value |
| **MANUAL** | `MANUAL` | Amber | You manually marked this value for redaction (scanner didn't flag it) |
| *(normal)* | — | Gray | No findings, no manual action; value exports as-is |

### Inline Checkboxes (Headers, Cookies, Query Params)

In the Headers, Cookies, and Query sub-tabs, each row has a checkbox on the left:

- **Checked + red** = FLAGGED (auto-redact)
- **Unchecked + teal** = KEPT (auto-detected but user chose to keep)
- **Checked + amber** = MANUAL (user-initiated redact)
- **Unchecked + gray** = normal value

Click the checkbox to toggle a value's redaction state. Scanner-detected values toggle between FLAGGED and KEPT. Non-detected values toggle between MANUAL and normal.

### JSON Body Redaction

In the Body sub-tab, JSON is displayed as syntax-highlighted, expandable structure. Keys with security findings appear with a **red background** and the value is visually marked.

Click any JSON key or value to toggle its redaction state. The same 4-state system applies.

### WebSocket Message Redaction

The WebSocket sub-tab lists messages with their data content. JSON-formatted messages are syntax-highlighted and support the same click-to-redact workflow as the Body tab.

### Keyboard Navigation

When a header/cookie/query table has focus:

| Key | Action |
|-----|--------|
| **Arrow Up** | Move focus to the previous row |
| **Arrow Down** | Move focus to the next row |
| **Spacebar** | Toggle redaction for the focused row |

### What Redaction Does on Export

When you export a sanitized HAR, every value marked for redaction (FLAGGED or MANUAL) is replaced with `[REDACTED]`. The replacement is done by parsing the body JSON, navigating to the exact key, replacing the full value, and re-serializing. Values already showing `[REDACTED]` are skipped on rescan.

---

## 6. Security

The Security tab shows all findings from the automatic scanner in a single list.

### How Detection Works

Detection is **value-first, not key-first**. Any sufficiently long, opaque string is evaluated regardless of its field name. Key names lower the detection threshold but never gate it.

**3-Tier Token Detection:**

| Tier | Condition | Severity |
|------|-----------|----------|
| 1 | Key name hints at secret + 32+ chars + 2+ character classes | Critical |
| 2 | Any key + 48+ chars + 2+ character classes | Warning |
| 3 | Any key + 80+ chars + 10+ unique characters | Warning |

**What gets flagged:**
- **Critical** — Authorization headers, session cookies, JWT tokens, Bearer/Basic auth, API keys (GitHub, GitLab, npm, Stripe, Slack, Supabase patterns), sensitive URL parameters, CSRF tokens, passwords, opaque tokens
- **Warning** — HTTP (non-HTTPS) requests, missing cookie security flags (httpOnly, secure), long opaque tokens without key hints
- **Info** — Private IP addresses (RFC 1918, IPv6 loopback)

Multiple detectors on the same value are consolidated into a single finding with merged descriptions and the highest severity.

### Filters

Two dropdowns at the top of the Security tab:

| Filter | Options |
|--------|---------|
| **Severity** | All, Critical, Warning, Info |
| **Category** | All, Auth, Token, JWT, Cookie Flags, Credentials, Private IP, etc. |

### Per-Finding Toggle

Each finding row has a toggle to switch between redact and keep. Toggling a finding here updates the Inspector's inline state and vice versa.

### Bulk Select / Deselect

Buttons at the top let you:
- **Select All** — mark all visible (filtered) findings for redaction
- **Deselect All** — mark all visible findings as kept

### Reset / Reapply

Reset returns all findings to their scanner-default state (auto-redact for critical/warning, keep for info).

---

## 7. Decisions

The Decisions tab is an audit trail — a table of every redaction decision, both automatic and manual.

### Columns

Each row shows: entry index, request method and path, location in the HAR (e.g., `request.headers[3].value`), action (redact/keep), source (auto/manual), and the area (headers, cookies, query, body, websocket).

### Filters

Three independent filter dropdowns:

| Filter | Options |
|--------|---------|
| **Action** | All, Redact, Keep |
| **Type** | All, Auto, Manual |
| **Area** | All, Headers, Cookies, Query, Body, WebSocket |

### Actions

Each row has two action buttons:

- **Toggle** — flip the decision between redact and keep
- **Inspect** — jump to the Inspector with the relevant entry, side, and sub-tab pre-selected

---

## 8. Exporting

The Export tab provides five output formats. All exports reflect your current redaction state — what's marked FLAGGED or MANUAL gets redacted, what's KEPT or normal stays.

### Export Formats

| Format | Extension | What It Produces |
|--------|-----------|------------------|
| **Sanitized HAR** | `.har` | A copy of the original HAR with all redacted values replaced by `[REDACTED]`. This is the file you share. |
| **Edit Decision List** | `.edl.json` | A JSON record of every redaction decision (entry index, location path, action, request context). Used for validation and auditing. |
| **CSV** | `.csv` | Tabular export of all requests: domain, path, status, timing, size. Good for spreadsheet analysis. |
| **Markdown Report** | `.md` | Analysis summary with stats, finding counts by severity, and a redaction summary. |
| **HTML Report** | `.html` | Self-contained HTML report with dark mode support (auto-detects system theme, manual sun/moon toggle, preference saved to localStorage), print-safe light forcing, and bulk redaction controls. Shareable as a standalone file. |

### Redaction Summary

Each export includes (or references) a summary of what was redacted: how many values were auto-redacted, how many were manually redacted, and how many were kept.

---

## 9. EDL & Validation

### What Is an EDL?

An **Edit Decision List** (`.edl.json`) is a companion file to a sanitized HAR. It records every redaction decision — auto and manual — with:

- Entry index and request context (method, path, status)
- Location path in the HAR (e.g., `entries[0].request.headers[3].value`)
- Action taken (`redact` or `keep`)
- Source (`auto` or `manual`)

### Why You Want One

- **Validate** that a sanitized HAR was actually redacted correctly
- **Audit** exactly what was redacted and what was kept
- **Automate** redaction workflows in CI/CD pipelines

Always export an EDL alongside your sanitized HAR.

### GUI Validation Workflow

1. Load the **sanitized** HAR into harscope (the one you already exported)
2. Go to the **Export** tab
3. Under the "Validate EDL" section, click **Upload EDL to Validate**
4. Select the `.edl.json` file you exported from the original HAR

Results appear immediately:

| Status | Meaning |
|--------|---------|
| **PASS** | Decision was applied correctly — redacted values show `[REDACTED]`, kept values have their original content |
| **FAIL** | Decision was NOT applied — the value doesn't match what was expected |
| **ERROR** | Location not found in the HAR — the path may have changed or the entry is missing |

A summary line shows the count: e.g., "42 pass, 0 fail, 1 error".

### CLI Validation

Validate without launching the browser:

```bash
# Human-readable output
./harscope --validate sanitized.har --edl original.edl.json

# Machine-readable JSON
./harscope --validate sanitized.har --edl original.edl.json --format json
```

Exit code **0** means all decisions validated. Exit code **1** means failures were found.

Validation rules:
- `action: redact` → value in HAR must be `[REDACTED]`
- `action: keep` → value in HAR must NOT be `[REDACTED]`

---

## 10. Other Views

### Sequence Diagram

An interactive SVG canvas showing browser-to-server request/response flows with pixel-perfect arrows and proper arrowhead markers.

**Visual Elements:**
- **Participant headers** — rounded cards with Globe (Browser) or Server icons and truncated domain names
- **Lifelines** — dashed vertical lines aligned under each participant
- **Blue solid arrows** = requests (labeled with HTTP method + path)
- **Gray dashed arrows** = successful responses (2xx/3xx, labeled with status code)
- **Red dashed arrows** = error responses (4xx/5xx)
- **Animated entrance** — arrows draw in with a staggered animation on load
- **Hover highlighting** — hovering a request or response highlights its paired arrow; other arrows fade to 40% opacity
- **Click to inspect** — clicking any arrow navigates to the Inspector for that entry

**Pan & Zoom:**

| Action | How |
|--------|-----|
| **Pan** | Click-drag on canvas, scroll wheel, or arrow keys |
| **Zoom** | Ctrl/Cmd + scroll wheel, `+`/`-` keys, or use the toolbar stepper |
| **Zoom stepper** | `[-]` and `[+]` buttons around an editable percentage field (click to type 20–300, press Enter) |
| **Fit to view** | **Fit** button or `Home` key |
| **Reset** | **Reset** button or `0` key |

**Minimap:** A small overview in the bottom-right corner shows all lifelines and arrows as tiny marks. The blue rectangle indicates the current viewport. Click anywhere on the minimap to jump to that region.

**Filters:**

| Control | What it does |
|---------|--------------|
| **Domain** dropdown | Show only flows involving a specific domain |
| **Flow** dropdown | Filter by detected pattern (see below) |
| **Show responses** checkbox | Toggle response arrows on/off to reduce visual noise |

**Detected Patterns:**

harscope automatically identifies common flow patterns and groups them:

- **Redirect chains** — sequences of 3xx responses (e.g., "redirect-0")
- **OAuth flows** — requests hitting `/oauth`, `/authorize`, `/token`, `/callback`, or `/auth/` endpoints, grouped with request count
- **API groups** — clusters of requests to the same domain prefix

**Pagination:** 100 messages per page with Previous/Next controls (floating overlay at bottom center).

### Dashboard

Four summary cards across the top:

| Card | Value |
|------|-------|
| **Total Requests** | Count of all HTTP requests |
| **Total Size** | Sum of all response body sizes |
| **Load Time** | Duration from first request to last response |
| **Error Rate** | Percentage of 4xx/5xx responses (highlighted red if > 5%) |

Four charts below:

| Chart | Type | Notes |
|-------|------|-------|
| **Status Codes** | Horizontal bar | Top 10 by frequency; 2xx=green, 3xx=yellow, 4xx=orange, 5xx=red |
| **Top Domains** | Horizontal bar | Top 10 domains by request count |
| **Content Types** | Horizontal bar | Top 10 MIME types, purple bars |
| **Timing Percentiles** | Text list | p50, p75, p90, p95 response times with average |

---

## 11. Quick Reference

### CLI Flags

```
./harscope [file.har] [--port PORT] [--validate HAR --edl EDL [--format text|json]]
```

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `file_path` | — | *(none)* | HAR file to open (optional) |
| `--port` | `-p` | 8200 | Server port (auto-probes 8200–8219) |
| `--validate` | — | — | Validate a sanitized HAR against an EDL (CLI mode) |
| `--edl` | — | — | Path to `.edl.json` (required with `--validate`) |
| `--format` | `-f` | `text` | Output format for validation: `text` or `json` |

### Keyboard Shortcuts

| Key | Context | Action |
|-----|---------|--------|
| **Arrow Up** | Inspector tables (headers/cookies/query) | Move focus to previous row |
| **Arrow Down** | Inspector tables | Move focus to next row |
| **Spacebar** | Inspector tables | Toggle redaction for focused row |
| **Enter** | File path input | Load the file |

### Color Legend

**Redaction States:**

| Badge | Background | Meaning |
|-------|-----------|---------|
| `FLAGGED` | Red | Auto-detected, will be redacted |
| `KEPT` | Teal | Auto-detected, user chose to keep |
| `MANUAL` | Amber | User manually marked for redaction |

**Severity Levels:**

| Severity | Color | Used in |
|----------|-------|---------|
| Critical | Red | Security findings, shield icons |
| Warning | Amber | Security findings, shield icons |
| Info | Gray | Security findings |

**HTTP Status Codes:**

| Range | Color |
|-------|-------|
| 2xx | Green |
| 3xx | Yellow |
| 4xx | Orange |
| 5xx | Red |

**Timing Segments:**

| Phase | Color |
|-------|-------|
| Blocked | Slate |
| DNS | Cyan |
| Connect | Green |
| SSL/TLS | Purple |
| Send | Blue |
| Wait (TTFB) | Yellow |
| Receive | Emerald |

**Shield Icons (Waterfall):**

| Icon | Meaning |
|------|---------|
| Red shield | Critical or warning findings |
| Green shield | No actionable findings |

**Validation Results:**

| Status | Color |
|--------|-------|
| PASS | Green |
| FAIL | Red |
| ERROR | Amber |
