# LLM Token Analyzer & Format Converter — Product Requirements

**Status:** Implemented
**Version:** 1.2
**Reviewed:** 2026-07-26

## 1. Product summary

The utility helps a user compare the textual size of common serialization
formats and convert data between them. It deliberately provides two independent
experiences:

1. A static browser interface for pasted data, format comparison, and token
   estimates.
2. A Python CLI for file conversion without token analysis.

The product is intended for local, low-friction experimentation. It is not a
schema migration tool, an exact model-pricing calculator, or a lossless
converter for every feature of the supported formats.

## 2. Supported formats

| Format | Web input/conversion | Web count | CLI input/output |
| --- | --- | --- | --- |
| Raw text | Count only | Yes | No |
| JSON, pretty | Yes | Yes | Yes (`json`) |
| JSON, compact | Yes | Yes | Output (`jsonc`) |
| XML | Yes | Yes | Yes |
| YAML | Yes | Yes | Yes |
| TOON | Limited browser subset | Yes | Yes, via `toon-format` |
| TOML | Yes, except data containing null | Yes | Yes, except data containing null |

## 3. Browser experience

The browser UI must:

- remain a single static `web/index.html` with no application backend;
- provide one editable panel per format and a calculate action for each;
- validate the selected structured input before conversion;
- populate every structured panel from a valid source object;
- show inline errors and clear stale counts/comparison results after a failed
  calculation;
- show token counts, their source (`API` or `Local`), the smallest and largest
  renderings, and percentage differences from the smallest;
- support system, light, and dark themes and persist only the theme choice;
- treat raw text as a count-only operation.

The page may load parsing libraries and fonts from public CDNs. Consequently,
the current product requires network access for a first uncached load of all
features.

### Token-count contract

The default count is `ceil(text.length / 4)`. It is explicitly an estimate, not
GPT-5 tokenization or a billing measurement.

When a user explicitly exposes an API key as `window.OPENAI_API_KEY`, the page
may attempt the legacy Completions request implemented in `web/index.html`.
Failure must fall back to the local estimate without preventing conversion.

### Browser conversion boundaries

- JSON is the common in-memory representation.
- Generated XML uses a synthetic `root` element. XML attributes and exact XML
  scalar typing are outside the lossless-conversion contract.
- Browser TOON support is a small, local syntax adapter and is not required to
  match every construct accepted by the Python `toon-format` package.
- TOML conversion must reject a value tree containing `null`.

## 4. CLI experience

The CLI is invoked as:

```text
python src/data_convert.py --input FILE --to FORMAT [--output FILE]
```

It must:

- infer JSON, XML, TOON, YAML, or TOML from the input extension, defaulting
  unknown extensions to JSON;
- accept `json`, `jsonc`, `xml`, `toon`, `yaml`, and `toml` as targets;
- write to the explicit output path or to a derived filename in the current
  directory;
- emit pretty sorted JSON for `json` and compact sorted JSON for `jsonc`;
- add an XML root wrapper when the common object does not already have exactly
  one top-level key;
- reject TOML output when any nested value is `None`;
- return nonzero exit codes and a one-line JSON error on standard error for
  runtime failures;
- never perform token counting or make an OpenAI request.

## 5. Quality requirements

- Python parsing and serialization behavior must be covered by pytest.
- CLI tests must cover success, malformed input, absent input, default output
  naming, TOML null rejection, and meaningful cross-format round trips.
- Tests and examples must use conspicuously synthetic data.
- The README must distinguish the browser's heuristic/API behavior from the
  CLI and document lossy format boundaries.

The browser implementation currently has no automated tests; this is a known
coverage boundary, not a claim that the Python suite validates browser behavior.

## 6. Privacy and operational constraints

- Structured values stay in the browser unless the optional API path is used.
- No API key is stored by the application.
- Users must be warned that setting a key in browser JavaScript exposes it to
  that browser context.
- The project must not include real keys, private data, or realistic personal
  fixtures.

## 7. Deliverables

- `web/index.html`
- `src/data_convert.py`
- `src/converters/`
- `requirements.txt`
- `tests/`
- `README.md`
- this product requirements document and the current technical specification
