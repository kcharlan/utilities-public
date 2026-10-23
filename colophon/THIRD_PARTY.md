# Third-party components and attribution

These notices cover retained dependencies and adapted rules/data. They do
not assert a new license for Kevin's application.

| Component | Version/source and retained notice |
| --- | --- |
| yyjson | 0.13.0; [VERSION](vendor/yyjson/VERSION) records exact URLs/digests; full [MIT license](vendor/yyjson/LICENSE). |
| Zstandard | v1.5.7 decompression sources in `vendor/zstd/`; [VERSION](vendor/zstd/VERSION) records the archive digest and per-file digests; full [BSD license](vendor/zstd/LICENSE) (upstream dual BSD/GPLv2, used under BSD). |
| Martian Mono | 1.1.0, static standard-width Light/Regular/Medium subsets embedded in `assets/font.css`; full [OFL 1.1](assets/OFL.txt), also embedded with the CSS. |
| Unicode normalization/casing | Unicode 16.0.0 committed `src/gen/unicode_nfc.c`/`.h`; full preserved [Unicode License V3](licenses/UNICODE.txt). |
| Unicode pricing properties | Unicode 17.0.0 Numeric, Extend/SpacingMark/ZWJ and Prepend compressed ranges in `assets/pricing_*_ranges.txt`; same [Unicode notice](licenses/UNICODE.txt). |
| CodexBar token/pricing rules | Adapted from [CodexBar](https://github.com/steipete/CodexBar) at `3bbf6bc48`; long-context thresholds and request-ledger validation/ownership/turn fallback, chronological per-request snapshot pairing, cross-copy mirror aliases and thread-settings priority follow `v0.74.1` (commit `7c08c0ae7`), with documented native adaptations. MIT, © 2026 Peter Steinberger; full [notice](licenses/CodexBar-MIT.txt). |
| ccusage Claude advisor entries and fast pricing | Adapted from [ccusage v20.0.33](https://github.com/ccusage/ccusage/tree/1308c416a7da73b63463f953a51b5ae29fb784a4), `rust/adapters/claude/src/lib.rs`, `rust/crates/ccusage-core/src/types.rs`, `cost.rs` and `pricing.rs`; `assets/ccusage_fast_multiplier_overrides.json` is copied verbatim. Full [MIT notice](licenses/ccusage-MIT.txt). |
| models.dev catalog rates/public seeds | Public [models.dev](https://models.dev/) data, MIT; full [notice](licenses/models.dev-MIT.txt). |
| Antigravity normalization | Adapted from [CodexBar commit e5d6977ba547aa7046eed3865f8ee1cdd5d58731](https://github.com/steipete/CodexBar/tree/e5d6977ba547aa7046eed3865f8ee1cdd5d58731/Sources/CodexBarCore/Providers/Antigravity), `AntigravityLocalReader.swift` normalization symbols; additional effort suffixes and unsupported Vertex routing documented in token rules. Existing [MIT notice](licenses/CodexBar-MIT.txt). |
| Antigravity behavioral oracle | Native ccusage 20.0.42 synthetic identity/output/model probes, not independently verified Rust-source algorithms; retained qualified public enum expectations in `tests/fixtures/antigravity/model-oracle.json`. Existing [MIT notice](licenses/ccusage-MIT.txt). |

The local [token-rule ledger](docs/token_rules.md) preserves upstream pins,
approved accounting adaptations and public seed provenance. Current native
rules and deliberate v0.74.1 differences are recorded in
[architecture](docs/architecture.md#usage-accounting-rules). These retained
documents and full notices supply attribution independently of the retired
Python application. Curated rates and historical
seeds remain public input data, separate from editable private runtime history.

Claude config-root, Desktop locator and transcript inventory selection follow
CodexBar `v0.74.1`, commit `7c08c0ae783b72040b728757eb85a6cfe4fc2443`,
`ClaudeConfigPaths`, `ClaudeDesktopProjectsLocator` and `inventoryClaudeRoots`.
Colophon enumerates resolved symlink roots and retains search-root provenance.
The existing full CodexBar MIT notice also covers these adapted rules.
The models.dev license was retrieved from its upstream repository at
[`ab53a58f0694bce3125f033468ec0b69fad87137`](https://raw.githubusercontent.com/anomalyco/models.dev/ab53a58f0694bce3125f033468ec0b69fad87137/LICENSE).
The CodexBar notice comes from its pinned public source LICENSE. The Unicode
notice was extracted verbatim from the historical Python Colophon application's
commented V3 block at repository baseline
`38d6998eb223f690fc9dc0bde0ba528fcf784449`, excluding surrounding code and
property data. The complete notice is retained locally in `licenses/UNICODE.txt`.

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
