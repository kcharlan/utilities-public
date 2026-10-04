# Token routing rules

Normative source: `steipete/CodexBar` at `3bbf6bc48`. File paths in this
ledger are relative to `Sources/CodexBarCore/Vendored/CostUsage/`. The launcher
ports routing into scalar observations; subsequent accounting replays them.
The suite uses hand-derived synthetic observations and has no dependency on
an upstream checkout, binary, cache or fixtures.

| Rule | Upstream file | Function | Commit | Decision | Notes |
| --- | --- | --- | --- | --- | --- |
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
