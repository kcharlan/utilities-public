# LLM Token Analyzer & Format Converter — Technical Specification

**Status:** Current implementation reference
**Version:** 1.2
**Reviewed:** 2026-07-26

## 1. Architecture

The browser and CLI share a product purpose but no runtime code.

```text
web/index.html
  ├─ inline HTML/CSS/JavaScript
  ├─ CDN: @iarna/toml
  ├─ CDN: js-yaml
  ├─ CDN: Google Fonts
  └─ optional OpenAI Completions request

src/data_convert.py
  └─ src/converters/
       ├─ json_conv.py
       ├─ xml_conv.py
       ├─ yaml_conv.py
       ├─ toon_conv.py
       └─ toml_conv.py
```

There is no backend, build step, package entry point, upload service, or shared
conversion library between JavaScript and Python.

## 2. Browser implementation

### 2.1 State and controls

`web/index.html` queries all controls at startup and stores them in the
`textAreas`, `buttons`, and `insightElements` maps. `FORMATS` is:

```javascript
['raw', 'jsonPretty', 'jsonCompact', 'xml', 'toon', 'yaml', 'toml']
```

Every button calls `handleCalculate(sourceFormat)`. A run first clears errors,
counts, status chips, the comparison table, and insight cards. A raw-text run
validates non-empty input, calls `tokenizeText`, updates only the raw count, and
leaves existing structured text intact.

A structured run:

1. validates the selected text;
2. parses it into a JavaScript value;
3. renders all six structured formats;
4. clears the raw textarea;
5. tokenizes the six rendered strings in parallel;
6. updates counts, source chips, the sorted comparison table, and insights.

Any thrown validation, parsing, or serialization error is displayed under the
source panel. Counts and comparisons remain cleared.

### 2.2 Parsers and serializers

| Format | Parser | Serializer | Relevant behavior |
| --- | --- | --- | --- |
| JSON | `JSON.parse` | `toJsonPretty`, `toJsonCompact` | Object keys are recursively sorted |
| XML | `DOMParser` / `jsonFromXml` | `xmlFromJson` | Generated output is wrapped in `root`; attributes are ignored; leaf numbers/booleans are coerced |
| YAML | `jsyaml.load` | `jsyaml.dump` | Library loaded from jsDelivr |
| TOON | `jsonFromToon` | `toonFromJson` | Local key/value subset; object root required for output |
| TOML | `@iarna/toml.parse` | `@iarna/toml.stringify` | ESM library loaded from esm.sh; null rejected before output |

The browser TOON adapter is deliberately separate from the Python
`toon-format` library. Its colon-delimited lines, bracket lists, and inline
object syntax do not constitute a complete TOON grammar.

### 2.3 Tokenization

`estimateTokens(text)` returns `Math.ceil(text.length / 4)`.

`tokenizeText(text)` checks `window.OPENAI_API_KEY`. When present, it sends a
request with a three-second abort timeout:

```text
POST https://api.openai.com/v1/completions
model: gpt-3.5-turbo-instruct
prompt: rendered text
max_tokens: 0
```

On an HTTP success it reads `usage.prompt_tokens` and reports engine `api`.
Missing keys, exceptions, timeouts, and non-success responses fall through to
the character heuristic and report engine `local`.

The local result is not a BPE/tiktoken count. The API path is a legacy
Completions proxy, not a dedicated tokenization endpoint and not GPT-5.

### 2.4 Browser persistence and network use

The selected theme is stored under the `theme` localStorage key. Input and
converted data are not persisted by the page.

TOML, YAML, and font resources require CDN access when not cached. The optional
OpenAI request sends rendered text to OpenAI only when the user has explicitly
defined `window.OPENAI_API_KEY`.

## 3. Python CLI

### 3.1 Entry point and orchestration

`src/data_convert.py` is executed directly. Its supported target list is:

```python
['json', 'jsonc', 'xml', 'toon', 'yaml', 'toml']
```

`detect_format(file_path)` maps `.xml`, `.toon`, `.yaml`/`.yml`, and `.toml`
explicitly; every other extension is treated as JSON.

`load_data(from_format, contents)` delegates to the matching converter.
`dump_data(to_format, data, from_format)` delegates serialization. Before XML
serialization, data that is not a one-key dictionary is wrapped as
`{"root": data}`.

`main(argv=None)` parses arguments, reads UTF-8 input, converts, and writes the
explicit output path or `<input-basename>.<target-extension>` in the current
directory. `jsonc` uses the `.json` extension. A trailing newline is added to
non-JSON targets when the serializer did not provide one.

### 3.2 Converter contracts

```python
# json_conv.py
load_json(text: str) -> Any
dump_pretty(obj: Any) -> str
dump_compact(obj: Any) -> str

# xml_conv.py
load_xml(text: str) -> Any
dump_xml(obj: Any) -> str

# yaml_conv.py
load_yaml(text: str) -> Any
dump_yaml(obj: Any) -> str

# toon_conv.py
load_toon(text: str) -> Any
dump_toon(obj: Any) -> str

# toml_conv.py
load_toml(text: str) -> Any
dump_toml(obj: Any) -> str
```

- JSON uses the standard library and key-sorted serialization.
- XML parsing uses `xmltodict`. Serialization accepts a one-key dictionary,
  sorts child keys, repeats elements for lists, renders booleans lowercase, and
  renders `None` as empty content. Parsed leaf values remain strings.
- YAML uses `yaml.safe_load`/`safe_dump`; `_normalize` converts
  `OrderedDict` recursively before writing and preserves mapping order.
- TOON delegates to `toon_format.encode`/`decode` and raises
  `ToonUnavailable` when the dependency cannot be imported.
- TOML uses `tomllib` on Python 3.11+, `tomli` on Python 3.10, and `tomli_w` for
  output. `_ensure_toml_compatible` recursively rejects `None`.

### 3.3 Error contract

`exit_with_error` emits a compact JSON object on standard error and exits:

```json
{"code": "E_3", "message": "...", "hint": "..."}
```

The implemented exit codes are:

| Code | Meaning |
| --- | --- |
| `0` | Success |
| `2` | `argparse` usage/choice error |
| `3` | Missing input or parse failure |
| `4` | Serialization/conversion failure |
| `5` | Output write failure |

File-read errors other than the explicit missing-path check are not translated
by `exit_with_error`; they propagate as ordinary Python errors.

## 4. Dependencies

`requirements.txt` contains runtime and test dependencies:

- `xmltodict`
- `pyyaml`
- `tomli`
- `tomli_w`
- `toon-format` from its GitHub repository
- `pytest`
- `requests` and `tiktoken` (currently installed but not imported by the
  Python implementation)

Python 3.10+ is supported. Development and test execution must occur in a
virtual environment.

## 5. Test topology

The pytest suite covers:

- JSON, XML, YAML, TOON, and TOML converter units;
- CLI conversions, missing input, parse errors, default naming, and TOML null
  rejection;
- a parameterized round-trip matrix across JSON, XML, YAML, TOON, and TOML.

Same-format pairs are omitted. Round trips involving TOML and a dataset
containing `None` are omitted because TOML cannot encode null. XML comparisons
coerce scalar types to account for `xmltodict` string values.

There are no automated tests for `web/index.html`, its CDN loading, browser
conversion functions, theme behavior, or the optional API path.

## 6. Known design constraints

- The web and CLI implementations can differ because they do not share
  converters, most notably for TOON and XML scalar coercion.
- Conversion is structural, not schema-aware or universally lossless.
- XML keys and string values are interpolated by the serializers; this utility
  should be used with trusted, simple data rather than as a hardened XML
  generator.
- The token comparison is normally heuristic and should be interpreted as a
  relative size signal.
- The static page is not fully offline because of its CDN dependencies.
