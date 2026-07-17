# Abacus.AI Usage Tracker

This toolkit automates the extraction and processing of ChatLLM credit usage data from the Abacus.AI dashboard. It allows you to easily bypass the web UI's limitations and export your usage logs into clean CSV files for analysis.

## 🚀 Quick Start

1.  **Setup:** Read **[`Operational_Guide.md`](./Operational_Guide.md)** to install the browser bookmarklets.
2.  **Capture:** Use the bookmarklets on the Abacus.AI dashboard to download JSON logs.
3.  **Process:** Run the `de-abacus.py` script to convert JSON to CSV.

```bash
# Example: Convert a downloaded detail log
python3 de-abacus.py abacus_usage_detail_2026-01-17.json output.csv
```

## 📂 Project Structure

### Documentation
*   **[`Operational_Guide.md`](./Operational_Guide.md)**: **(Recommended)** The modern guide. Explains how to use JavaScript bookmarklets to one-click capture data.
*   **`Deprecated - Guide - capture ChatLLM usage.md`**: The original manual method using Browser DevTools. Kept for archival purposes or debugging API changes.

### Tools
*   **[`de-abacus.py`](./de-abacus.py)**: The core utility script.
    *   **Input:** Raw JSON from the Abacus API.
    *   **Output:** Flattened CSV with dates as rows and Models/Sources as columns.
    *   **Features:** Handles dynamic column detection, fills missing values with 0, and rounds currency values.
    *   **Usage:** `python3 de-abacus.py <input.json> [output.csv]`

### Data Files (Examples)
*   **`abacus_usage_detail_*.json`**: Raw JSON response containing usage broken down by specific LLM (e.g., `CLAUDE_V4_5_SONNET`, `OPENAI_GPT5_2`).
*   **`abacus_usage_summary_*.json`**: Raw JSON response containing usage grouped by high-level source (e.g., `UI`, `Deep Agent`).
*   **`*.csv`**: The converted spreadsheet-ready versions of the logs.

## 🛠 Script Options

The `de-abacus.py` script includes several safety features and options:

```text
usage: de-abacus.py [-h] [--no-zeros] [-v] input [output]

positional arguments:
  input           Path to input JSON file
  output          Path to output CSV file (default: input_filename.csv)

options:
  -h, --help      show this help message and exit
  --no-zeros      Leave missing values empty instead of filling with 0
  -v, --verbose   Enable verbose debug logging
```
