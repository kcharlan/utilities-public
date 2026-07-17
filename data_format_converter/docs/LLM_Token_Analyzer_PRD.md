# LLM Token Analyzer & Format Converter  
**Version:** 1.1  
**Author:** Repository maintainers  
**Date:** 2025-11-11  

---

## 1. Overview

This project delivers a dual-interface utility for analyzing and converting text data formats, emphasizing token count efficiency for LLM use. It includes:

1. **Web Interface:** a standalone static HTML/JS page for copy-paste analysis and conversion between supported formats.  
2. **Command Line Interface (CLI):** a Python utility for file-based format conversion only.

Both tools provide insight into how various data structures affect tokenization under **OpenAI GPT-5**.

---

## 2. Objectives

- Quickly compare token counts across formats for LLM prompt optimization.  
- Seamlessly convert between JSON (pretty/compact), XML, YAML, and TOON.
- Enable low-friction, offline experimentation without requiring APIs or installations beyond pip dependencies.  
- Keep the implementation modular, testable, and self-contained.

---

## 3. Supported Formats

| Type | Input Source | Conversion | Token Counting |
|------|---------------|-------------|----------------|
| Raw Text | Manual entry only | No | Yes |
| JSON Pretty | Yes | To all others | Yes |
| JSON Compact | Yes | To all others | Yes |
| XML | Yes | To all others | Yes |
| YAML | Yes | To all others | Yes |
| TOON | Yes | To all others | Yes |

---

## 4. Functional Requirements

### 4.1 Web Interface

**Structure**
- Single HTML file (inline JS and CSS preferred).
- Six stacked text boxes (one per format).
- “Calculate” button under each box.
- Token count displayed under each box.
- Comparison table listing format name, token count, and percentage difference from smallest count.

**Behavior**
- When *Calculate* is clicked:
  1. Validate the input.
  2. If valid:
     - Convert to all other supported formats.
     - Calculate and display token counts.
     - Update comparison table.
  3. If invalid:
     - Show an inline error below the offending box.
     - Clear all token counts.
- When entering raw text, all other boxes are cleared and disabled.
- Boxes are editable, but counts update only on *Calculate*.

**Tokenization**
- Uses **OpenAI GPT-5 tokenizer**.
- Attempt API call first; fall back to local `tiktoken` if unavailable.
- Each token count shows an indicator:  
  - ✅ “API” — official OpenAI tokenizer used  
  - ⚙️ “Local” — fallback mode  

**Error Handling**
- Inline errors directly beneath inputs.
- Clears all previous counts and results when any error is detected.

---

### 4.2 CLI Utility

**Command Name:** `data_convert`

**Syntax**
```
data_convert --input <file> --to <target_format> [--output <file>]
```

**Behavior**
- Validates input format and structure.  
- Converts to specified target format.  
- Outputs to:
  - `<input_basename>.<target_format>` by default, or  
  - User-defined filename via `--output`.  
- Supports: JSON (pretty/compact), XML, YAML, TOON.
- Does **not** calculate token counts.  

**Dependencies**
- `xmltodict`
- `tiktoken`
- `requests`
- `pyyaml`
- `toon-format` (from GitHub)

---

## 5. Technical Architecture

### 5.1 Web Tool
- **Language:** HTML5 + Vanilla JS (optional inline CSS).  
- **Tokenization:**  
  - JS fetch to OpenAI API (`/v1/tokenize`) when available.  
  - Fallback to embedded `tiktoken`-based estimator when offline.  
- **No backend, uploads, or persistent storage.**

### 5.2 CLI Tool
- **Language:** Python 3.10+  
- **Structure:**
  ```
  src/
    data_convert.py
    converters/
      json_conv.py
      xml_conv.py
      toon_conv.py
      yaml_conv.py
    tests/
      test_json_conv.py
      test_xml_conv.py
      test_toon_conv.py
      test_yaml_conv.py
  requirements.txt
  ```

- **Libraries:**  
  - `tiktoken` (token counting, fallback)  
  - `xmltodict` (XML handling)  
  - `requests` (API calls)  
  - `pyyaml` (YAML handling)
  - `toon-format` (TOON handling, installed from GitHub)

- **Environment:** isolated `venv` install via `requirements.txt`.

---

## 6. Unit Testing (pytest)

### Scope

| Component | Positive Tests | Negative Tests |
|------------|----------------|----------------|
| JSON converter | Valid round-trip (pretty↔compact) | Invalid JSON syntax |
| XML converter | Proper nested conversion | Malformed tags |
| YAML converter | Proper nested conversion | Malformed YAML |
| TOON converter | Valid TOON→JSON | Unsupported features |
| Fallback logic | Uses local tokenizer if API down | N/A |
| Parity | JSON→XML→JSON matches original | N/A |

### Exclusions
- No UI tests for HTML/JS.  
- No tests requiring OpenAI API keys.

---

## 7. Non-Functional Requirements

- Must run offline (excluding optional API call).  
- Setup entirely via `requirements.txt`.  
- CLI operations complete within 3 seconds for ≤1 MB input.  
- Static HTML page, no CDN or server dependency.

---

## 8. Deliverables

- `web/index.html` — static front-end.  
- `src/data_convert.py` — CLI utility.  
- `requirements.txt` — dependencies.  
- `tests/` — pytest suite.  
- `README.md` — setup and usage instructions.  

---

## 9. Risks & Notes

- **OpenAI API:** fallback ensures continuity if API changes or requires key.  
- **Future Expansion:** add Anthropic/Gemini tokenizers when official SDKs exist.

---

## 10. Sample Execution Plan

### Phase 1 — Core Conversion (CLI)
- Implement converters for JSON, XML, YAML, TOON.
- Build CLI wrapper and argument parser.  
- Validate and test round-trip conversions.  

### Phase 2 — Tokenization Logic
- Integrate GPT-5 API calls with fallback to `tiktoken`.  
- Create token count and comparison logic.  
- Unit-test fallback and count accuracy.  

### Phase 3 — Web UI
- Build static HTML/JS interface.  
- Implement conversion and tokenization flows.  
- Add inline error handling and comparison table.  

### Phase 4 — Finalization & QA
- Add README, requirements, and usage docs.  
- Run pytest suite.  
- Package for venv deployment.  

---

**End of Document**
