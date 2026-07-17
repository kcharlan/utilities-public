# Tax2 Technical Migration Plan

> **Superseded:** This historical migration plan predates the uv-managed PEP 723 launcher. See the repository-level `docs/uv_bootstrap_migration_implementation_plan.md` for the current environment model.

## Document Purpose

This document provides a step-by-step migration plan to convert the tax2 application from its current Streamlit-based architecture to the new self-bootstrapping pattern with an embedded React SPA interface, as defined in AGENTS.md.

**Target Audience**: Low reasoning coding agents
**Complexity Level**: Each step is atomic and verifiable
**Estimated Effort**: 15-20 implementation steps

---

## Current Architecture Analysis

### Current Structure
```
tax2/
├── app/
│   └── streamlit_app.py          # Streamlit UI (301 lines)
├── taxkit/                        # Core library
│   ├── __init__.py
│   ├── engine.py                  # Tax computation engine
│   ├── models.py                  # Pydantic models
│   ├── qif.py                     # QIF export
│   ├── rules_loader.py            # YAML rule parser
│   ├── tablegen.py                # Table generation
│   └── utils.py                   # Helper functions
├── rules/                         # YAML rule files
│   ├── federal/2025.yaml
│   └── states/GA/2025.yaml
├── tables/                        # Generated lookup tables
├── cli.py                         # Typer CLI for table generation
├── run.sh                         # Streamlit launcher
├── requirements.txt               # Dependencies (7 packages)
└── tests/
```

### Current Entry Points
1. **UI Mode**: `./run.sh` → launches Streamlit on port 8501
2. **CLI Mode**: `python3 cli.py tablegen` or `python3 cli.py generate-combined`

### Current Dependencies
```
streamlit>=1.36
pydantic>=2.5
pyyaml>=6.0
pandas>=2.0
typer>=0.12
python-dateutil>=2.9
pyarrow>=14.0
```

### Current Workflow
1. User activates venv manually (`source .venv/bin/activate`)
2. User installs dependencies manually (`pip install -r requirements.txt`)
3. User runs `./run.sh` or CLI commands
4. Streamlit reruns entire script on every interaction

---

## Target Architecture

### New Structure
```
tax2/
├── tax2                           # Single-file self-bootstrapping executable
├── taxkit/                        # Core library (unchanged)
│   ├── __init__.py
│   ├── engine.py
│   ├── models.py
│   ├── qif.py
│   ├── rules_loader.py
│   ├── tablegen.py
│   └── utils.py
├── rules/                         # YAML rule files (unchanged)
├── tables/                        # Generated lookup tables (unchanged)
├── docs/                          # Documentation
│   ├── Tech_migration.md          # This file
│   └── UI_Design_Reference.html   # UI mockup
└── tests/
```

### New Entry Point
```bash
# No setup required - just run
./tax2

# Or with options
./tax2 --port 8000
./tax2 /path/to/custom/rules/dir
```

### New Dependencies
```
fastapi>=0.104.0
uvicorn>=0.24.0
python-multipart>=0.0.6
pydantic>=2.5
pyyaml>=6.0
pandas>=2.0
python-dateutil>=2.9
pyarrow>=14.0
```

**Removed**: `streamlit`, `typer` (functionality absorbed into main file)
**Added**: `fastapi`, `uvicorn`, `python-multipart`

### New Workflow
1. User runs `./tax2` (no setup needed)
2. On first run: script auto-creates `~/.tax2_venv` and installs deps
3. Script re-execs itself using venv Python
4. FastAPI server starts on port 8000
5. Browser opens to `http://127.0.0.1:8000`
6. React SPA loads with full UI
7. User interacts; frontend fetches from `/api/*` endpoints

---

## Prerequisites

### Required Files
- [x] `/Users/example/source/utilities/tax2/docs/UI_Design_Reference.html` (created)
- [ ] `/Users/example/source/utilities/tax2/tax2` (to be created)

### Reference Implementation
- Location: `/Users/example/source/utilities/editdb/editdb`
- Use as template for:
  - Self-bootstrapping pattern (lines 8-41)
  - Embedded HTML template structure (lines 560-end)
  - FastAPI app structure (lines 227-end)
  - React/Tailwind/Babel CDN loading

---

## Detailed Migration Steps

### Phase 1: Create New Main File Structure

#### Step 1.1: Create Executable Stub
**File**: `tax2/tax2`
**Action**: Create new file with shebang and bootstrap skeleton

```python
#!/usr/bin/env python3
import os
import sys
import subprocess

# Self-Bootstrapper (copy from editdb pattern)
def bootstrap():
    """Ensure dependencies are installed in a private venv and re-run script."""
    venv_dir = os.path.expanduser("~/.tax2_venv")
    venv_python = os.path.join(venv_dir, "bin", "python3")

    # Always use venv if it exists
    if os.path.exists(venv_python) and sys.executable != venv_python:
        os.execv(venv_python, [venv_python] + sys.argv)

    # Check if we are already running inside our private venv
    if sys.executable == venv_python:
        return

    # If venv doesn't exist or dependencies are missing, set it up
    try:
        import fastapi
        import uvicorn
        import python_multipart
        import pydantic
        import yaml
        import pandas
        return
    except ImportError:
        pass

    if not os.path.exists(venv_python):
        print(f"📦 First-time setup: Creating environment in {venv_dir}...")
        subprocess.check_call([sys.executable, "-m", "venv", venv_dir])
        print("📥 Installing dependencies...")
        subprocess.check_call([venv_python, "-m", "pip", "install", "--upgrade", "pip"])
        subprocess.check_call([
            venv_python, "-m", "pip", "install",
            "fastapi", "uvicorn", "python-multipart",
            "pydantic", "pyyaml", "pandas", "python-dateutil", "pyarrow"
        ])

    os.execv(venv_python, [venv_python] + sys.argv)

if __name__ == "__main__":
    bootstrap()

# TODO: Add imports and main application code below
```

**Verification**:
- File exists at `tax2/tax2`
- File has execute permissions (`chmod +x tax2/tax2`)
- Running `./tax2` creates `~/.tax2_venv` on first run
- Script doesn't crash after bootstrap completes

---

#### Step 1.2: Add CLI Argument Parsing
**File**: `tax2/tax2`
**Action**: Add argument parser after bootstrap, before main app code

```python
import argparse
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('tax2')

def parse_args():
    parser = argparse.ArgumentParser(
        description="Tax2: Rules-based tax calculator with QIF export",
        epilog="Launches a local web server and opens the browser interface."
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=8000,
        help="Port to run the server on (default: 8000)."
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't auto-open browser"
    )
    parser.add_argument(
        "rules_dir",
        nargs="?",
        help="Optional custom rules directory"
    )
    return parser.parse_args()
```

**Verification**:
- `./tax2 --help` displays help text
- `./tax2 -p 9000` parses port correctly
- No runtime errors

---

### Phase 2: Implement FastAPI Backend

#### Step 2.1: Add Core FastAPI App
**File**: `tax2/tax2`
**Action**: Add FastAPI app initialization and basic routes

```python
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import io

app = FastAPI(title="Tax2 API")

# Global state
current_rules_dir = None

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return HTMLResponse(content="", status_code=204)

@app.get("/", response_class=HTMLResponse)
async def get_ui():
    return HTML_TEMPLATE  # Will be defined later

@app.get("/api/status")
async def status():
    return {
        "rules_dir": current_rules_dir or "default",
        "version": "2.0"
    }
```

**Verification**:
- Code compiles without import errors
- FastAPI app object is created
- Routes are defined

---

#### Step 2.2: Add API Models
**File**: `tax2/tax2`
**Action**: Define Pydantic request/response models

```python
from datetime import date

class TaxRequest(BaseModel):
    monthly_income: float
    filing_status: str
    year: int
    mode: str  # "rules" or "table"
    federal_rules: Optional[str] = None
    state_rules: Optional[str] = None

class TaxResponse(BaseModel):
    federal_monthly: float
    state_monthly: float
    total_monthly: float
    federal_annual: float
    state_annual: float
    total_annual: float
    effective_rate: float
    brackets: Optional[List[Dict[str, Any]]] = None

class QIFRequest(BaseModel):
    tx_date: date
    federal_tax: float
    state_tax: float
    payee: str
    federal_expense: str
    federal_transfer: str
    state_expense: str
    state_transfer: str
```

**Verification**:
- All models compile
- No circular import issues with taxkit models

---

#### Step 2.3: Implement Tax Computation Endpoint
**File**: `tax2/tax2`
**Action**: Add POST /api/compute endpoint

```python
@app.post("/api/compute", response_model=TaxResponse)
async def compute_taxes(request: TaxRequest):
    """Compute taxes using rules engine or table lookup"""
    try:
        from taxkit.rules_loader import load_rules
        from taxkit.engine import compute_tax
        from taxkit.models import TaxInput, FilingStatus
        from taxkit.utils import get_rule_path

        # Determine rules directory
        base_dir = os.path.dirname(__file__)

        if request.mode == "rules":
            # Use rules engine
            fed_base = request.federal_rules or os.path.join(base_dir, "rules", "federal")
            state_base = request.state_rules or os.path.join(base_dir, "rules", "states", "GA")

            fed_path = get_rule_path(fed_base, request.year)
            state_path = get_rule_path(state_base, request.year)

            fed_rules = load_rules(fed_path)
            state_rules = load_rules(state_path)

            fs = FilingStatus(request.filing_status)
            annual_income = request.monthly_income * 12.0

            federal_annual = compute_tax(TaxInput(annual_income=annual_income, filing_status=fs), fed_rules)
            state_annual = compute_tax(TaxInput(annual_income=annual_income, filing_status=fs), state_rules)

            federal_monthly = round(federal_annual / 12.0, 2)
            state_monthly = round(state_annual / 12.0, 2)

        elif request.mode == "table":
            # Use table lookup
            import pandas as pd

            table_path = os.path.join(base_dir, "tables", f"combined_{request.year}.csv")
            if not os.path.exists(table_path):
                raise HTTPException(status_code=404, detail=f"Table for year {request.year} not found")

            df = pd.read_csv(table_path)

            # Find nearest income
            idx = (df["MonthlyIncome"] - request.monthly_income).abs().idxmin()
            row = df.loc[idx]

            federal_monthly = float(row["FederalMonthlyTax"])
            state_monthly = float(row["StateMonthlyTax"])
            federal_annual = federal_monthly * 12
            state_annual = state_monthly * 12

        else:
            raise HTTPException(status_code=400, detail="Invalid mode")

        total_monthly = federal_monthly + state_monthly
        total_annual = federal_annual + state_annual
        effective_rate = round((total_annual / (request.monthly_income * 12)) * 100, 2)

        return TaxResponse(
            federal_monthly=federal_monthly,
            state_monthly=state_monthly,
            total_monthly=total_monthly,
            federal_annual=federal_annual,
            state_annual=state_annual,
            total_annual=total_annual,
            effective_rate=effective_rate
        )

    except Exception as e:
        logger.error(f"Computation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
```

**Verification**:
- Endpoint compiles without errors
- Can handle both "rules" and "table" modes
- Returns proper TaxResponse structure

---

#### Step 2.4: Implement Available Years Endpoint
**File**: `tax2/tax2`
**Action**: Add GET /api/years endpoint

```python
@app.get("/api/years")
async def get_available_years():
    """Return list of available tax years"""
    try:
        from taxkit.utils import get_available_years

        base_dir = os.path.dirname(__file__)
        fed_dir = os.path.join(base_dir, "rules", "federal")

        years = get_available_years(fed_dir)

        # Get current year as default
        import datetime
        current_year = datetime.datetime.now().year

        return {
            "years": sorted(years, reverse=True),
            "default": current_year if current_year in years else max(years) if years else current_year
        }
    except Exception as e:
        logger.error(f"Failed to get years: {e}")
        return {"years": [2025, 2024], "default": 2025}
```

**Verification**:
- Endpoint returns list of years
- Default year is reasonable

---

#### Step 2.5: Implement QIF Export Endpoint
**File**: `tax2/tax2`
**Action**: Add POST /api/export/qif endpoint

```python
@app.post("/api/export/qif")
async def export_qif(request: QIFRequest):
    """Generate QIF file for download"""
    try:
        from taxkit.qif import build_qif_entries, QIFConfig

        cfg = QIFConfig(
            payee=request.payee,
            federal_expense=request.federal_expense,
            federal_transfer=request.federal_transfer,
            state_expense=request.state_expense,
            state_transfer=request.state_transfer
        )

        qif_text = build_qif_entries(request.tx_date, request.federal_tax, request.state_tax, cfg)

        # Return as downloadable file
        return StreamingResponse(
            io.BytesIO(qif_text.encode('utf-8')),
            media_type="application/qif",
            headers={"Content-Disposition": "attachment; filename=tax_transactions.qif"}
        )

    except Exception as e:
        logger.error(f"QIF export failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

**Verification**:
- Endpoint compiles
- Returns StreamingResponse with proper headers

---

#### Step 2.6: Implement Table Generation Endpoint
**File**: `tax2/tax2`
**Action**: Add POST /api/generate-tables endpoint

```python
class GenerateTableRequest(BaseModel):
    year: int
    state: str = "GA"
    filing_status: str = "single"
    inc_max: int = 500000
    step: int = 50

@app.post("/api/generate-tables")
async def generate_tables(request: GenerateTableRequest):
    """Generate combined tax tables (async background task)"""
    try:
        from taxkit.tablegen import generate_table
        from taxkit.utils import get_rule_path
        import pandas as pd

        base_dir = os.path.dirname(__file__)

        fed_dir = os.path.join(base_dir, "rules", "federal")
        state_dir = os.path.join(base_dir, "rules", "states", request.state)

        fed_path = get_rule_path(fed_dir, request.year)
        state_path = get_rule_path(state_dir, request.year)

        # Generate tables
        df_fed = generate_table(fed_path, request.filing_status, 0, request.inc_max, request.step, "monthly")
        df_state = generate_table(state_path, request.filing_status, 0, request.inc_max, request.step, "monthly")

        # Save individual files
        out_dir = os.path.join(base_dir, "tables")
        os.makedirs(out_dir, exist_ok=True)

        fed_out = os.path.join(out_dir, f"federal_{request.year}.parquet")
        state_out = os.path.join(out_dir, f"{request.state.lower()}_{request.year}.parquet")

        df_fed.to_parquet(fed_out, index=False)
        df_state.to_parquet(state_out, index=False)

        # Merge
        rf = df_fed.rename(columns={"MonthlyTax": "FederalMonthlyTax"})[["MonthlyIncome", "FederalMonthlyTax"]]
        rs = df_state.rename(columns={"MonthlyTax": "StateMonthlyTax"})[["MonthlyIncome", "StateMonthlyTax"]]

        combined = pd.merge(rf, rs, on="MonthlyIncome", how="outer").sort_values("MonthlyIncome")

        combined_out = os.path.join(out_dir, f"combined_{request.year}.csv")
        combined.to_csv(combined_out, index=False)

        return {
            "status": "success",
            "rows": len(combined),
            "files": [fed_out, state_out, combined_out]
        }

    except Exception as e:
        logger.error(f"Table generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

**Verification**:
- Endpoint compiles
- Generates tables successfully
- Returns status with file paths

---

### Phase 3: Implement React Frontend

#### Step 3.1: Create HTML Template Skeleton
**File**: `tax2/tax2`
**Action**: Add HTML_TEMPLATE constant with CDN imports

```python
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tax2 - Professional Tax Calculator</title>

    <!-- Fonts -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&family=Epilogue:wght@400;500;600;700;800&family=Public+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">

    <!-- Tailwind CSS -->
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    fontFamily: {
                        display: ['Epilogue', 'sans-serif'],
                        mono: ['IBM Plex Mono', 'monospace'],
                        body: ['Public Sans', 'sans-serif']
                    }
                }
            }
        };
    </script>

    <!-- React -->
    <script src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
    <script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
    <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>

    <!-- Lucide Icons -->
    <script src="https://unpkg.com/lucide@0.321.0/dist/umd/lucide.min.js"></script>

    <style>
        /* Copy styles from UI_Design_Reference.html */
        /* TO BE ADDED IN NEXT STEP */
    </style>
</head>
<body>
    <div id="root"></div>

    <script type="text/babel">
        // React app code
        // TO BE ADDED IN NEXT STEP
    </script>
</body>
</html>
"""
```

**Verification**:
- HTML template is a valid string
- All CDN URLs are accessible
- Template can be returned from GET /

---

#### Step 3.2: Copy CSS Styles
**File**: `tax2/tax2`
**Action**: Copy complete CSS from `UI_Design_Reference.html` into `<style>` block

**Source**: `/Users/example/source/utilities/tax2/docs/UI_Design_Reference.html` (lines in `<style>` tag)
**Destination**: `HTML_TEMPLATE` `<style>` section

**Instructions**:
1. Open `UI_Design_Reference.html`
2. Copy everything between `<style>` and `</style>` tags
3. Paste into HTML_TEMPLATE's `<style>` section
4. Ensure no escaping issues with template string

**Verification**:
- Template still parses as valid Python string
- No syntax errors
- CSS variables are all defined

---

#### Step 3.3: Implement React App Component Structure
**File**: `tax2/tax2`
**Action**: Add React component skeleton

```javascript
const { useState, useEffect } = React;

// Icon component (copy from editdb)
const Icon = ({ name, size = 18, className = "" }) => {
    const toPascalCase = (value) => value.replace(/(\\w)(\\w*)(_|-|\\s*)/g, (_, first, rest) =>
        first.toUpperCase() + rest.toLowerCase()
    );
    const iconDef = window.lucide?.icons?.[toPascalCase(name)];
    const [tag, baseAttrs, children] = Array.isArray(iconDef) ? iconDef : [];

    if (!iconDef || tag !== 'svg' || !Array.isArray(children)) {
        return <span className={`inline-flex items-center justify-center ${className}`}
                     style={{ width: size, height: size, minWidth: size }} />;
    }

    return (
        <svg xmlns="http://www.w3.org/2000/svg" {...baseAttrs} width={size} height={size}
             className={`inline-block ${className}`.trim()}>
            {children.map(([childTag, attrs], i) =>
                React.createElement(childTag, { ...attrs, key: `${name}-${i}` })
            )}
        </svg>
    );
};

// Main App Component
const App = () => {
    // State management
    const [darkMode, setDarkMode] = useState(false);
    const [availableYears, setAvailableYears] = useState([]);
    const [selectedYear, setSelectedYear] = useState(2025);
    const [filingStatus, setFilingStatus] = useState('single');
    const [computeMode, setComputeMode] = useState('rules');
    const [monthlyIncome, setMonthlyIncome] = useState(12500);
    const [taxResults, setTaxResults] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    // QIF config
    const [qifConfig, setQifConfig] = useState({
        txDate: new Date().toISOString().split('T')[0],
        payee: 'Estimated Taxes Withholding',
        federalExpense: 'Tax:Federal Income Tax Estimated Paid',
        federalTransfer: '[Federal Income Taxes]',
        stateExpense: 'Tax:State Income Tax Estimated Paid',
        stateTransfer: '[GA State Income Taxes]'
    });

    // Load available years on mount
    useEffect(() => {
        fetch('/api/years')
            .then(r => r.json())
            .then(data => {
                setAvailableYears(data.years);
                setSelectedYear(data.default);
            })
            .catch(err => console.error('Failed to load years:', err));
    }, []);

    // Auto-compute on input changes
    useEffect(() => {
        computeTaxes();
    }, [monthlyIncome, filingStatus, selectedYear, computeMode]);

    // Dark mode persistence
    useEffect(() => {
        const saved = localStorage.getItem('tax2-dark-mode');
        if (saved !== null) {
            setDarkMode(saved === 'true');
        }
    }, []);

    useEffect(() => {
        localStorage.setItem('tax2-dark-mode', darkMode);
        document.documentElement.classList.toggle('dark', darkMode);
    }, [darkMode]);

    const computeTaxes = async () => {
        setLoading(true);
        setError(null);

        try {
            const response = await fetch('/api/compute', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    monthly_income: monthlyIncome,
                    filing_status: filingStatus,
                    year: selectedYear,
                    mode: computeMode
                })
            });

            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || 'Computation failed');
            }

            const data = await response.json();
            setTaxResults(data);
        } catch (err) {
            setError(err.message);
            console.error('Computation error:', err);
        } finally {
            setLoading(false);
        }
    };

    const downloadQIF = async () => {
        if (!taxResults) return;

        try {
            const response = await fetch('/api/export/qif', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    tx_date: qifConfig.txDate,
                    federal_tax: taxResults.federal_monthly,
                    state_tax: taxResults.state_monthly,
                    payee: qifConfig.payee,
                    federal_expense: qifConfig.federalExpense,
                    federal_transfer: qifConfig.federalTransfer,
                    state_expense: qifConfig.stateExpense,
                    state_transfer: qifConfig.stateTransfer
                })
            });

            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'tax_transactions.qif';
            a.click();
            window.URL.revokeObjectURL(url);
        } catch (err) {
            console.error('QIF export failed:', err);
            alert('Failed to export QIF: ' + err.message);
        }
    };

    return (
        <div className="app-container">
            {/* Sidebar */}
            <Sidebar
                selectedYear={selectedYear}
                setSelectedYear={setSelectedYear}
                availableYears={availableYears}
                filingStatus={filingStatus}
                setFilingStatus={setFilingStatus}
                computeMode={computeMode}
                setComputeMode={setComputeMode}
            />

            {/* Main Panel */}
            <MainPanel
                selectedYear={selectedYear}
                monthlyIncome={monthlyIncome}
                setMonthlyIncome={setMonthlyIncome}
                taxResults={taxResults}
                loading={loading}
                error={error}
                darkMode={darkMode}
                setDarkMode={setDarkMode}
            />

            {/* Export Panel */}
            <ExportPanel
                qifConfig={qifConfig}
                setQifConfig={setQifConfig}
                downloadQIF={downloadQIF}
                taxResults={taxResults}
            />
        </div>
    );
};

// Render app
const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);
```

**Verification**:
- React code compiles in browser
- No console errors
- App renders empty shell

---

#### Step 3.4: Implement Sidebar Component
**File**: `tax2/tax2`
**Action**: Add Sidebar component in React section

```javascript
const Sidebar = ({ selectedYear, setSelectedYear, availableYears, filingStatus, setFilingStatus, computeMode, setComputeMode }) => {
    return (
        <div className="sidebar">
            <div className="sidebar-header">
                <h1 className="app-title">Tax2</h1>
                <div className="app-subtitle">Professional Edition</div>
            </div>

            <div className="control-section">
                <label className="control-label">Tax Year</label>
                <select value={selectedYear} onChange={(e) => setSelectedYear(Number(e.target.value))}>
                    {availableYears.map(year => (
                        <option key={year} value={year}>{year}</option>
                    ))}
                </select>
            </div>

            <div className="control-section">
                <label className="control-label">Filing Status</label>
                <div className="radio-group">
                    <div className="radio-option">
                        <input
                            type="radio"
                            name="filing"
                            id="single"
                            checked={filingStatus === 'single'}
                            onChange={() => setFilingStatus('single')}
                        />
                        <label htmlFor="single">Single</label>
                    </div>
                    <div className="radio-option">
                        <input
                            type="radio"
                            name="filing"
                            id="married"
                            checked={filingStatus === 'married_joint'}
                            onChange={() => setFilingStatus('married_joint')}
                        />
                        <label htmlFor="married">Married Filing Jointly</label>
                    </div>
                </div>
            </div>

            <div className="control-section">
                <label className="control-label">Computation Mode</label>
                <div className="radio-group">
                    <div className="radio-option">
                        <input
                            type="radio"
                            name="mode"
                            id="rules"
                            checked={computeMode === 'rules'}
                            onChange={() => setComputeMode('rules')}
                        />
                        <label htmlFor="rules">Rules Engine</label>
                    </div>
                    <div className="radio-option">
                        <input
                            type="radio"
                            name="mode"
                            id="table"
                            checked={computeMode === 'table'}
                            onChange={() => setComputeMode('table')}
                        />
                        <label htmlFor="table">Lookup Table</label>
                    </div>
                </div>
            </div>
        </div>
    );
};
```

**Verification**:
- Sidebar renders with controls
- Year selection works
- Filing status toggles
- Mode switches between rules/table

---

#### Step 3.5: Implement MainPanel Component
**File**: `tax2/tax2`
**Action**: Add MainPanel component

```javascript
const MainPanel = ({ selectedYear, monthlyIncome, setMonthlyIncome, taxResults, loading, error, darkMode, setDarkMode }) => {
    const formatCurrency = (value) => {
        return value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    };

    const handleIncomeChange = (e) => {
        const value = e.target.value.replace(/,/g, '');
        if (!isNaN(value) && value !== '') {
            setMonthlyIncome(Number(value));
        }
    };

    return (
        <div className="main-panel">
            <div className="header-bar">
                <div className="year-badge">FY {selectedYear}</div>
                <button className="theme-toggle" onClick={() => setDarkMode(!darkMode)}>
                    ◐ Toggle Theme
                </button>
            </div>

            {/* Income Input */}
            <div className="income-section">
                <div className="income-label">Monthly Gross Income</div>
                <div className="income-display">
                    <span className="currency-symbol">$</span>
                    <input
                        type="text"
                        className="income-input"
                        value={formatCurrency(monthlyIncome)}
                        onChange={handleIncomeChange}
                    />
                </div>
                <div className="income-sublabel">= ${formatCurrency(monthlyIncome * 12)} annually</div>
            </div>

            {/* Error Display */}
            {error && (
                <div style={{ padding: '1rem', background: 'var(--accent-tax-light)', borderRadius: '8px', marginBottom: '2rem' }}>
                    <strong>Error:</strong> {error}
                </div>
            )}

            {/* Results */}
            {loading ? (
                <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-secondary)' }}>
                    Calculating...
                </div>
            ) : taxResults ? (
                <>
                    <div className="results-grid">
                        <div className="result-card federal">
                            <div className="result-label">Federal Tax</div>
                            <div className="result-amount">${formatCurrency(taxResults.federal_monthly)}</div>
                            <div className="result-sublabel">
                                {((taxResults.federal_monthly / monthlyIncome) * 100).toFixed(1)}% effective
                            </div>
                        </div>

                        <div className="result-card state">
                            <div className="result-label">State Tax (GA)</div>
                            <div className="result-amount">${formatCurrency(taxResults.state_monthly)}</div>
                            <div className="result-sublabel">
                                {((taxResults.state_monthly / monthlyIncome) * 100).toFixed(1)}% effective
                            </div>
                        </div>

                        <div className="result-card total">
                            <div className="result-label">Total Monthly</div>
                            <div className="result-amount">${formatCurrency(taxResults.total_monthly)}</div>
                            <div className="result-sublabel">{taxResults.effective_rate}% combined</div>
                        </div>
                    </div>
                </>
            ) : null}
        </div>
    );
};
```

**Verification**:
- Main panel renders
- Income input displays and updates
- Results cards show when taxResults is present
- Loading state displays
- Error state displays

---

#### Step 3.6: Implement ExportPanel Component
**File**: `tax2/tax2`
**Action**: Add ExportPanel component

```javascript
const ExportPanel = ({ qifConfig, setQifConfig, downloadQIF, taxResults }) => {
    const updateConfig = (key, value) => {
        setQifConfig(prev => ({ ...prev, [key]: value }));
    };

    return (
        <div className="export-panel">
            <div className="export-header">
                <h2 className="export-title">QIF Export</h2>
                <p className="export-description">
                    Configure transaction details for Quicken/Moneydance import
                </p>
            </div>

            <div className="export-section">
                <label className="export-label">Transaction Date</label>
                <input
                    type="date"
                    value={qifConfig.txDate}
                    onChange={(e) => updateConfig('txDate', e.target.value)}
                />
            </div>

            <div className="export-section">
                <label className="export-label">Payee Name</label>
                <input
                    type="text"
                    value={qifConfig.payee}
                    onChange={(e) => updateConfig('payee', e.target.value)}
                />
            </div>

            <div className="export-section">
                <label className="export-label">Federal Expense Category</label>
                <input
                    type="text"
                    className="category-input"
                    value={qifConfig.federalExpense}
                    onChange={(e) => updateConfig('federalExpense', e.target.value)}
                />
            </div>

            <div className="export-section">
                <label className="export-label">Federal Transfer Account</label>
                <input
                    type="text"
                    className="category-input"
                    value={qifConfig.federalTransfer}
                    onChange={(e) => updateConfig('federalTransfer', e.target.value)}
                />
            </div>

            <div className="export-section">
                <label className="export-label">State Expense Category</label>
                <input
                    type="text"
                    className="category-input"
                    value={qifConfig.stateExpense}
                    onChange={(e) => updateConfig('stateExpense', e.target.value)}
                />
            </div>

            <div className="export-section">
                <label className="export-label">State Transfer Account</label>
                <input
                    type="text"
                    className="category-input"
                    value={qifConfig.stateTransfer}
                    onChange={(e) => updateConfig('stateTransfer', e.target.value)}
                />
            </div>

            <button
                className="export-button"
                onClick={downloadQIF}
                disabled={!taxResults}
            >
                ↓ Download QIF
            </button>
        </div>
    );
};
```

**Verification**:
- Export panel renders
- All QIF config inputs are editable
- Download button is enabled when taxResults exists
- Button triggers downloadQIF function

---

### Phase 4: Server Initialization

#### Step 4.1: Add Server Startup Logic
**File**: `tax2/tax2`
**Action**: Add main() function and server startup

```python
import uvicorn
import webbrowser
import threading
import time

def open_browser(port: int, delay: float = 1.5):
    """Open browser after short delay to let server start"""
    time.sleep(delay)
    webbrowser.open(f"http://127.0.0.1:{port}")

def main():
    args = parse_args()

    # Set global rules directory if provided
    global current_rules_dir
    if args.rules_dir:
        current_rules_dir = os.path.abspath(args.rules_dir)
        logger.info(f"Using custom rules directory: {current_rules_dir}")

    # Launch browser in background thread
    if not args.no_browser:
        threading.Thread(target=open_browser, args=(args.port,), daemon=True).start()

    # Start server
    logger.info(f"Starting Tax2 server on http://127.0.0.1:{args.port}")
    logger.info("Press Ctrl+C to stop")

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=args.port,
        log_level="info"
    )

if __name__ == "__main__":
    main()
```

**Verification**:
- main() function compiles
- Server starts when running `./tax2`
- Browser opens automatically (unless --no-browser)
- Server logs appear in console
- Ctrl+C stops server cleanly

---

### Phase 5: Testing and Validation

#### Step 5.1: Manual Smoke Test
**Actions**:
1. Run `./tax2` from terminal
2. Verify bootstrap creates `~/.tax2_venv` on first run
3. Verify browser opens to `http://127.0.0.1:8000`
4. Verify UI loads without errors
5. Change income input → verify tax calculation updates
6. Toggle filing status → verify recalculation
7. Switch mode to "table" → verify it uses table lookup
8. Configure QIF settings
9. Click "Download QIF" → verify file downloads
10. Toggle dark mode → verify theme switches
11. Test with different years (if rules exist)

**Success Criteria**:
- No console errors
- All API endpoints respond
- Tax calculations match expected values
- QIF file has correct format
- Dark mode persists across reloads

---

#### Step 5.2: Comparison Test
**Actions**:
1. Run old Streamlit version: `./run.sh` (from legacy venv)
2. Run new version: `./tax2`
3. Compare outputs for identical inputs:
   - Monthly income: $12,500
   - Filing status: Single
   - Year: 2025
   - Mode: Rules engine

**Validation**:
- Federal tax matches (within $0.01)
- State tax matches (within $0.01)
- QIF output is byte-identical

**If differences found**:
- Check rounding logic in API endpoint
- Verify taxkit imports are correct
- Check annual/monthly conversion

---

#### Step 5.3: Run Existing Tests
**Actions**:
```bash
cd /Users/example/source/utilities/tax2
~/.tax2_venv/bin/python -m pytest
```

**Expected**:
- All existing tests pass
- No regressions in taxkit modules

---

### Phase 6: Migration Cleanup

#### Step 6.1: Update README
**File**: `tax2/README.md`
**Action**: Rewrite Quick Start section

Replace:
```markdown
## Quick Start

```bash
# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the application
streamlit run app/streamlit_app.py
```
```

With:
```markdown
## Quick Start

```bash
# No setup required - just run
./tax2

# Or with custom port
./tax2 --port 9000

# CLI mode for table generation (uses same venv)
~/.tax2_venv/bin/python -c "from tax2 import generate_tables_cli; generate_tables_cli()"
```

On first run, the script will automatically:
- Create a private virtual environment at `~/.tax2_venv`
- Install all required dependencies
- Start the web server
- Open your browser

Subsequent runs start instantly.
```

**Verification**:
- README is updated
- Instructions are accurate
- No references to Streamlit remain

---

#### Step 6.2: Archive Old Files
**Actions**:
```bash
cd /Users/example/source/utilities/tax2
mkdir -p archive/streamlit_version
mv app/ archive/streamlit_version/
mv run.sh archive/streamlit_version/
mv requirements.txt archive/streamlit_version/
mv .venv/ archive/streamlit_version/ # If you want to remove it
```

**Note**: Keep `cli.py` if you want to preserve separate CLI tool, or absorb its functionality into `tax2` script

**Verification**:
- Old files moved to archive/
- Core application still works
- taxkit/ directory untouched

---

#### Step 6.3: Update .gitignore
**File**: `tax2/.gitignore`
**Action**: Add new patterns

```
# Virtual environment (old and new)
.venv/
~/.tax2_venv

# Python
__pycache__/
*.pyc
*.pyo
.pytest_cache/

# Generated files
tables/*.parquet
tables/*.csv

# Archives
archive/

# IDE
.vscode/
.idea/
```

**Verification**:
- File is created/updated
- Patterns match current structure

---

### Phase 7: Documentation

#### Step 7.1: Create Usage Guide
**File**: `tax2/docs/Usage.md`
**Action**: Create user documentation

```markdown
# Tax2 Usage Guide

## Installation

No installation required. Simply run the executable:

```bash
./tax2
```

## Basic Usage

### Launch the Application
```bash
./tax2
```

This will:
1. Start the web server on port 8000
2. Automatically open your browser
3. Display the tax calculator interface

### Command-Line Options

**Custom Port**:
```bash
./tax2 --port 9000
```

**Disable Auto-Browser**:
```bash
./tax2 --no-browser
```

**Custom Rules Directory**:
```bash
./tax2 /path/to/custom/rules
```

## Features

### Tax Calculation Modes

1. **Rules Engine** (default)
   - Computes taxes directly from YAML rule files
   - Always uses the latest logic
   - Ideal for testing rule changes

2. **Lookup Table**
   - Fast pre-computed results
   - Requires table generation first
   - Good for production use

### Generating Tables

Use the built-in table generation endpoint:
1. Open the app
2. Go to "Generate Tables" (if UI supports it)
3. Or use API directly:

```bash
curl -X POST http://127.0.0.1:8000/api/generate-tables \
  -H "Content-Type: application/json" \
  -d '{"year": 2025, "state": "GA", "filing_status": "single"}'
```

### QIF Export

1. Enter your income and select filing status
2. Review calculated taxes
3. Configure QIF settings in right panel:
   - Transaction date
   - Payee name
   - Account categories
4. Click "Download QIF"
5. Import into Quicken or Moneydance

## Customization

### Adding New Tax Years

1. Create YAML files:
   - `rules/federal/2026.yaml`
   - `rules/states/GA/2026.yaml`

2. Restart the application

3. New year appears in dropdown

### Adding New States

1. Create directory: `rules/states/TX/`
2. Add YAML file: `rules/states/TX/2025.yaml`
3. Modify API endpoint to support state selection
4. Restart application

## Troubleshooting

**Port already in use**:
```bash
./tax2 --port 9000
```

**Dependencies not installing**:
```bash
rm -rf ~/.tax2_venv
./tax2  # Will recreate and reinstall
```

**Calculation seems wrong**:
- Check YAML rules for typos
- Verify year is correct
- Try switching between rules/table mode
- Compare with previous year's rules
```

**Verification**:
- Documentation is clear
- Examples are correct
- Covers common scenarios

---

### Phase 8: Final Validation

#### Step 8.1: Full Integration Test
**Test Script**: Create `test_migration.sh`

```bash
#!/bin/bash
set -e

echo "=== Tax2 Migration Test Suite ==="

# Clean slate
echo "1. Cleaning old venv..."
rm -rf ~/.tax2_venv

# First run
echo "2. Testing first run (bootstrap)..."
timeout 5 ./tax2 --no-browser --port 8001 &
PID=$!
sleep 3
kill $PID || true

# Verify venv created
echo "3. Verifying venv exists..."
test -d ~/.tax2_venv || (echo "ERROR: venv not created" && exit 1)

# Test API
echo "4. Testing API endpoints..."
./tax2 --no-browser --port 8001 &
PID=$!
sleep 2

# Status endpoint
curl -s http://127.0.0.1:8001/api/status | grep -q "rules_dir" || (echo "ERROR: /api/status failed" && kill $PID && exit 1)

# Years endpoint
curl -s http://127.0.0.1:8001/api/years | grep -q "years" || (echo "ERROR: /api/years failed" && kill $PID && exit 1)

# Compute endpoint
curl -s -X POST http://127.0.0.1:8001/api/compute \
  -H "Content-Type: application/json" \
  -d '{"monthly_income":12500,"filing_status":"single","year":2025,"mode":"rules"}' \
  | grep -q "federal_monthly" || (echo "ERROR: /api/compute failed" && kill $PID && exit 1)

kill $PID

echo "5. All tests passed!"
echo "=== Migration Successful ==="
```

**Actions**:
1. Make script executable: `chmod +x test_migration.sh`
2. Run: `./test_migration.sh`
3. Verify all tests pass

**Verification**:
- Script completes without errors
- All API endpoints respond correctly
- Venv is created and used

---

#### Step 8.2: Performance Comparison
**Actions**:
1. Time Streamlit startup:
   ```bash
   time (streamlit run app/streamlit_app.py --server.headless=true &
         sleep 5; kill %1)
   ```

2. Time new version startup:
   ```bash
   time (./tax2 --no-browser &
         sleep 2; kill %1)
   ```

**Expected**:
- New version starts faster (no Streamlit overhead)
- First run slower (bootstrap), subsequent runs fast

---

## Migration Checklist

Before declaring migration complete, verify:

- [ ] `tax2` executable exists and is executable
- [ ] Bootstrap creates `~/.tax2_venv` on first run
- [ ] All dependencies install correctly
- [ ] FastAPI server starts without errors
- [ ] Browser opens automatically (when not disabled)
- [ ] UI loads without console errors
- [ ] All React components render
- [ ] Dark mode toggles correctly
- [ ] Year selection works
- [ ] Filing status toggles
- [ ] Computation mode switches (rules/table)
- [ ] Income input updates calculations
- [ ] Tax results display correctly
- [ ] Calculations match old Streamlit version
- [ ] QIF export downloads valid file
- [ ] QIF format matches previous implementation
- [ ] Table generation works
- [ ] Custom rules directory option works
- [ ] Port customization works
- [ ] --no-browser flag works
- [ ] README is updated
- [ ] Old files are archived
- [ ] Tests pass
- [ ] Documentation is complete

---

## Rollback Plan

If migration fails or issues are found:

1. **Restore Old Version**:
   ```bash
   cd /Users/example/source/utilities/tax2
   mv archive/streamlit_version/* .
   source .venv/bin/activate
   ./run.sh
   ```

2. **Remove New Files**:
   ```bash
   rm tax2
   rm -rf ~/.tax2_venv
   ```

3. **Preserve taxkit**:
   - The `taxkit/` directory should remain unchanged
   - All core logic remains compatible with both versions

---

## Post-Migration Tasks

After successful migration:

1. **Update Project README** at repo root to reflect new usage
2. **Update AGENTS.md** to list tax2 as using new pattern
3. **Create Release Notes** documenting changes
4. **Test on Clean Machine** (if possible) to verify bootstrap works universally
5. **Update .gitignore** to exclude `~/.tax2_venv` globally if desired
6. **Consider**: Add GitHub Actions workflow to test bootstrap process

---

## Notes for Low Reasoning Agents

- **Execute steps sequentially** - many steps depend on previous completions
- **Verify after each step** - use the verification criteria provided
- **Do not skip verification** - catch errors early
- **Copy code exactly** - templates are designed to work as-is
- **Read error messages carefully** - they usually indicate which step failed
- **If stuck**: Check that bootstrap completed, venv exists, and dependencies installed
- **Safe to re-run**: Bootstrap is idempotent; running `./tax2` multiple times is safe
- **Use logging**: Check console output for FastAPI startup messages and errors

---

## Success Metrics

The migration is successful when:

1. **User Experience**: User can run `./tax2` with zero setup
2. **Functionality**: All features from Streamlit version work
3. **Performance**: UI is more responsive than Streamlit
4. **Compatibility**: QIF exports match byte-for-byte
5. **Maintainability**: Single file is easier to distribute and update
6. **Reliability**: No dependency conflicts, works on fresh systems

---

## Appendix A: File Size Comparison

**Before Migration**:
```
app/streamlit_app.py:          ~301 lines
cli.py:                        ~113 lines
run.sh:                        ~5 lines
requirements.txt:              ~8 lines
Total complexity:              Multiple files, external venv
```

**After Migration**:
```
tax2:                          ~800-1000 lines (estimated)
Total complexity:              Single file, self-contained
```

Trade-off: Larger single file, but dramatically simpler deployment and user experience.

---

## Appendix B: Dependency Changes

**Removed**:
- `streamlit` - Replaced by FastAPI + React
- `typer` - Replaced by `argparse`

**Added**:
- `fastapi` - Backend API framework
- `uvicorn` - ASGI server
- `python-multipart` - File upload support

**Unchanged**:
- `pydantic` - Data models
- `pyyaml` - Rules parsing
- `pandas` - Table operations
- `python-dateutil` - Date handling
- `pyarrow` - Parquet support

Net change: -1 dependency, +30MB lighter distribution

---

## End of Migration Plan

This plan provides complete, step-by-step instructions for migrating tax2 from Streamlit to the self-bootstrapping + React SPA architecture. Follow each step carefully, verify at each checkpoint, and refer to the editdb reference implementation when in doubt.
