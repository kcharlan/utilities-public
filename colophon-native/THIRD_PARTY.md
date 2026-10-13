# Third-party components and attribution

These notices cover retained dependencies and adapted rules/data. They do
not assert a new license for Kevin's application.

| Component | Version/source and retained notice |
| --- | --- |
| yyjson | 0.13.0; [VERSION](vendor/yyjson/VERSION) records exact URLs/digests; full [MIT license](vendor/yyjson/LICENSE). |
| Martian Mono | 1.1.0, static standard-width Light/Regular/Medium subsets embedded in `assets/font.css`; full [OFL 1.1](assets/OFL.txt), also embedded with the CSS. |
| Unicode normalization/casing | Unicode 16.0.0 committed `src/gen/unicode_nfc.c`/`.h`; full preserved [Unicode License V3](licenses/UNICODE.txt). |
| Unicode pricing properties | Unicode 17.0.0 Numeric, Extend/SpacingMark/ZWJ and Prepend compressed ranges in `assets/pricing_*_ranges.txt`; same [Unicode notice](licenses/UNICODE.txt). |
| CodexBar token/pricing rules | Adapted from [CodexBar](https://github.com/steipete/CodexBar) at `3bbf6bc48`; long-context thresholds and request-ledger validation/ownership/turn fallback follow `v0.74.1` (commit `7c08c0ae7`). MIT, © 2026 Peter Steinberger; full [notice](licenses/CodexBar-MIT.txt). |
| models.dev catalog rates/public seeds | Public [models.dev](https://models.dev/) data, MIT; full [notice](licenses/models.dev-MIT.txt). |

The CodexBar/models.dev attribution follows the maintained public Python
Colophon README and token-rule provenance. Curated rates and historical
seeds remain public input data, separate from editable private runtime history.
The models.dev license was retrieved from its upstream repository at
[`ab53a58f0694bce3125f033468ec0b69fad87137`](https://raw.githubusercontent.com/anomalyco/models.dev/ab53a58f0694bce3125f033468ec0b69fad87137/LICENSE).
The CodexBar notice comes from its pinned public source LICENSE. The Unicode
notice is extracted verbatim from the maintained public Colophon application's
commented V3 block, excluding surrounding code and property data.

Unicode pricing-property sources are
[DerivedNumericType](https://www.unicode.org/Public/17.0.0/ucd/extracted/DerivedNumericType.txt)
and [GraphemeBreakProperty](https://www.unicode.org/Public/17.0.0/ucd/auxiliary/GraphemeBreakProperty.txt).
Normalization/casing tables are generated from pinned Unicode 16.0.0 via
Python 3.14's Unicode database; see [development](docs/development.md).

Martian Mono's source is release
[`v1.1.0`](https://github.com/evilmartians/mono/releases/tag/v1.1.0), exact
source commit `8ffa86c2998677256252336f3662d60997e74b05`.
The retained OFL SHA-256 is
`ddafd2c3f37ef1d83ef284ca63e159befd3820850c5e9eded14ca52eee92c256`.
The embedded subsets require no runtime font tooling or network requests.
