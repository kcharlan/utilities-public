# Capture Abacus.AI usage data

The bookmarklets below download ChatLLM usage data directly from the signed-in
Abacus.AI Billing/Usage page.

Usage exports contain private account and activity data. Keep them outside this
public repository.

## Prerequisites

- Sign in to Abacus.AI and open the Billing/Usage page.
- Use a browser that supports JavaScript bookmarklets.

The bookmarklet runs in the current page and uses that page's authenticated
session. It will not work from an unrelated site or while signed out.

## Create the bookmarklets

Open the browser's bookmarks manager and create these two bookmarks. Paste the
entire `javascript:` line into each bookmark's URL field.

### Detail usage

- Name: `Abacus Usage (Detail)`
- URL:

```javascript
javascript:(async function(){const API_URL='/api/_getOrganizationComputePointLog';const payload={byLlm:true};try{const res=await fetch(API_URL,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':(document.cookie.match(/csrf_token=([^;]+)/)||[])[1]||''},body:JSON.stringify(payload)});if(!res.ok)throw new Error(`HTTP ${res.status}`);const data=await res.json();const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`abacus_usage_detail_${new Date().toISOString().slice(0,10)}.json`;document.body.appendChild(a);a.click();document.body.removeChild(a);alert('Detail data downloaded!');}catch(e){alert('Failed to download: '+e.message);console.error(e);}})();
```

### Summary usage

- Name: `Abacus Usage (Summary)`
- URL:

```javascript
javascript:(async function(){const API_URL='/api/_getOrganizationComputePointLog';const payload={byLlm:false};try{const res=await fetch(API_URL,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':(document.cookie.match(/csrf_token=([^;]+)/)||[])[1]||''},body:JSON.stringify(payload)});if(!res.ok)throw new Error(`HTTP ${res.status}`);const data=await res.json();const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`abacus_usage_summary_${new Date().toISOString().slice(0,10)}.json`;document.body.appendChild(a);a.click();document.body.removeChild(a);alert('Summary data downloaded!');}catch(e){alert('Failed to download: '+e.message);console.error(e);}})();
```

## Capture data

1. Open the signed-in Abacus.AI Billing/Usage page.
2. Click the detail or summary bookmark.
3. Confirm that the browser downloads
   `abacus_usage_detail_YYYY-MM-DD.json` or
   `abacus_usage_summary_YYYY-MM-DD.json`.

Detail data is grouped by model; summary data is grouped by higher-level usage
source.

## Convert the download

From the `abacus usage` directory, run:

```bash
./de-abacus.py \
  ~/Downloads/abacus_usage_detail_2030-01-02.json \
  ~/Downloads/abacus_usage_detail_2030-01-02.csv

./de-abacus.py \
  ~/Downloads/abacus_usage_summary_2030-01-02.json \
  ~/Downloads/abacus_usage_summary_2030-01-02.csv
```

See [`README.md`](./README.md#command-line-options) for all converter options.

## Troubleshooting

- For HTTP `401` or `403`, sign in again, reload the Billing/Usage page, and
  retry the bookmarklet.
- If no file downloads, allow downloads for the Abacus.AI site and inspect the
  browser console for the error reported by the bookmarklet.
- If the endpoint returns a different response shape, the converter requires a
  top-level `result` object and expects usage rows in `result.log`.
- Because the bookmarklets use an internal dashboard endpoint, an Abacus.AI
  dashboard update may require changing the endpoint or request payload.
