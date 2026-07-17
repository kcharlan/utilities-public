# Operationalizing Abacus.AI Usage Capture

This guide provides a streamlined method to capture your ChatLLM usage data without manually digging through Developer Tools.

## The Solution: A "Bookmarklet"

A bookmarklet is a small piece of JavaScript code saved as a browser bookmark. When you are on the Abacus.AI usage page, simply clicking this bookmark will fetch the data and download the JSON file automatically.

### 1. Create the Bookmarklets

1.  Open your browser's **Bookmarks Manager**.
2.  Add two new bookmarks with the following details:

#### **Bookmark 1: Abacus Usage (Detail)**
- **Name:** `Abacus Usage (Detail)`
- **URL:** 
```javascript
javascript:(async function(){const API_URL='/api/_getOrganizationComputePointLog';const payload={byLlm:true};try{const res=await fetch(API_URL,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':(document.cookie.match(/csrf_token=([^;]+)/)||[])[1]||''},body:JSON.stringify(payload)});if(!res.ok)throw new Error(`HTTP ${res.status}`);const data=await res.json();const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`abacus_usage_detail_${new Date().toISOString().slice(0,10)}.json`;document.body.appendChild(a);a.click();document.body.removeChild(a);alert('Detail data downloaded!');}catch(e){alert('Failed to download: '+e.message);console.error(e);}})();
```

#### **Bookmark 2: Abacus Usage (Summary)**
- **Name:** `Abacus Usage (Summary)`
- **URL:**
```javascript
javascript:(async function(){const API_URL='/api/_getOrganizationComputePointLog';const payload={byLlm:false};try{const res=await fetch(API_URL,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':(document.cookie.match(/csrf_token=([^;]+)/)||[])[1]||''},body:JSON.stringify(payload)});if(!res.ok)throw new Error(`HTTP ${res.status}`);const data=await res.json();const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`abacus_usage_summary_${new Date().toISOString().slice(0,10)}.json`;document.body.appendChild(a);a.click();document.body.removeChild(a);alert('Summary data downloaded!');}catch(e){alert('Failed to download: '+e.message);console.error(e);}})();
```

### 2. How to Use

1.  Navigate to the **Abacus.AI Billing/Usage Dashboard**.
2.  Click the desired bookmark.
3.  A file named `abacus_usage_..._YYYY-MM-DD.json` will download.

### 3. Processing the Data

Use the Python utility to convert the JSON to CSV:

```bash
# Convert Detail JSON
./de-abacus.py ~/Downloads/abacus_usage_detail_2026-01-17.json detail.csv

# Convert Summary JSON
./de-abacus.py ~/Downloads/abacus_usage_summary_2026-01-17.json summary.csv
```