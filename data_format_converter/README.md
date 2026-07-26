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

- the `@iarna/toml` parser and serializer;
- `js-yaml`;
- Google Fonts.

Network access is therefore required on first load unless those resources are
already cached. The selected theme is the only value saved to browser
`localStorage`.

### Token counts

Without an API key, the page uses a simple local estimate:

```text
ceil(number of characters / 4)
```

This is useful for relative comparisons, but it is not a model tokenizer and
must not be treated as an exact billable-token count.

If `window.OPENAI_API_KEY` is set, the current implementation first attempts a
three-second request to the legacy OpenAI Completions endpoint using
`gpt-3.5-turbo-instruct` and reads `usage.prompt_tokens`. Any missing key,
request error, rejection, or timeout falls back silently to the local estimate.
The status chip reports `✅ API` only when that request succeeds and
`⚙️ Local` otherwise.

To try the API path, set the key in the browser developer console before
calculating:

```javascript
window.OPENAI_API_KEY = "YOUR_API_KEY_HERE"; // pragma: allowlist secret
```

Putting an API key in a browser exposes it to that page and to anyone who can
inspect the browser session. Use a restricted, disposable key if you enable
this optional path.

### Web conversion limits

- The browser TOON implementation is a small key/value subset. It is separate
  from the Python CLI's `toon-format` library and is not a general-purpose TOON
  parser.
- Generated XML uses a synthetic `<root>` element around the common object.
  XML attributes are not preserved, and numeric/boolean-looking element text
  is converted to JavaScript number/boolean values when parsed.
- TOML cannot represent `null`; if any converted value is `null`, the
  structured conversion run reports an error.
- The browser code currently has no automated test suite. The Python tests do
  not validate the HTML/JavaScript implementation.

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
repository, so the initial installation requires network access.

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
are intentionally excluded because TOML has no null value. There are currently
no automated browser tests.

## Design references

- [Product requirements](docs/LLM_Token_Analyzer_PRD.md)
- [Technical specification](docs/llm_token_analyzer_technical_spec_v_1.md)
