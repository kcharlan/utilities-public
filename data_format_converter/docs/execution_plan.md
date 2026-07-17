# Execution Plan: LLM Token Analyzer & Format Converter

This document breaks down the work required to build the LLM Token Analyzer and Format Converter utility. The plan is based on the PRD and Technical Specification documents. Each task includes a checkbox to track progress.

---

## 1. Project Setup

- [x] Create the initial directory structure:
  ```
  .
  ├── src/
  │   ├── converters/
  │   │   ├── __init__.py
  │   │   ├── json_conv.py
  │   │   ├── xml_conv.py
  │   │   └── toon_conv.py
  │   └── data_convert.py
  ├── tests/
  │   ├── __init__.py
  │   ├── data/
  │   ├── test_json_conv.py
  │   ├── test_xml_conv.py
  │   └── test_toon_conv.py
  ├── docs/
  ├── web/
  │   └── index.html
  └── requirements.txt
  └── README.md
  ```

---

## 2. Phase 1: Core Conversion Logic (Python CLI)

This phase focuses on building the backend conversion logic and the command-line interface.

- **Sub-task 2.1: JSON Converter**
  - [x] Implement `load_json` in `src/converters/json_conv.py`.
  - [x] Implement `dump_pretty` (2-space indent, sorted keys) in `src/converters/json_conv.py`.
  - [x] Implement `dump_compact` (no spaces, sorted keys) in `src/converters/json_conv.py`.
  - [x] Write unit tests in `tests/test_json_conv.py` to verify round-trip conversions and handling of malformed JSON.

- **Sub-task 2.2: XML Converter**
  - [x] Implement `load_xml` using `xmltodict` in `src/converters/xml_conv.py`, ensuring it handles single root elements and no attributes.
  - [x] Implement `dump_xml` with deterministic key ordering in `src/converters/xml_conv.py`.
  - [x] Write unit tests in `tests/test_xml_conv.py` for JSON-to-XML-to-JSON round-trip equivalence and handling of malformed XML.

- **Sub-task 2.3: TOON Converter**
  - [x] Implement `load_toon` in `src/converters/toon_conv.py`. Include a fallback for when the `toon` library is not available.
  - [x] Implement `dump_toon` in `src/converters/toon_conv.py`.
  - [x] Define `ToonUnavailable` exception.
  - [x] Write unit tests in `tests/test_toon_conv.py` for valid TOON subset parsing and graceful failure for unsupported features.

- **Sub-task 2.4: CLI Implementation**
  - [x] Set up `argparse` in `src/data_convert.py` to handle `--input`, `--to`, and `--output` arguments.
  - [x] Implement the main `convert` function to orchestrate format detection and conversion.
  - [x] Implement the `main` function to read input, call `convert`, and write to the output file or default filename.
  - [x] Implement error handling with the specified exit codes and STDERR JSON messages.
  - [x] Create `requirements.txt` with `xmltodict`, `requests`, `tiktoken`, and `pyyaml`.

---

## 3. Phase 2: Web Interface

This phase focuses on building the standalone HTML/JS web tool.

- **Sub-task 3.1: HTML Structure**
  - [x] Create the main HTML file `web/index.html`.
  - [x] Implement the five text area panels (Raw Text, JSON Pretty, JSON Compact, XML, TOON).
  - [x] Add "Calculate" buttons, token count display areas, and status indicators (API/Local) for each panel.
  - [x] Implement the final comparison table structure.

- **Sub-task 3.2: JavaScript Conversion Logic**
  - [x] Write pure JavaScript functions to convert between data formats (JSON, XML, TOON), mirroring the Python logic for deterministic output.
  - [x] `toJsonPretty`, `toJsonCompact`
  - [x] `xmlFromJson`, `jsonFromXml`
  - [x] `toonFromJson`, `jsonFromToon`

- **Sub-task 3.3: Tokenization**
  - [x] Implement the `tokenizeText` function.
  - [x] Add logic to call the OpenAI API (`/v1/tokenize`) if `window.OPENAI_API_KEY` is present, with a 3-second timeout.
  - [x] Implement a local fallback estimator (`estimateTokens`) using a simple BPE implementation or heuristic for GPT-5.
  - [x] Ensure the correct status indicator (✅ API or ⚙️ Local) is displayed.

- **Sub-task 3.4: UI Interaction & Pipeline**
  - [x] Wire up the "Calculate" buttons to trigger the full pipeline: validate -> convert -> tokenize -> update UI.
  - [x] Implement the validation logic for each input format.
  - [x] Implement the error handling protocol: display an inline error and clear all results upon failure.
  - [x] Implement the logic to populate the comparison table with token counts and percentage differences.
  - [x] Ensure the "Raw Text" input disables other structured format text areas.

---

## 4. Phase 3: Finalization & Documentation

- **Sub-task 4.1: Documentation**
  - [x] Create a `README.md` file with:
    - [x] Project overview.
    - [x] Setup instructions for the CLI (`venv`, `pip install -r requirements.txt`).
    - [x] Usage instructions for `data_convert`.
    - [x] Instructions for using the `web/index.html` tool, including how to provide an API key.

- **Sub-task 4.2: Testing and QA**
  - [x] Run the full `pytest` suite to ensure all CLI tests pass.
  - [x] Manually test the web interface against the E2E scenarios defined in the spec.
  - [x] Verify deterministic outputs for both CLI and web tools using golden test files from `tests/data/`.

---
