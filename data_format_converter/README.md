# LLM Token Analyzer & Format Converter

This project has two independent interfaces:

- `web/index.html` converts pasted structured data in the browser and compares
  the rendered formats with a token-count estimate.
- `src/data_convert.py` converts files from the command line. It does not count
  tokens.

The structured formats are pretty JSON, compact JSON, XML, YAML, TOON, and
TOML. The web page also has a raw-text, count-only input.

## Web interface

Open `web/index.html` in a modern browser. Paste data into a panel and select
**Calculate & Convert**. Valid structured input is parsed into a JavaScript
object, rendered into every structured format, and added to the comparison
table. The raw-text panel only estimates the pasted text; it does not convert
or clear the structured inputs.

The page has no backend and does not upload pasted data to this repository. It
does, however, load the following resources from public CDNs:

- the `@iarna/toml` 3.0.0 parser and serializer;
- [`js-yaml` 5.4.3 browser UMD build](https://cdn.jsdelivr.net/npm/js-yaml@5.4.3/dist/browser/js-yaml.umd.min.js);
- Google Fonts.

Network access is therefore required on first load unless those resources are
already cached. The selected theme is the only value saved to browser
`localStorage`.

### Token counts

The page uses a simple local estimate:

```text
ceil(number of characters / 4)
```

This is useful for relative comparisons, but it is not a model tokenizer and
must not be treated as an exact billable-token count.

Token estimation is deliberately local. A former browser-only fallback sent
rendered content and a browser-exposed key to the legacy OpenAI Completions
API; that integration was removed because it was not a safe or current
tokenization contract. The page never reads an API key or uploads pasted data.

### Web conversion limits

- The browser TOON implementation is a small key/value subset. It is separate
  from the Python CLI's `toon-format` library and is not a general-purpose TOON
  parser.
- Generated XML uses a synthetic `<root>` element around the common object.
  XML attributes are not preserved, and numeric/boolean-looking element text
  is converted to JavaScript number/boolean values when parsed.
- TOML cannot represent `null`; if any converted value is `null`, the
  structured conversion run reports an error.
- YAML uses core implicit numbers: binary and separator forms such as `0b101`
  and `1_000` remain strings. Explicit numeric tags retain legacy parsing,
  including `!!int 1_000` and `!!float 1_000.5`
  (`yaml_implicit_legacy_numbers_use_core_strings` and
  `yaml_explicit_numeric_tags_keep_baseline_values` in
  [`tests/browser.spec.js`](tests/browser.spec.js)). Merge keys, timestamps,
  complex keys, binary, sets, ordered mappings, pairs, boolean-looking words,
  and comment-only documents retain their previous values
  (`yaml_load_preserves_legacy_collections_and_timestamps`).
- YAML output retains the tested multiline block style and trailing newlines.
  The approved v5 compatibility exception adds a terminal `...` document-end
  marker when the final multiline scalar uses keep chomping (`|+`); a scalar
  with one trailing newline stays unchanged
  (`yaml_dump_keeps_baseline_multiline_output`). A string of three spaces may
  use double rather than single quotes
  (`yaml_dump_accepts_whitespace_quote_change`). These byte-level exceptions
  preserve the parsed values.
- The browser Playwright smoke test covers dependency initialization, one JSON
  conversion, local token-source labels, and the no-OpenAI-request privacy
  contract. The Python tests do not validate the HTML/JavaScript
  implementation, and the browser suite is not a full interaction matrix.

## Command-line interface

### Setup

Python 3.10 or newer is required. From this directory, create and activate a
virtual environment, then install the project requirements:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

The supported Python dependency graph, including the released `toon-format`
distribution, is declared in [`requirements.txt`](requirements.txt).

### Usage

```sh
python src/data_convert.py \
  --input <input-file> \
  --to <json|jsonc|xml|toon|yaml|toml> \
  [--output <output-file>]
```

Input format is selected from the filename extension:

| Extension | Input format |
| --- | --- |
| `.json` | JSON |
| `.xml` | XML |
| `.toon` | TOON |
| `.yaml`, `.yml` | YAML |
| `.toml` | TOML |
| anything else | JSON |

`json` emits indented JSON and `jsonc` emits compact JSON. When `--output` is
omitted, the file is written to the current directory using the input basename
and target extension. Both JSON targets use `.json`.

Examples:

```sh
python src/data_convert.py --input tests/data/sample.json --to xml --output converted.xml
python src/data_convert.py --input tests/data/sample.xml --to jsonc
python src/data_convert.py --input tests/data/sample.yaml --to toon --output from_yaml.toon
python src/data_convert.py --input tests/data/sample.toml --to json
```

Important conversion behavior:

- JSON output is key-sorted. YAML preserves the parsed mapping order. XML
  output sorts mapping keys.
- XML requires one root element. Non-single-key data is wrapped in `<root>`
  when converting to XML.
- XML element values load as strings through `xmltodict`; an XML round trip may
  therefore not preserve scalar Python types.
- The XML serializers interpolate element names and string values directly.
  Use trusted, simple data; they are not hardened XML generators.
- TOML conversion fails with exit code `4` when the data contains `null`/`None`.
- TOON serializes Python dates, datetimes, and times as ISO strings
  ([`test_dump_temporal_as_iso_string`](tests/test_toon_conv.py)), and treats
  comment-only input as an empty object
  ([`test_load_comment_only_is_empty_object`](tests/test_toon_conv.py)).
- YAML binary values cannot be represented in TOON. Conversion reports a
  structured error with exit code `4` without creating an output file
  ([`test_yaml_binary_to_toon_is_a_structured_error`](tests/test_cli.py)).
- Missing input paths and parse errors use exit code `3`, conversion errors
  use `4`, output-write errors use `5`, and `argparse` usage errors use `2`.
  Handled runtime errors are emitted as one-line JSON on standard error;
  other input-read failures, such as permission errors, propagate as Python
  exceptions.

## Testing

From this directory, using the project virtual environment:

```sh
.venv/bin/python -m pytest
```

The pytest suite covers each Python converter, CLI success/error paths, default
output naming, and cross-format round trips. TOML pairs containing null values
are intentionally excluded because TOML has no null value.

The Playwright suite loads the static page in Chromium and verifies that the
pinned YAML and TOML browser dependencies initialize and perform a structured
conversion:

```sh
npm ci
npx playwright install chromium
npm run test:browser
```

## Maintenance notes

The browser and CLI have separate conversion implementations. Keep their
documented boundaries explicit rather than assuming parity, particularly for
TOON and XML. Browser conversion starts in `handleCalculate` in
`web/index.html`; each run clears previous counts and comparisons before
validation, so a failed run cannot leave stale results. The CLI dispatches
through `load_data` and `dump_data` in `src/data_convert.py` to the modules in
`src/converters/`.
