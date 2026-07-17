### Goal

Extract the raw JSON payload for Abacus.AI ChatLLM credit usage from Vivaldi on macOS, using DevTools. You already found the right endpoints:

- `_getOrganizationComputePointLog` (summary)
- `_getOrganizationComputePointLog` (detail)

The workflow below captures both reliably and keeps a record you can re-use later.

---

## A. Prepare Vivaldi so the request is easy to capture

1. Open the Abacus.AI page that shows the credit usage grid.
2. Open DevTools:
   - Menu: **Tools → Developer Tools**
   - Or shortcut: `Cmd+Option+I`
3. In DevTools, click the **Network** tab.
4. Turn on these two toggles at the top of Network:
   - **Preserve log**: ON  
     (so the request doesn’t disappear when the page navigates/reloads)
   - **Disable cache**: ON  
     (so reload forces fresh network calls while DevTools is open)
5. In the Network filter bar:
   - Click **Fetch/XHR** (you did this already).
   - In the text filter box, type: `_getOrganizationComputePointLog`

At this point the Network list should be mostly empty until you trigger the request.

---

## B. Trigger the request so it appears in Network

You need to cause the page to call the endpoint again.

1. With Network tab open and filtering in place, do one of:
   
   - Reload the page: `Cmd+R`, or
   - Change the date range (if available), or
   - Toggle the “model detail” checkbox on/off (this often triggers summary vs detail)

2. Watch the Network request list. You should see entries whose **Name** includes `_getOrganizationComputePointLog`.

Tip: if multiple entries appear, click the **Time** column to sort newest-first, or look at the **Waterfall** timing to identify the most recent one.

---

## C. Extract the JSON response (the simplest way)

Once you see the request you want:

1. Click the request row in the left panel (the one with `_getOrganizationComputePointLog`).
2. In the right panel, click **Response**.
3. Confirm you’re seeing the JSON you expect:
   - `{"success": true, "result": { ... }}`

Now you have two good copy options.

### Option 1: Copy response (recommended)

1. Right click the request row (in the left list).
2. Choose:
   - **Copy → Copy response**
3. Paste into a text editor:
   - TextEdit in plain text mode, VS Code, Sublime, etc.
4. Save it as a `.json` file, for example:
   - `compute_points_summary.json`
   - `compute_points_detail.json`

This is usually cleaner than selecting text in the Response panel because it copies the entire raw response.

### Option 2: Copy from the Response tab (works, but more manual)

1. In the **Response** tab, click inside the JSON.
2. `Cmd+A` (select all)
3. `Cmd+C` (copy)
4. Paste into your editor and save as `.json`

---

## D. Make sure you get both “summary” and “detail”

Because both are named the same in your description, the difference will be in the request payload and the response shape (columns differ).

Do this twice:

### 1) Capture summary

1. Turn OFF “model detail” (or whatever toggle collapses model breakdown).
2. Trigger a reload or date change.
3. Find the newest `_getOrganizationComputePointLog` request.
4. Copy response and save:
   - `compute_points_summary.json`

You can sanity-check it quickly by scanning for a smaller `columns` map like:

- `date`, `total`, `UI`, `Document Processing`, `Deep Agent` (etc.)

### 2) Capture detail

1. Turn ON “model detail”.
2. Trigger a reload or date change.
3. Pick the newest `_getOrganizationComputePointLog` request.
4. Copy response and save:
   - `compute_points_detail.json`

Sanity-check: `columns` should include lots of model keys (for example `OPENAI_GPT5_2`, `CLAUDE_...`, etc.).

---

## E. If multiple similar requests appear, identify the right one

When there are duplicates, use these quick checks:

1. Click the request, then open **Headers** (right panel).
2. Look at:
   - **Request Method** (likely POST)
   - **Request URL** (path will often be the same)
3. Scroll down in Headers to:
   - **Request Payload** (or “Form Data”)
4. Look for differences that correlate with summary vs detail, for example:
   - `includeModelDetails: true/false`
   - `groupBy: model`
   - `breakdown: true`
   - date range params

Even if you don’t fully understand the payload, this confirms you’re saving the correct response.

---

## F. Keep a reproducible artifact (optional but very useful)

Besides “Copy response”, also save the request itself so you can re-fetch later without the UI:

1. Right click the request row.
2. Choose:
   - **Copy → Copy as cURL**
3. Paste into a file and save it (redact cookies/tokens if you ever share it).

We can use that later to automate downloading the JSON for any date range.

---
