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
- `js-yaml` 4.1.1;
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
- The browser Playwright smoke test covers dependency initialization, one JSON
  conversion, local token-source labels, and the no-OpenAI-request privacy
  contract. The Python tests do not validate the HTML/JavaScript
  implementation, and the browser suite is not a full interaction matrix.

## Command-line interface

### Setup

Python 3.10 or newer is required. From this directory, create and activate a
virtual environment, then install the project requirements:

```sh
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt` installs the TOON implementation directly from its GitHub
repository at audited commit
`e475c82e9da03dfaf88c0b277dee6b5d17100b13`, so the initial installation
requires network access.

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
- TOML conversion fails with exit code `4` when the data contains `null`/`None`.
- Parse/input errors use exit code `3`, conversion errors use `4`, output-write
  errors use `5`, and `argparse` usage errors use `2`. Runtime error details are
  emitted as one-line JSON on standard error.

## Testing

With the project virtual environment active:

```sh
python3 -m pytest
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

## Design references

- [Product requirements](docs/LLM_Token_Analyzer_PRD.md)
- [Technical specification](docs/llm_token_analyzer_technical_spec_v_1.md)
