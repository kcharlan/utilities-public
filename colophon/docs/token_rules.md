# Token and pricing rules

Curated price-history seed provenance: public `https://models.dev/api.json`,
downloaded once on **2026-10-04**, SHA-256
`9095031166fec35632248c736bd29d383771ea8eb2c73dcc5ccdb3082923bc6e`.
The downloaded snapshot stays outside the repository. Method: run
`.venv/bin/python tests/tools/seed_price_history.py --snapshot <external-snapshot.json> --snapshot-date 2026-10-04`
and paste its deterministic `indent=2` JSON between `CURATED_PRICE_HISTORY`
markers. The seed combines sorted bundled ids and normalized priceable OpenAI
catalog ids, resolving with Task 13's pinned resolver. Historical null periods
and fixed cutoff periods use the upstream table; all other models start at null.
No catalog `last_updated` values are used. The committed block contains only
reviewed public rates, with 56 entries for 53 model keys.
The tool checks raw floating `limit.context` spellings before normalization,
using Task 13's source-grounded JSONDecoder Int boundary results. The 53
OpenAI context fields in this snapshot are integers and are unaffected;
the checked parser regenerates the exact same seed bytes. Cost fields retain
the existing Double conversion and invalid model children are skipped individually.
The source boundary follows Swift Foundation's
[JSONDecoder integer conversion](https://github.com/swiftlang/swift-foundation/blob/swift-6.2-RELEASE/Sources/FoundationEssentials/JSON/JSONDecoder.swift#L1001-L1104)
and [Foundation Decimal parsing](https://github.com/swiftlang/swift-foundation/blob/swift-6.1-RELEASE/Sources/FoundationEssentials/Decimal/Decimal.swift#L320-L424).
For the large-number slow path, the parser fills a UInt128 mantissa and
discards excess fractional digits, then compacts trailing zeros. The released
JSONDecoder's internal `FixedWidthInteger.init?(_ decimal: Decimal)` requires
the compacted mantissa to fit UInt64 before exponent scaling, divides without
checking fractional remainders, and sizes the positive magnitude before
applying its sign. This accepts `.1`/`.01` near 2^53 while rejecting nearby
tiny fractions and larger mantissas; mathematical integrality is not the rule.
Independent synthetic Foundation probes pin both sides of that boundary;
rate resolution stays pinned to
CodexBar `3bbf6bc48`.

Normative source: `steipete/CodexBar` at `3bbf6bc48`. File paths in this
ledger are relative to `Sources/CodexBarCore/Vendored/CostUsage/`. The launcher
ports routing into scalar observations; subsequent accounting replays them.
The suite uses hand-derived synthetic observations and has no dependency on
an upstream checkout, binary, cache or fixtures.

| Rule | Upstream file | Function | Commit | Decision | Notes |
| --- | --- | --- | --- | --- | --- |
| Historical rate seed | CostUsagePricing.swift | codexHistoricalPricing (394–407), gpt56Pricing (47–61) | 3bbf6bc48 | Ported values, adapted representation | Sol cutoff 2026-08-21; Terra/Luna cutoff 2026-07-30. Historical null entries use the exact decimal per-million tuples and 272000 threshold; cutoff entries use the explicit snapshot resolver. |
| Priority seed | CostUsagePricing.swift | codexAPIFastMultiplier, codexAPIFastAllowsLongContext (682–692) | 3bbf6bc48 | Ported | ×2 for 5.4, 5.4-mini, 5.6 Sol/Terra/Luna and 6 Astra; ×2.5 for 5.5. Cap 272000 except Astra's null cap. |
| Dated ledgers and recording | Colophon spec §5.6, plan Task 16/D15 | validate_ledger, PriceHistory, record_catalog_rates, append_user_ledger | — | Colophon addition, approved A4 item 2 | Exact pricing keys; null first, then dated periods; manual > catalog > curated ties. Record at fetch time, compare non-manual standard/long rates only, carry priority, preserve existing JSON on append, detect mtime edits. Compiler diagnostic wiring belongs to Task 18. |
| Ledger JSON metadata | Colophon spec §5.6, plan Task 16 | validate_ledger, append_user_ledger | — | Literal JSON contract | Unknown fields stay intact. Duplicate comparison distinguishes booleans from numbers recursively, retains numeric equality, and excludes only note/recorded_at. Reject nonstandard constants on read and all nonfinite metadata during direct validation, with entry-indexed errors. |
| Optional ledger context compatibility | CostUsagePricing.swift | codexCostUSD (704–726) | 3bbf6bc48 | Ported behavior | An omitted long_context selects standard rates. cost_usd reads it optionally without adding a null field to picked or persisted entries. |
| One observation stream during the existing read | CostUsageScanner.swift | parseCodexFileCancellable, onLine (4772–5005) | 3bbf6bc48 | Adapted representation | Cache observations instead of reducing usage immediately. Raw bytes route independently of Colophon's recovered display records. |
| Physical position and upstream position | CostUsageJsonl.swift; CostUsageScanner.swift | flushLine (358–359); onLine (4773–4774) | 3bbf6bc48 | Ported | `line` counts physical lines; `uidx` counts prior nonzero-byte lines. Whitespace and carriage-return-only lines advance `uidx`. |
| Bounded prefix | CostUsageJsonl.swift | appendSegment (342–353) | 3bbf6bc48 | Ported | Strictly more than 262144 bytes truncates; extractors receive only the first 262144 bytes. |
| Prefix Unicode handling | CostUsageScanner+CodexTruncatedPrefix.swift | truncatedUTF8String (46–55) | 3bbf6bc48 | Ported | Try the prefix with zero through four trailing bytes removed; otherwise drop the truncated observation. |
| Prefix field parsing | CostUsageScanner+CodexTruncatedPrefix.swift | extractJSONField, parseJSONString, skipJSONWhitespace (125–209) | 3bbf6bc48 | Ported | Root discriminator uses depth 1. Text escapes remove a backslash literally; they do not JSON-unescape. Object extraction returns the remaining suffix. Swift Character whitespace differs from the Foundation trim set. |
| Truncated context | CostUsageScanner+CodexTruncatedPrefix.swift | extractCodexTruncatedTurnContext, isCompleteJSONObject (22–82) | 3bbf6bc48 | Ported | A usable root timestamp and payload object are required. Model lookup has the context tri-state. An incomplete payload cannot clear a model merely because a blank field precedes the truncation. `XC` stores that tri-state. |
| Truncated metadata | CostUsageScanner+CodexTruncatedPrefix.swift; CostUsageScanner.swift | extractCodexTruncatedSessionMetadata (4–20); onLine (4799–4820) | 3bbf6bc48 | Planned adaptation | Store eligible `XM` observations even before knowing whether the pre-pass selects a subagent. Task 14 consumes them only in upstream's subagent pending mode. ID aliases are payload-only here. |
| Usage consumes a line before type routing | CostUsageScanner.swift | onLine (4822–4835) | 3bbf6bc48 | Ported | Literal raw `"usage"` requires a valid dictionary, absent root `type` (null still counts as present), and a valid bare-usage envelope. Failure consumes the line. |
| Bare envelopes and number aliases | CostUsageScanner.swift | codexBareUsage, codexBareUsageInt (3918–3972) | 3bbf6bc48 | Ported | Select the first dictionary usage under root, data, result or response. Require input and output numeric aliases, clamp negatives, and reject an all-zero result. |
| Bare cached input is already subtracted | CostUsageScanner.swift | codexBareUsage (3937–3941) | 3bbf6bc48 | Ported | Cached aliases use the first numeric key, not the token-count maximum. `B.input = max(0, input - cached)`; later accounting must not subtract it again. |
| Bare model and timestamp | CostUsageScanner.swift | codexBareUsage (3943–3961); handleBareUsage (4279–4307) | 3bbf6bc48 | Adapted representation | Preserve the root timestamp or null for later fallback to the last accepted token timestamp. Model evidence comes from root model/model_name then data model/model_name. Do not infer a timestamp here. |
| Raw filters | CostUsageScanner.swift | onLine (4837–4854) | 3bbf6bc48 | Ported | Four literal type-value markers pass. Compact event_msg lines without a literal token_count or task_started marker are dropped. Escaped type keys can reach dictionary fallback when the literal value marker remains. |
| Fast byte fields | CostUsageScanner+CodexFastJSON.swift | extractJSONByteField and string/object helpers (4–168, 249–309) | 3bbf6bc48 | Ported | Scan braces and quoted spans without validating JSON. Match only unescaped keys at depth 1; select the first successfully typed value. This can route glued bytes that strict JSON would reject. |
| Fast integers and booleans | CostUsageScanner+CodexFastJSON.swift | parseJSONByteInt, parseJSONByteBool (170–224) | 3bbf6bc48 | Ported | Integer prefixes stop before fraction/exponent bytes and check positive magnitude overflow at Int.max. Booleans are not fast integer values. Bool prefixes use literal true/false. |
| JSON fallback | CostUsageScanner.swift; CostUsageJsonl.swift | onLine dictionary path (4881–5005); hasCompleteJSONTail (383–392) | 3bbf6bc48 | Stand-in | Use stdlib JSON parsing, reject non-JSON constants and recursively reject unpaired surrogates. Preserve numeric lexemes for Foundation integer casts. A small tail needs valid fragments; a terminated fast line does not require full JSON validation. |
| Foundation integer casts | CostUsageScanner.swift | codexBareUsageInt (3965–3972), tokenTotals/toInt (4970–4989) | 3bbf6bc48 | Library compatibility | NSNumber includes bool, truncates floats and has signed Int width. Short floating mantissas saturate. Large integers and long floating mantissas select Decimal: discard least-significant digits until the UInt128 mantissa fits, then validate the signed eight-bit exponent before compacting trailing zeros. Convert the mantissa to signed Int64 before decimal division, truncate toward zero, and apply the Decimal sign afterward. Unrepresentable Decimal lexemes reject the fallback JSON object and leave a small tail unconsumed. Synthetic standalone Foundation probes verify representation boundaries and casts outside the suite. |
| Token totals | CostUsageScanner.swift | codexTotals (3644–3676), tokenTotals (4977–4989) | 3bbf6bc48 | Ported | Clamp all components at zero; cached is the maximum of cached_input_tokens and cache_read_input_tokens; reasoning is null if absent, otherwise clamped between zero and output. Preserve fast/fallback number-cast distinctions. |
| Model trimming and context tri-state | CostUsageScanner.swift | codexModelEvidence, codexTurnContextModel (3453–3475) | 3bbf6bc48 | Ported | Foundation whitespacesAndNewlines is an explicit 26-scalar set, including U+200B and excluding U+001C–U+001F. First nonblank payload.model, payload.model_name, info.model, info.model_name sets context; present strings all blank clear; omitted/non-string fields preserve context. |
| Token model evidence | CostUsageScanner.swift | parseCodexFastLine (3866–3888); onLine (4964–4968) | 3bbf6bc48 | Ported | First nonblank info.model, info.model_name, payload.model, root.model. |
| Session metadata identities | CostUsageScanner.swift | codexSessionId (3595–3618), codexSessionMetadata (3994–4011) | 3bbf6bc48 | Ported | Payload id, root id, payload session_id/sessionId, root session_id/sessionId. Fast strings skip empty values; dictionary nil-coalescing preserves the first present string, including empty. |
| Session metadata provenance | CostUsageScanner.swift | codexForkParentId, codexHistoryBaseThreadId, codexIsSubagentThread (3477–3571); normalizedCodexProjectPath (3621–3628) | 3bbf6bc48 | Ported | Trim fork/history aliases, detect string or object subagent provenance, expand tilde and standardize absolute cwd. Preserve the empty-subagent-string fast/dictionary difference. Metadata fork timestamp prefers payload over root. |
| Turn identities | CostUsageScanner.swift | byte codexTurnID (3574–3593), dictionary codexTurnID (5266–5274) | 3bbf6bc48 | Ported | turn_id, turnId, id in payload then info; fast skips empty strings while dictionary fallback accepts them. |
| Timestamp routing validity | CostUsageScanner.swift; CostUsageScanner+Timestamp.swift | codexFastLineTimestampValidity (3975–3987); dayKeyFromTimestamp/dayKeyFromParsedISO (105–200) | 3bbf6bc48 | Ported with stdlib library compatibility | Metadata bypasses validity. Other regular observations need a usable day key. The fast calendar path normalizes calendar fields and scans backwards for Z/+/-; it imposes no RFC3339 fraction, suffix or component-range validation. Historical formatter fallback remains separate. |
| Historical timestamp fallback | CostUsageScanner+Timestamp.swift | parseISO/parseHistoricalISO (22–32) | 3bbf6bc48 | Fixed formatter slice | Native successes already satisfy dayKeyFromTimestamp. Historical numeric fields share ICU number parsing: Unicode decimal digits, minus aliases and scientific notation; a leading plus is rejected. Formattable reads signed Int32 from Int64 storage or Binary64 union bits. Preserve Gregorian/Julian cutover, checked year/day/epoch subtraction and Double millisecond normalization. Fractional parsing counts Unicode Nd digits and scales through an Int32 divisor. Zone digits remain ASCII, case-insensitive named-zone prefixes remain separate, and literal T skips bidi controls but not whitespace. Display event-time parsing is unchanged. |
| Millisecond conversion chain | CostUsageScanner+Timestamp.swift; CostUsageScanner.swift | dateFromTimestamp, parseISO, parseNativeRFC3339, parseHistoricalISO (22–89); unixMilliseconds (4262–4267) | 3bbf6bc48 | Clarification | Parse native RFC3339 first; retain only the first three source fractional digits (at most nine accepted natively); construct Date; otherwise try historical fractional then plain formatter; finally round the parsed Date's epoch seconds times 1000. Do not round additional source digits. Token observations retain raw timestamps; Task 6's native-precision regressions remain intact. |
| Ordinals | CostUsageScanner.swift | codexLineOrdinal (3989–4000), onLine (4858, 4887) | 3bbf6bc48 | Ported | Fast signed integer extraction versus fallback NSNumber.intValue. Include null when unavailable. |
| Metadata pre-pass | CostUsageScanner.swift | parseCodexSessionMetadata (4013–4106), initialization (4698–4709) | 3bbf6bc48 | Adapted representation | Emit `P` first, selecting the first metadata result from a line no longer than 256 KiB anywhere in the bounded bytes. Include an unterminated segment even if tail routing leaves it unconsumed. The selection runs independently of usage filtering. No second file open is needed. |
| Structural tail state | CostUsageJsonl.swift | JSONTailState (45–270) | 3bbf6bc48 | Ported | Byte scalar/number/container/string/escape transitions are preserved. Bare numbers need a delimiter; whitespace alone is incomplete; invalid starting bytes count structurally complete; closing containers clamp depth at zero. Structural completeness is not JSON validity. |
| Tail routing and cache fact | CostUsageJsonl.swift | hasCompleteJSONTail, scanBounded EOF branches (383–417) | 3bbf6bc48 | Ported | Small tails also require accepted JSON fragments. Truncated tails require structural completeness only. Otherwise emit no routed observation and mark unconsumed_tail. Persist only observations and this byte-derived fact. |

The Task 6 timestamp wording `round(ms)` describes rounding an already parsed
Date. It does not license rounding higher-precision source digits. Native
`.0006` becomes zero milliseconds, `.0015` becomes one millisecond and a
fraction immediately before an epoch or second boundary does not carry into
the next second. Historical formatter acceptance is broader than the display
RFC3339 parser; applying display strictness to token routing would discard
observations upstream retains.

The stream representation intentionally preserves `XM` ahead of the accounting
pending-mode gate and `B` ahead of timestamp/model fallback. Those adaptations
are specified by the implementation plan; they introduce no new accounting
rule. No pricing, fork reduction or day-range filtering is implemented here.

The historical formatter slice is portable standard-library code. Supplemental
library derivation uses Apple's public ICU source at
`9e80977766f830c93e3cdae3d5628997e1a61b63` (ICU 76.1):
`icu/icu4c/source/i18n/smpdtfmt.cpp` (`subParse`, `parseInt`, `countDigits`,
`matchLiterals`), `fmtable.cpp`/`unicode/fmtable.h` (`adoptDecimalQuantity`,
`getLong`), `gregocal.cpp` (`handleGetExtendedYear`, `handleComputeJulianDay`,
`handleComputeMonthStart`), `calendar.cpp` (`computeTime`,
`computeGregorianFields`), `numparse_scientific.cpp`, `numparse_symbols.cpp`,
`numparse_decimal.cpp` (`DecimalMatcher::match`, exponent saturation),
`source/common/static_unicode_sets.cpp` and `source/data/locales/root.txt`.
These supplement the pinned CodexBar formatter-options call; they do not
replace it. Synthetic probes corroborate this slice against the installed
macOS Foundation/ICU 78.1. They are evidence outside the repository and never
test-suite dependencies. A direct CoreFoundation prototype agreed on the
calendar cases but accepted an `INF` spelling that the Swift formatter rejects;
Swift formatter results govern that discrepancy. For fractions with at least
35 digits, the Int32 divisor wraps to zero; the observed macOS ARM64 formatter
division yields zero milliseconds, which this slice preserves. This is library
compatibility evidence, not a new token-accounting rule.

Scientific exponent magnitude is checked against ICU's Int32 maximum before
constructing a Python Decimal. A larger positive exponent saturates to infinity;
a larger negative exponent clears the quantity to zero. Both resulting number
casts yield zero, including signed and zero mantissas. Parse Unicode Nd exponent
digits linearly, strip leading zeros, and compare only the bounded significant
magnitude. This preserves accepted observations beyond Python Decimal's exponent
range and Python's integer-string digit limit; it does not catch and drop them.

The pinned `CostUsageJsonl.swift` tail check (391) and scanner bare/dictionary
fallbacks (4824, 4879) delegate to Foundation JSONSerialization. Its observed
limit permits nonempty arrays/dictionaries only through container depth 512;
an empty terminal container at depth 513 is accepted. The fallback validates
container paths iteratively without changing Python's recursion limit, retaining
source object pairs temporarily so an overwritten duplicate key cannot erase
an excessive nesting path or invalid Unicode string. Synthetic Foundation
probes establish that duplicate keys keep the first source value, including
nested usage fields; the fallback preserves that dictionary projection.
Terminated typed fast routing and structurally complete truncated
tails retain their source behavior without whole-object JSON validation.

## Task 8 — discovery and processing order

The discovery port reads `CostUsageScanner.swift` at `3bbf6bc48`:

| Colophon rule | Upstream source | Treatment |
|---|---|---|
| Sessions root before archived root; separately sorted paths | `codexSessionsRoots`, `listCodexSessionFiles`, scan root loop (2151–2187, 5950–5968) | Port; full recursive cold discovery over all history. |
| Canonical calendar day directories, shallow day contents | `listCodexSessionFilesByDatePartition` (2740–2810) | Port; enumerate existing canonical valid days instead of probing absent days. Ancestors are unfiltered, because upstream generates day paths directly; only day entries apply hidden filtering. |
| Flat and legacy `.jsonl`, case insensitive; root-level four-number-character years excluded from legacy traversal | `listCodexSessionFilesFlat`, `listCodexLegacySessionFilesRecursive`, `isCodexDatePartitionAncestor` (3283–3330), `isDatePartitionComponent` (2479–2481) | Port; malformed year contents are not a recursive fallback. |
| Lexical absolute keys; `/private/var/` maps to `/var/` | `codexPathKey` (2533–2543) | Port; retain general symlink spellings in parser and cache keys. |
| Path and device/inode de-duplication | Root loop (5950–5968), `scanCodexFile` (5320–5323) | Port; the first discovery path owns a filesystem identity. |
| Admit directory-shaped `.jsonl`; failed stat retains zero size/mtime without identity | `CostUsageScanner+CacheHelpers.swift`, `codexFileMetadata` (660–677); scanner listing functions above | Port; actual open/read errors are reported by Colophon's scan. No regular-file-only filter is added. |
| Descending millisecond mtime, ascending size, ascending path | `sortedCodexSessionFilesNewestFirst` (6717–6732) | Port; scan records retain this processing order even across mixed cache hits and misses. |

Darwin's `FileManager` enumeration options also exclude hidden resource flags
and package descendants. Standard-library `ctypes` calls the same platform
CoreFoundation `kCFURLIsHiddenKey` and `kCFURLIsPackageKey` resource properties,
with explicitly typed functions and owned references released in `finally`.
No filename-extension approximation classifies packages. Native loading is lazy
and cached. Primary API references: [hidden property](https://developer.apple.com/documentation/corefoundation/kcfurlishiddenkey?language=objc)
and [package property](https://developer.apple.com/documentation/corefoundation/kcfurlispackagekey?language=objc).
Synthetic macOS Foundation and CoreFoundation probes corroborated package,
hidden-flag, directory-shaped `.jsonl`, and symlink behavior outside the
repository; no probe or upstream checkout is a test-suite dependency.

On non-Darwin platforms, package exclusion is deliberately absent, matching
[`NSURLDirectoryEnumerator.nextObject` in swift-corelibs-foundation](https://github.com/swiftlang/swift-corelibs-foundation/blob/44cd6163efc4d12bef854bed34bf17cda65747d4/Sources/Foundation/FileManager%2BPOSIX.swift#L354-L397):
it explicitly ignores `skipsPackageDescendants`, filters dot-prefixed names,
and uses physical traversal without descending symlinks. Platform assertions
run without skipped tests. This is library compatibility for the pinned
scanner's discovery options, not an added token-accounting deviation.

The private parse cache is Colophon's own adaptation: changed files reparse
from byte zero; keys retain scan-start nanosecond mtime and size and the last
4096 snapshot bytes' SHA-256. Cache entries are buffered until commit; rebuild
writes a sibling directory and swaps it only after scanning succeeds. Invalid
cache key types and boolean parser versions never provide hit evidence.

Source detail: a visible entry remains discoverable under a hidden-flagged
canonical year, month or day directory. Upstream opens generated day paths
directly; its hidden option filters entries within each day, rather than
ancestors. Synthetic direct-day Foundation probes verified all three cases.
The spec's broad non-hidden discovery wording is read in this source-defined
sense, rather than extended to every ancestor.

Scanning buffers records without committing. The caller commits after a
successful page write (Task 18); `cache._live_paths` keeps the scan-start
inventory including unreadable candidates, so pruning never needs a second
discovery pass. A successful rebuild scan can still be aborted before commit.

The successful rebuild installation rename is the commit point. Pre-install
scan/write/swap failures retain or restore the old cache. After installation,
the cache sets `_committed` and is marked finished before old-backup cleanup:
cleanup `OSError` is
best effort and leaves the backup for dead-pid maintenance; `KeyboardInterrupt`
propagates with the committed state intact. Callers must report this committed
state honestly rather than claiming the previous cache was retained after a
post-install interruption. `_committed` distinguishes this state from an
aborted scan (both are finished), and abort never changes it. No rollback
attempts use a partly deleted backup.

Rebuild swap recovery captures the old and new directories' device/inode
identities before either rename, without following symlinks. If an interrupt
arrives after a completed rename but before bookkeeping, exception handling
recognizes the installed new identity and marks it committed, or restores the
matching owned old backup while the matching new directory still awaits
installation. Missing paths alone do not prove either outcome. Preexisting
backups are rejected before mutation handling, and recovery preserves the
original exception even when filesystem repair fails. Trace-injected synthetic
interrupts exercise the rename and bookkeeping boundaries, including existing
and first-ever rebuild installations; no signal timing assumption is required.

Abort finalization always clears the buffer and closes the cache without
changing `_committed`, including when rebuild-directory removal fails. Direct
`abort()` propagates that cleanup exception and retains its object privately
as `_abort_cleanup_error`. During scan failure or failed FORMAT initialization,
the original exception object instead propagates with a note describing the
cleanup failure; the same private field retains the cleanup object. A retained
rebuild directory remains subject to the existing dead-pid cleanup rules.
This is Colophon's transaction/error contract, not an additional upstream
parse or discovery rule. Synthetic regressions cover both filesystem errors
and a second interruption during abort cleanup.

## Task 13 — model normalization and pricing

| Rule | Upstream file and function | Commit | Decision | Notes |
| --- | --- | --- | --- | --- |
| Bundled literals and normalization | CostUsagePricing.swift, `codex` (84–208), `gpt56Pricing` (45–60), `normalizeCodexModel` (482–518) | 3bbf6bc48 | Ported | Preserve every non-nil per-token literal in `CURATED_BUNDLED`. Strip only the exact `openai/` prefix; apply four aliases; keep bundled keys; fold dashed dates only for bundled bases. Foundation whitespace and Swift Character regex semantics remain intact. |
| Lookup candidates and catalog spelling | ModelsDevPricing.swift, `ModelsDevCatalog.pricing`, `ModelsDevProvider.pricing`, `ModelsDevModel.pricing`, `ModelsDevModelIDNormalizer.candidates` (65–73, 185–251, 343–395) | 3bbf6bc48 | Ported | First priceable direct key wins, then normalized model IDs. Candidate expansion remains ordered. Swift string equality is canonical-equivalent; normalized-index hits retain catalog spelling, while direct-key hits retain candidate spelling. Missing input/output or malformed decoded fields provide no price evidence. |
| Provider-qualified targets | CostUsagePricing.swift, `codexModelsDevPricingTargets` (453–485); ModelsDevPricingTargetResolver.swift, whole file | 3bbf6bc48 | Recorded deviation, A4 item 5 | Keep only OpenAI providers. Other provider-qualified IDs remain unpriced, including bundled-looking model names. The OpenAI target and alias ordering follows source. |
| Resolver precedence | CostUsagePricing.swift, `resolvedCodexPricing` (562–620) | 3bbf6bc48 | Ported | Raw catalog lookup precedes normalized fallback. Catalog standard rates win; missing cache rates fall back to bundled values. Bundled threshold wins over catalog threshold. Absent catalog context block permits the bundled long tuple; a present empty/partial block preserves catalog omissions and catalog fallback order. Raw-alias cases match upstream (C1). |
| History and numeric representation | CostUsagePricing.swift, `resolvedCodexPricing` and historical constants (394–407) | 3bbf6bc48 | Adapted representation, A4 | Historical lookup is omitted because dated ledgers own it; cutoffs remain exact epoch milliseconds. Per-million catalog numbers are kept as given. Bundled per-token numbers use `float(Decimal(repr(x)).scaleb(6))`; per-token reconstruction differs by at most one ulp. Fill long fields from unfilled raw fields before standard caches. |
| Standard cost formula | CostUsagePricing.swift, `codexCostUSD(pricing:…)` (694–731) | 3bbf6bc48 | Ported | Clamp total input, cached subset and output. Bill zero cache-write tokens, while preserving logged writes for later display. Use full-request long rates strictly above the threshold. Keep the four terms in source order; reported output already includes reasoning. |
| Priority formula and Fast multiplier | CostUsagePricing.swift, `codexPriorityCostUSD`, `codexAPIFastMultiplier`, `codexAPIFastAllowsLongContext` (646–692) | 3bbf6bc48 | Ported; dated priority source adapted, A4 | Separate priority entry supplies multiplier and cap. Over-cap requests return no priority cost; Astra has no cap. Multiply standard cost only after its source-order calculation. The public API multiplier switch is distinct from Codex credit multipliers. |

models.dev `tiers` may describe a 272,000-token threshold, while upstream's
`ModelsDevModel.pricing` uses 200,000 whenever `context_over_200k` exists and
ignores `tiers`. Colophon keeps this upstream simplification for parity.
Bundled thresholds still take precedence, so a bundled 272,000 threshold
can coexist with a catalog context block. Revisit only when the pinned
upstream implementation changes.

`ModelsDevIndex.pricing` returns a dictionary with `provider_id`, `model_id`,
`normalized_model_id`, unfilled `per_million` rates, and `long_context` or
null. The matched `normalized_model_id` is the catalog identity needed by
the later priority-override ledger. `resolve_rates` alone fills omissions.

Edge-case decisions:

- Malformed optional catalog fields, booleans and values outside finite Double representation provide no price evidence; upstream skips models whose typed decoder fails.
- A wrapped provider map is decoded as a whole; one malformed provider abandons it and triggers top-level fallback, while malformed models remain individually skippable.
- `limit.context` accepts finite integral JSON numbers under the source's checked Int conversion, including decimal/exponent float spellings; boolean, fractional and out-of-range values reject the model.
- The dict interface checks each already decoded number's JSON-compatible spelling; raw catalog lexemes must be validated before Python float conversion at the fetch boundary, since lost original digits cannot be reconstructed.
- A normalized OpenAI fallback target is appended even when the target resolver rejected the original nested or whitespace-bearing route; source fallback order remains authoritative.
- Non-numeric `tiers` content is ignored because it is outside upstream's decoded cost keys.
- A catalog `context_over_200k: {}` is present evidence of a threshold, not absence; source omission precedence therefore applies.
- Canonically equivalent IDs compare equal but preserve the source spelling selected by the upstream branch; no case folding or compatibility normalization is added.

The narrow pricing regex compatibility slice embeds compressed public
Unicode 17.0.0 ranges from
[DerivedNumericType.txt](https://www.unicode.org/Public/17.0.0/ucd/extracted/DerivedNumericType.txt)
and [GraphemeBreakProperty.txt](https://www.unicode.org/Public/17.0.0/ucd/auxiliary/GraphemeBreakProperty.txt).
Only Numeric, Extend/SpacingMark/ZWJ and Prepend properties are embedded.
The suffix patterns need only digit and literal graphemes, following
[UAX #29 GB9, GB9a and GB9b](https://www.unicode.org/reports/tr29/).
The non-ASCII String regex path treats numeric Characters as digits, including
superscripts, fractions, Roman numerals and numeric CJK characters; the ASCII
NSRegularExpression path uses scalar digits. Delimiters and prefix/suffix
literals must match complete Characters. Synthetic standalone Swift probes
verified every embedded range endpoint and delimiter boundaries; no probe,
download, upstream checkout or binary is a test-suite dependency.
Copyright © 1991–2026 Unicode, Inc.; the Unicode License V3 copyright and
permission notice is included beside the data in the launcher so standalone
copies retain it. The source text is [Unicode License V3](https://www.unicode.org/license.txt).

## Task 14 — fallback token accounting

Every function below follows `steipete/CodexBar` at `3bbf6bc48`. The stored
reference outputs are immutable. The harness copies inputs into temporary
homes, restores their recorded mtimes and applies each reference's bucket zone.
Rows are compared in emission order before independent model/day totals.

| Python function or type | Upstream file and function | Treatment |
| --- | --- | --- |
| `Totals`, `ForkBaseline` | `CostUsageScanner.swift`, `CodexForkBaseline` and `CostUsageCodexTotals` consumers (431–667) | Frozen totals and tagged tuple representation. |
| `codex_totals_equal` | `CostUsageScanner.swift`, `codexTotalsEqual` (436–438) | Port. |
| `codex_totals_at_least`, `codex_totals_at_most` | `CostUsageScanner.swift`, `codexTotalsAtLeast`, `codexTotalsAtMost` (440–446) | Port. |
| `codex_looks_like_stale_regression` | `CostUsageScanner.swift`, `codexLooksLikeStaleRegression` (448–475) | Port. |
| `codex_should_prefer_total_delta` | `CostUsageScanner.swift`, `codexShouldPreferTotalDelta` (477–489) | Port. |
| `codex_add_totals`, `codex_min_totals`, `codex_max_totals` | `CostUsageScanner.swift`, `codexAddTotals`, `codexMinTotals`, `codexMaxTotals` (491–513, 553–564) | Port. |
| `codex_total_delta` | `CostUsageScanner.swift`, `codexTotalDelta` (515–529) | Port. |
| `codex_divergent_total_delta` | `CostUsageScanner.swift`, `codexDivergentTotalDelta` (531–551) | Port. |
| `codex_contained_total_delta` | `CostUsageScanner.swift`, `codexContainedTotalDelta` (573–596) | Port. |
| `codex_add_optional`, `codex_min_optional`, `codex_max_optional`, `codex_subtract_optional` | `CostUsageScanner.swift`, `codexAddOptional`, `codexMinOptional`, `codexMaxOptional`, `codexSubtractOptional` (598–620) | Port. |
| `codex_optional_delta`, `codex_divergent_optional_delta`, `codex_contained_optional_delta` | `CostUsageScanner.swift`, `codexOptionalDelta`, `codexDivergentOptionalDelta`, `codexContainedOptionalDelta` (622–647) | Port. |
| `codex_post_latch_event_delta` | `CostUsageScanner.swift`, `codexPostLatchEventDelta` (654–666) | Port. |
| `CodexTotalsTracker.__init__`, `is_seen`, `latch_if_below_watermark`, `commit_observed`, `raise_watermark` | `CostUsageScanner.swift`, `CodexTotalsTracker.init`, `isSeen`, `latchIfBelowWatermark`, `commitObserved`, `raiseWatermark` (669–723) | Port; `SEEN_RAW_TOTALS_LIMIT = 64`. |
| `CodexSnapshotAccumulator.__init__`, `state`, `apply` | `CostUsageScanner.swift`, `CodexSnapshotAccumulator.init`, `state`, `apply` (725–855) | Port; accumulator state uses Python keys. |
| `InheritedTotalsResolver.inherited_totals` | `CostUsageScanner.swift`, `CodexInheritedTotalsResolver.inheritedTotals(for:atOrBefore:)` (1692–1734) | Port cutoff and recursion guard over cached streams. |
| `InheritedTotalsResolver.inherited_totals_from` | `CostUsageScanner.swift`, private `inheritedTotals(from:cutoffTimestamp:cutoffDate:)` (1736–1792) | Port; replay from the first snapshot, without checkpoints or a monotonic fast path. |
| `InheritedTotalsResolver.snapshot_resolution` | `CostUsageScanner.swift`, `snapshotResolution`, `cachedSnapshotResolution` (1847–2003); `CostUsageScanner+ForkCoverage.swift`, `isUnresolvedMissingParentFork` (43–46); `CostUsageScanner+CacheHelpers.swift`, `codexForkBaselineDependencyKey` (1297–1308); `CostUsageCacheModels.swift`, `hasBufferedCodexForkRetryLines` (381–391) | Adapt production resolution to a per-session memo; assert the stream key matches parsed identity. Missing-parent diagnostics use `missing`. Snapshot withholding follows source, not prose: `isUnresolvedMissingParentFork` reads only the parent's used dependency key, so a retained resolved key still offers snapshots after the child's own parse is unresolved; the result's `has_unresolved_fork_baseline` stays a diagnostic and does not withhold. |
| `classify_subagent_session_ids` | `CodexSubagentRolloutShape.swift`, `classify(leafSessionID:observedSessionIDs:)` (41–58) | Port the metadata overload separately; canonical ancestor identity retains the first trimmed source spelling. |
| `classify_subagent_rollout` | `CodexSubagentRolloutShape.swift`, `classify(leafSessionID:observations:hasExplicitParent:)` (60–207) | Port; observations use upstream `uidx` positions. |
| `same_concrete_session_id`, `totals_contain_usage`, `normalized_session_id` | `CodexSubagentRolloutShape.swift`, `sameConcreteSessionID`, `totalsContainUsage`, `normalizedSessionID` (209–227) | Port; normalization returns trimmed source text, while NFC keys represent canonical Swift string equality only in identity comparisons. |
| `RolloutShape`, `OwnedSuffix`, `OwnedSuffixCandidate` | `CodexSubagentRolloutShape.swift`, nested result structs (14–38) | Dataclass representation. |
| `_CodexUsageParser`, `parse_codex_usage` | `CostUsageScanner.swift`, `parseCodexFileCancellable` (4177–5264) | A small class retains the closure's mutable locals; consume cached observations instead of file bytes. |
| `_CodexUsageParser.unix_milliseconds`, `_round_swift_ms` | `CostUsageScanner.swift`, nested `unixMilliseconds` (4262–4267) | Port rounded parsed-Date milliseconds. |
| `_CodexUsageParser.handle_bare_usage` | `CostUsageScanner.swift`, nested `handleBareUsage` (4279–4307) | Port. |
| `_CodexUsageParser.resolve_fork_baseline`, `configure_fork_accounting_if_ready` | `CostUsageScanner.swift`, nested `resolveForkBaseline`, `configureForkAccountingIfReady` (4326–4358) | Port. |
| `_CodexUsageParser.raise_inherited_baseline_if_continued_counter` | `CostUsageScanner.swift`, nested `raiseInheritedBaselineIfContinuedCounter` (4365–4394) | Port. |
| `_CodexUsageParser.handle_session_metadata` | `CostUsageScanner.swift`, nested `handleSessionMetadata` (4396–4440) | Port counter-relevant fields; display metadata is already owned by the FileRecord/assembly stages. |
| `_CodexUsageParser.handle_token_count`, inner `adjusted_last_delta`, `totals_derived_delta`, `commit_delta` | `CostUsageScanner.swift`, nested `handleTokenCount`, `adjustedLastDelta`, `totalsDerivedDelta`, `commitDelta` (4442–4654) | Port. |
| `_CodexUsageParser.process_fast_line`, `route_fast_line` | `CostUsageScanner.swift`, nested `processFastLine`, `routeFastLine` (4663–4685, 4726–4755) | Port over observations; bare usage remains outside the pending gate. |
| `_CodexUsageParser.explicit_owned_suffix`, `classify_and_replay_subagent` | `CostUsageScanner.swift`, `explicitOwnedSuffix` closure and EOF classification/replay (5016–5210) | Port; retain the unconsumed-tail gate and nonempty retry-buffer facts. |
| `_CodexUsageParser.append_row`, `UsageRow`, `CodexUsageResult` | `CostUsageScanner.swift`, emitted rows and parse return (4290–4303, 4635–4654, 5220–5264) | Adapt row positions and result representation. Reset model timeline at the owned suffix's physical line minus 0.5; discard unreplayed prefix models. |
| `account_logs` | `CostUsageScanner.swift`, parent file index and cold parsing; A4 items 6–7 | One shared resolver for every record, including header-only parents. Newest native mtime selects a duplicate parent, with ascending path ties. Meta-less files remain accounting inputs but never parent sources. |
| `date_from_timestamp` | `CostUsageScanner+Timestamp.swift`, `dateFromTimestamp`, `parseISO`, `parseNativeRFC3339`, `parseHistoricalISO` (22–89) | Port native branch selection before historical formatter compatibility; display parsing is unchanged. |
| `day_key_from_timestamp`, `day_key_from_parsed_iso`, `_codex_local_day_key` | `CostUsageScanner+Timestamp.swift`, `dayKeyFromTimestamp`, `dayKeyFromParsedISO` (104–187); `Sources/CodexBarCore/CostUsageModels.swift`, `CostUsageLocalDay`, `CostUsageLocalDayKeyMemo` (1573–1661) | Port local Gregorian-calendar buckets; return both key and fallback instant. Preserve Julian cutover and year-of-era rendering. |
| `_codex_historical_zone_offset` | Apple ICU 76.1, `tzfmt.cpp`, `parseOffsetISO8601`, `parseAsciiOffsetFields`, `parseAbuttingAsciiOffsetFields`, localized/default offset parsers | Library compatibility for the pinned historical formatter; bounded prefix consumption rather than strict RFC3339 validation. |
| All-history rows | `CostUsageScanner.swift`, `CostUsageDayRange` calls in `parseCodexFileCancellable` | Adaptation: omit day-range filtering. |
| Cold stream replay | `CostUsageScanner.swift`, `parseCodexFileCancellable` append-resume parameters and token-index checkpoints | Adaptation: no byte resume state or initial accounting state; changed logs reparse from the beginning. |
| On-demand lineage resolution | `CostUsageScanner.swift`, incremental refresh budget, parent queue/retries; A4 item 7 | Adaptation: no scan budget, parent queue or file-order dependence. `b10` includes the verified `b04` grandchild counters on `b10`'s dates. |

The historical zone compatibility source is
[Apple ICU `tzfmt.cpp`](https://raw.githubusercontent.com/apple-oss-distributions/ICU/9e80977766f830c93e3cdae3d5628997e1a61b63/icu/icu4c/source/i18n/tzfmt.cpp).
As with Task 7's numeric/calendar slice, standalone synthetic Foundation probes
corroborate this library behavior outside the repository. The suite depends
only on stored reference outputs and hand-derived assertions.

No additional token-accounting deviation was introduced. The source's pending
subagent gate and explicit-boundary suppression govern `s04` and `s07`; those
approved suppressed totals remain suppressed. Costs and priority are outside
Task 14's comparisons.

Resolver dependency state remains keyed by parent session. The empty-cutoff
guard returns unresolved before updating that state, so an earlier resolved
key remains resolved (`CostUsageScanner.swift` 1698–1703). The port preserves
that source behavior instead of replacing it with stricter per-parse state.

Parent identity follows Swift `String` canonical equality in the session-file
index, resolver memo, recursion set, dependency keys and parsed-identity check
(`CostUsageScanner.swift` 1172–1235, 1611–2003). Internal NFC keys provide this
library compatibility without adding trimming, case folding or compatibility
normalization. Returned metadata and diagnostic tuples retain their original
spellings. A4's newest-mtime and ascending-path selection applies once per
canonical identity; the separate rollout classifier's trimming stays separate.

The rollout classifier's `normalizedSessionID` (222–227) trims without
rewriting Unicode spelling. Both classifier overloads compare canonical keys,
and the ancestor set retains the first trimmed spelling of a sole distinct
identity. Inferred parent IDs therefore keep that spelling in the classifier
and usage result. Equivalent leaf metadata does not create an ancestor or
erase a suffix boundary. Explicit parent metadata remains source text.

## Task 15 — priority detection and usage composition

| Rule | Upstream file and function at `3bbf6bc48` | Treatment |
| --- | --- | --- |
| Request, submission and completion parsing | `CostUsageScanner+CodexPriority.swift`, `parseCodexPriorityTraceRow`, `parseCodexPrioritySubmissionRow`, `parseCodexCompletedTraceRow`, `value`, `quotedValue` (1020–1098) | Ported. Preserve Swift Character boundaries for markers, names, punctuation and quotes; marker precedence, prefix turn-id precedence, Foundation JSON/type checks, first duplicate-key projection and Foundation trimming. A request marker with invalid JSON never falls through to submission parsing. |
| Pending completion FIFO and completed-model selection | `CostUsageScanner+CodexPriority.swift`, `storePendingCodexCompletedModels`, `accumulateCodexPriorityTurns` (889–971), `filteredResolvedCodexPriorityTurns`, `latestCodexCompletedModel` (440–459) | Ported. Retain at most 4,096 pending turn identities in insertion order; repeated completions do not refresh insertion order. Known priority turns retain completions separately. Highest rowid wins regardless of timestamp or subsequent request model. |
| Cold query and source database | `CostUsageScanner+CodexPriority.swift`, `codexPriorityAccumulationPlan` (973–1005) | Adapted, A1/A4 item 4. Run only the non-indexed cold query with `rowid > 0` and `ts >= 0`; no memo, cursor, anchors or pruning. The database follows `--codex-home`. Open with `mode=ro`, `timeout=0.25`, normal SQLite coordination. Any SQLite error discards this scan's detections and retains sticky entries with a diagnostic. |
| SQLite text and timestamp projection | `CostUsageScanner+CodexPriority.swift`, `text`, `timestamp` (1100–1113) | Ported library compatibility. INTEGER becomes signed decimal; TEXT/BLOB are decoded as zero-terminated UTF-8 with replacement. REAL uses the same native SQLite library as the Python connection, preserving that backend's default numeric-to-text formatting. |
| Sticky memory | User decision A1 | Colophon addition. Never prune valid remembered entries. Database fields replace stored fields while retaining `first_seen_ms`. Write atomically at mode 0600 only when the merged entries change. Invalid stored entries provide no priority evidence and add diagnostics. |
| Primary response units | User decision A4 item 1; `CostUsageScanner.swift`, `tokenTotals` (4977–4987) supplies component mapping | Colophon addition. Count matching-thread records across every copy, first response id in source processing order wins; missing response ids are never deduplicated. Compaction records count. Keep cache-write for display and bill zero through the existing cost API. |
| Model in force | `CostUsageScanner.swift`, `processFastLine` (4663–4685), EOF suffix replay (5016–5210) | Use Task 14's own-file timeline strictly before each primary record. An unreplayed pending tail alone borrows its ordered C/XC evidence without inventing an owned suffix. Cleared/absent models remain `unknown`. |
| Cross-file fallback union | `CostUsageScanner+CacheHelpers.swift`, `uniqueCodexRows`, `codexUsageRowKey`, `codexCrossFileRowKey` (497–555); `CostUsageScanner.swift`, `sortedCodexSessionFilesNewestFirst` (6717–6731) | Ported. Preserve joined U+001F keys, event index, normalized model, component counts and pricing timestamp. Compare canonical Swift string identities while retaining public spelling. Add each file's keys only after its rows, preserving duplicates within a file. |
| Source selection and attribution | A4 item 1, D8; spec §5.5 | Colophon addition. Account the complete corpus including skipped parents before selecting primary/fallback units per turn. Reassign fallback row file indexes to each session's records. Display only matching owned turn ids whose unit line is outside its own file's inherited ranges; other units remain in session totals. |
| Fork and duplicate diagnostics | A4 item 6; spec §5.1, §5.5 | Every unresolved file flags its session. Detect duplicate pre-pass identities across all records; report differing true-first display identities alongside them. The existing shared resolver selects the newest-mtime parent copy. |

SQLite's REAL representation is a backend contract. The initial fifteen-digit
assumption was corrected against primary library source:
[SQLite 3.51.3 `vdbeMemRenderNum`](https://raw.githubusercontent.com/sqlite/sqlite/version-3.51.3/src/vdbemem.c)
uses `%!.15g`, whereas
[SQLite 3.52.0 `vdbeMemRenderNum`](https://raw.githubusercontent.com/sqlite/sqlite/version-3.52.0/src/vdbemem.c)
uses the connection's floating-point precision, defaulting to 17.
The same default is explicit in
[SQLite 3.53.4 connection initialization](https://raw.githubusercontent.com/sqlite/sqlite/version-3.53.4/src/main.c).
Synthetic standalone Swift `import SQLite3` probes on this execution host used
SQLite 3.54.0 and produced the same seventeen-digit values as Python's 3.53.4
connection. Tests independently compare native formatting with synthetic
SQLite CAST, including subnormal and maximum Double values, and verify native
allocation/free ownership. No source session database or CodexBar binary was
used. This corrects representation, without a token or cost deviation.

Trace parsing follows Swift Characters rather than Python scalar substring
matches. Task 13's ASCII literal boundary matcher also applies to every trace
marker, name and quote: preceding Prepend or following Extend/SpacingMark/ZWJ
prevents a whole literal match. Value punctuation stops only as a whole
Character. Swift's
[Character whitespace predicate](https://raw.githubusercontent.com/swiftlang/swift/main/stdlib/public/core/CharacterProperties.swift)
uses the Character's first scalar. Ordinary whitespace with trailing Extend
therefore stops a value, whereas preceding Prepend makes it part of the value.
[Unicode grapheme rules GB3–5 and GB9–9b](https://www.unicode.org/reports/tr29/#Grapheme_Cluster_Boundary_Rules)
make control whitespace, including CRLF, break from preceding Prepend.
Standalone synthetic source-helper probes corroborate these narrow predicates;
tests preserve clustered punctuation and quote spelling without inventing
shorter turn identities. No general Unicode rewrite or accounting deviation
is introduced.

Edge-case decisions:

- Malformed or wrong-schema sticky memory, invalid entry types and boolean `first_seen_ms` never establish priority; retain valid neighboring entries and report rejected entries.
- A missing trace database is silent and never created; a locked or unreadable database keeps sticky evidence only.
- Empty submission ids and completed models are rejected exactly as upstream; a non-string request model is retained as unknown rather than inferred.
- SQLite's own numeric text conversion, C-string NUL termination and UTF-8 replacement govern trace fields; Python's generic `str` is not the contract.
- Canonically equivalent priority and cross-file identities match without rewriting the public selected spelling.
- Clustered trace markers and quotes are absent; clustered value punctuation remains in the identity. Ordinary whitespace is governed by the Character's first scalar, with the source's control/CRLF boundaries preserved.
- Missing, cleared or unreplayed model evidence never supplies an invented model; only the explicitly specified pending-tail context rule supplies a model from C/XC observations.
- Duplicate-id diagnostics use pre-pass identities and also list differing display ids, with each display id's actual file paths.
