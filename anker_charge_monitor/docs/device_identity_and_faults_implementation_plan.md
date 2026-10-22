# Device identity and fault display: implementation plan

Status: approved for implementation 2026-10-21 (separate `devices.json`, `DeviceCatalog.label(for:)` row text, minor release).

## Amendments (owner verification evidence, 2026-10-21)

The implementation differs from the text below in these points:

- Identity support (`b7`) never hides decoded identity. The owner's charger
  reported 2 while one port carried a resolved identity, so decoded `bd`/`be`
  data always wins and missing identity reads "Not reported by this charger".
  The "This charger can't identify connected devices." state was not shipped.
- `.identifying` (`{0, 0}`) presents as "Unidentified device" (catalog label)
  and "This device hasn't reported its identity." (expanded detail): some
  devices never answer USB-PD Discover Identity. The case name is unchanged.
- Brand keys with leading zeros (for example `01`) are rejected.
- Release: minor version 0.3.0, build 5.

See the 2026-10-21 entries in [lessons](lessons_learned.md).

## Goal

Display connected-device identity, port faults and charger over-temperature in
the status panel, using the existing status-request path. Device names and
editable brand data belong outside the repository. See "Out of scope" for the
limits of this change.

Paths below are relative to `anker_charge_monitor/` unless marked repository
root. The contracts below specify new app behavior; wire definitions and
existing implementation behavior remain in the cited sources.

## Decisions Kevin needs to confirm

- **Catalog location.** Confirm the separate `devices.json` proposal. Review
  `StateStore.load()` and `StateStore.save()` in
  `Sources/PrimeMonitor/StateStore.swift` and the persistence call in
  `MonitorController` before accepting this separation.
- **Row text.** Confirm `DeviceCatalog.label(for:)` from "Catalog contract"
  for the row, with IDs in expanded detail.
- **Version increment.** Propose a minor release; confirm the increment before
  implementation, under the repository's "Release Versions" rule.

## Protocol authority

Use anker-solix-api commit `9e72894181aef868e7b3ed0ba05bd322d54bb5d7`:

- [`mqttmap.py`, `_A2345_0a00`](https://github.com/thomluther/anker-solix-api/blob/9e72894181aef868e7b3ed0ba05bd322d54bb5d7/src/anker_solix_api/mqttmap.py#L3550):
  keys `a3`, `b7`, `bd` and `be` are the authority for masks, value offsets,
  sentinels, identity-support meaning and brand classes. These are the
  **detail fields** throughout this plan. Decode their values as that map does.
- [`mqtttypes.py`, `DeviceHexDataField.extract_value`](https://github.com/thomluther/anker-solix-api/blob/9e72894181aef868e7b3ed0ba05bd322d54bb5d7/src/anker_solix_api/mqtttypes.py#L394):
  follow its field-type dispatch into `BYTES` extraction, including the
  `sile` branch. Do not infer accepted types from the base-type enum alone.
  `detailsFieldTypesMatchUpstream` will hold the accepted/rejected type matrix.
- For value indexing, follow upstream `DeviceHexDataField.f_value` and the
  retained-payload contract on `Sources/AnkerCloud/HexFrame.swift:HexFrame`.

Owner wire-layout acceptance remains the "Owner verification gate" below.
Synthetic tests establish decoding against these sources, not behavior on
Kevin's charger.

## Snapshot contract

Add `Sources/PrimeMonitorCore/ChargerDetails.swift` with this public interface:

```swift
public enum PortIdentity: Equatable, Sendable {
    case nothingAttached
    case identifying
    case identified(vendorID: UInt16, productID: UInt16,
                    brandClass: UInt16?, modelCode: UInt16?)
}

public struct ChargerDetails: Equatable, Sendable {
    public let faultBits: UInt8?
    public let identitySupport: UInt8?
    public let identities: [PortID: PortIdentity]
    public let rawFields: [UInt8: [UInt8]]
    public init(faultBits: UInt8?, identitySupport: UInt8?,
                identities: [PortID: PortIdentity], rawFields: [UInt8: [UInt8]])
    public var overTemperature: Bool? { get }
    public func fault(_ port: PortID) -> Bool?
}
```

`overTemperature` and `fault(_:)` are read-only computations from `faultBits`
using the protocol authority's masks. The raw low fault byte is stored once;
there is no independent temperature flag. USB-A fault presentation uses the
upstream shared-port meaning and the label "USB-A fault".

In `Sources/PrimeMonitorCore/Ports.swift`, add
`public let details: ChargerDetails?` to `ChargerSnapshot`, with a corresponding
initializer argument defaulting to `nil`.

Decoder rules:

- Preserve the existing mandatory-reading validation in `PortDecoder.snapshot`.
- A missing, short or unsupported detail field leaves the affected decoded
  part unknown. Keep usable parts from other detail fields. A valid `bd` can
  provide IDs when `be` is unusable; its optional metadata then remains nil.
- Preserve present detail payloads verbatim in `rawFields`, including the type
  byte, even if decoding fails. `details` is nil when no detail field is present.
- Keep `HexFrame.parse`'s framing validation unchanged. Tests for forms that
  parser rejects must distinguish parser rejection from direct construction
  through `HexFrame(messageType:fields:)`.

**Unavailable-value wording:** expanded detail uses "Not reported by this
charger" for a value that was not decoded. An undecodable fault value makes no
row fault claim; "None" requires a decoded clear port bit. Show raw fault bits
in detail when available.

## Catalog contract

Add `Sources/PrimeMonitorCore/DeviceCatalog.swift`. Decode the JSON object with
custom validation; the proposed key formats must not rely on synthesized
dictionary `Codable` behavior.

```swift
public struct DeviceKey: Hashable, Sendable {
    public let vendorID: UInt16
    public let productID: UInt16
    public init(vendorID: UInt16, productID: UInt16)
}
public struct DeviceCatalog: Equatable, Sendable {
    public var brands: [UInt16: String]
    public var vendors: [UInt16: String]
    public var devices: [DeviceKey: String]
    public init()
    public static func decode(_ data: Data) throws(DeviceCatalogError) -> Self
    public func label(for identity: PortIdentity) -> String?
}
```

For `.identified`, resolve a label in this order: user device name, brand-class
name, vendor name, uppercase hexadecimal `VID:PID`. `.identifying` resolves to
"Identifying…"; `.nothingAttached` resolves to nil.

`DeviceCatalog.init()` initializes empty lookup dictionaries. The interface
blocks specify API declarations; implement their bodies in the named Core files.

**File format:** schema `1`, with required JSON objects `brands`, `vendors` and
`devices`. Require string names; trim them, reject empty names and names longer
than 64 characters. Reject a noninteger schema or the wrong JSON value type.
Brand keys are decimal UInt16 excluding the upstream absence sentinel; vendor
keys are four hexadecimal digits; device keys join vendor and product keys in
that format with a colon. Accept either hex letter case, normalize numeric
keys, and reject aliases that resolve to the same key. `DeviceCatalogTests`
holds the literal valid/rejected keys and error messages. A validation failure
rejects the load and names the failing entry.

`source` and unknown top-level keys are accepted. The store retains the parsed
JSON object to preserve them on writes; they need not be properties of the
label-lookup value type.

**Seed:** create tracked `Resources/device_catalog.json` from the protocol
authority's named brand-class entries. Do not turn VID-only comments into
brand names. Include schema and provenance, with empty `vendors` and `devices`.
Keep this mapping in the resource; UI source code consults the catalog.

## Store contract

Add `Sources/PrimeMonitor/DeviceCatalogStore.swift`, an
`@MainActor @Observable final class DeviceCatalogStore` exposing `catalog` and
`problem: String?`.

- `init()` creates an empty in-memory store: no file URL, bundled seed lookup,
  filesystem access or timer. Its naming operations update memory only.
- `init(fileURL:seedURL:scheduler:)` requires an explicit file URL and
  scheduler; the seed URL may be nil. The GUI composition alone supplies
  `devices.json` beside `StateStore().fileURL` and
  `Bundle.main.url(forResource: "device_catalog", withExtension: "json")`.
- **Seeding:** on `load()` or refresh, copy the seed's bytes when the file is
  absent and a seed exists. Leave existing content untouched. With neither
  file nor seed, use an empty catalog without a problem. A later naming save
  can create a schema-valid empty document before adding the name.
- **Loading:** success replaces the catalog and clears `problem`; failure
  retains the last good catalog, sets a recoverable file/entry diagnostic and
  leaves the file untouched. Refuse naming writes while current file contents
  are invalid. A corrected file must recover on refresh or naming retry.
- **Reloading:** `panelOpened()` refreshes immediately and starts a one-second
  loop through `PollScheduler` in `Sources/PrimeMonitor/SystemEvents.swift`.
  `panelClosed()` cancels it; repeated lifecycle calls must not duplicate loops.
  Compare `(device, inode, size, mtime-nanoseconds)` before decoding. Record the
  attempted signature for invalid content too, so unchanged invalid files are
  not decoded on each tick. Edits preserving the entire signature are outside
  this reload guarantee.
- **Naming:** `setName(_ name: String?, for key: DeviceKey) throws` reads and
  validates the current on-disk JSON object immediately before changing
  `devices[key]`; resolve absence through the seeding rule before that read,
  including deletion since the last load. Match existing JSON entries by decoded
  `DeviceKey`, so changing or removing a name works with either accepted hex
  spelling and cannot introduce an alias. A blank or nil name removes the entry.
  Apply the catalog contract's content-preservation rule,
  write sorted and pretty-printed JSON, and publish the new catalog/signature
  after success.
  This is a read/modify/write operation, not a lock shared with external editors;
  avoid simultaneous editor saves during an in-app naming write.
- **Writes:** behave as `StateStore.save` does for private atomic replacement.
  Follow "Preserve decoded paths when modernizing Foundation URLs" in
  `docs/lessons_learned.md` for path-based operations.

Keep file access behind an injectable internal dependency so tests can fail on
an unexpected operation without observing the owner's runtime directory.

## Panel interaction contract

Add `Sources/PrimeMonitor/PortDetailState.swift`, an
`@MainActor @Observable final class PortDetailState`. `StatusItemController`
owns it and passes it through `StatusContent` to `PanelView`; tests and snapshot
fixtures construct it directly. It owns expansion, draft, edited `DeviceKey`,
dirty/editing state and naming error, with methods called by the actual controls.

- Rows are borderless buttons; click, Space or Return toggles expansion. Keep
  one expanded row and retain expansion through snapshot replacement. Use
  `PanelMotion.perform` for the transition.
- The naming field uses "Name this device" and is enabled for an identified
  device. Return and focus loss save through `setName`. Closing or switching
  rows settles the pending edit through the same path. A failed save retains
  the draft and inline error for retry, including after reopening. On a row-switch save
  failure, keep the edited row expanded until retry succeeds or Escape cancels
  the edit; do not replace the pending draft with the destination row's state.
- Catalog reloads must follow the draft-preservation principle in "Keep literal
  vault item names through observed Settings edits" in the project lessons.
  Bind a draft to its original device key; a replacement device or charger must
  never receive the previous device's draft.
- Escape cancels the draft and ends editing while keeping the panel open.
  Mark cancellation before focus changes, so the focus-loss save cannot commit
  it. A later Escape outside editing retains normal panel dismissal.
- Route cancellation consistently through `StatusPanel.performKeyEquivalent`
  and `StatusPanel.cancelOperation` in `Sources/PrimeMonitor/StatusPanel.swift`,
  and `StatusHostingController.cancelOperation` in
  `Sources/PrimeMonitor/StatusItemController.swift`. These paths must invoke
  the edit-cancel action while naming rather than dismiss or recursively
  forward the same command. Wire the TextField's `.onExitCommand` to that same
  action and clear its focus before allowing a later panel-level cancellation.

## Tasks

### Task 1: Decode details and expose diagnostic evidence

**Changes**

- Implement the snapshot contract in `ChargerDetails.swift`, `Ports.swift` and
  `Sources/AnkerCloud/PortDecoder.swift`. Use unsigned identity reads without
  changing signed port-reading decoding.
- Extend `Sources/PrimeMonitor/DiagnosticReadout.swift` to show the detail
  properties, per-port identities and raw payload hex, including unavailable
  values. This is the evidence path for the owner gate.
- Extend `tools/generate_synthetic_frames.mjs` to produce
  `Tests/AnkerCloudTests/Fixtures/synthetic_0a00_details_frames.txt`. Preserve
  the existing corpus. Follow the fixture README's synthetic padding convention;
  add its provenance. The new corpus covers identity cases, unknown classes,
  support states, mask combinations and the field-type matrix. In particular,
  include a `sile`-encoded fault-field regression.
- Add pinned protocol references to decoder comments and
  `docs/anker_protocol_reference.md` after "A2345 reply map"; cite the authority
  rather than copying its field layout. Add this commit to README "Attribution"
  and the upstream provenance `Text` in `SettingsView`.

**Tests**

- Extend `ZeroAZeroDecodeTests` with `detailsCorpusDecodesToKnownValues` and
  `detailsFieldTypesMatchUpstream`: literal expectations independent of the
  generator, reading parity with detail-free frames, and nil details for the
  existing corpus. Cover the snapshot contract's malformed/partial cases,
  including missing support, short identity data, missing value bytes and an
  unsupported type. Assert the snapshot contract for these cases.
- Add Core tests against the protocol authority for mask mapping and identity
  sentinels, including independently missing optional metadata. Exercise the
  snapshot contract's computations for set, clear and unknown cases.
- Extend diagnostic readout tests with literal synthetic output expectations.
- In the decoder tests, construct `ChargerDetails` through ordinary
  `import PrimeMonitorCore`, so its public construction is compiler-checked.

**Acceptance**

- Apply "Validation for implementation tasks" below.
- **Owner verification gate:** complete this before "Panel presentation, editing
  and release". Kevin follows "Release acceptance" below, quits the GUI, then
  runs, from `anker_charge_monitor/`:

  ```sh
  "build/release/Anker Charge Monitor.app/Contents/MacOS/PrimeMonitor" --live-check
  ```

  Consult README "Signing and installation" for installed `make live-check`
  scope and app-path authorization limitations, and "Credentials and setup" for
  normal 1Password approval. This gate contacts the real vault/service and is
  owner-run; keep its output private outside the checkout. Check raw payloads
  against the protocol authority, an attached device's identity and an empty
  USB-C port's identity. If the shape differs, correct the decoder and add an
  invented regression before proceeding with the panel.

### Task 2: Catalog persistence, reload and safe composition

**Changes**

- Implement the catalog and store contracts.
- In `Makefile` `release`, copy the seed into `Contents/Resources` before
  signing. In `Tests/ReleaseChecks/check_bundle.sh`, compare the built seed to
  the tracked resource byte-for-byte. Leave `tools/install.sh` unchanged;
  preserve its `validate()`/`validate_release()` compatibility boundary.
- On the GUI branch of `PrimeMonitorApp.main`, construct the persistent store,
  call `load()`, and inject it through `AppDelegate.init` (including the default
  `statusFactory`), `StatusItemController.init`, `StatusContent` and `PanelView`.
  Any omitted dependency uses `DeviceCatalogStore()` from the store contract.
  Do not create the persistent store on the `LiveCheck` branch.
- In `StatusItemController`, pair catalog lifecycle calls with controller calls
  in `presentPanel`/`hidePanel`. Use explicit temporary stores in catalog-aware
  `PanelViewTests`, `StatusPanelTests`, and snapshot `Fixture.make`.
- Document the catalog/store contracts in README "Operation and state" and
  `docs/architecture.md`.

**Tests**

- Add `DeviceCatalogTests` for validation, label resolution and the tracked seed
  read via `#filePath`. Pin synthetic labels and rejected input messages there.
- Add `DeviceCatalogStoreTests` with a manual scheduler and private temporary
  paths containing spaces and non-ASCII text. Cover seeding/re-seeding, existing
  content, missing seed, first naming save without a seed, deletion between load
  and save, invalid edits and recovery, metadata-triggered reload,
  unchanged valid/invalid signatures,
  lifecycle cancellation, content preservation, name removal, private modes
  and held readers across atomic replacement. `namingUsesDecodedDeviceKeys`
  holds the existing-key spelling cases for naming updates/removals. Construct
  `DeviceKey` and the empty catalog through ordinary `import PrimeMonitorCore`.
- Exercise the store contract's default-construction rule through app/panel
  composition with filesystem access instrumentation during opening, closing,
  reloading and naming.
  Do not inspect or modify the owner's runtime file to establish this.

**Acceptance**

- Apply "Validation for implementation tasks" below.
- **Deployment validation:** run the repository-root Validation Matrix entry
  "Static deployment/fleet audit tooling", including its consumer prerequisites
  and suites. Run the deployment dry-run documented in README "Signing and
  installation", using its stated working directory.

### Task 3: Panel presentation, editing and release

**Changes**

- Implement the panel interaction contract.
- `Sources/PrimeMonitor/PortRowView.swift`: replace the intervening `Spacer`
  with the catalog label in smaller secondary text, single-line and tail
  truncated. Choose number-column widths through `numericColumnsFitWireExtremes`
  in `PanelViewTests`, using the actual font and `NSAttributedString.size()`.
- Faulted labels/device text use red with `exclamationmark.triangle` and
  "Fault reported"; apply the snapshot contract's USB-A wording. Preserve the
  existing inactive/stale presentation behavior.
- `Sources/PrimeMonitor/PanelView.swift`: for `.identified`, expanded detail
  shows the naming control, catalog brand or unknown class, hexadecimal USB IDs
  and "Device model code N". Missing optional brand/model values use the
  unavailable-value wording; a reported unknown class retains its numeric value.
  Use the snapshot contract's fault wording for each expanded port.
- For identity presentation, USB-A says "USB-A ports don't report connected
  devices." For USB-C, interpret support through the protocol authority;
  confirmed unsupported says "This charger can't identify connected devices."
  Without that result, show usable identity data even if support is unavailable.
  If identity is also unavailable, use the unavailable-value wording; never
  infer nothing-attached from missing data. Expanded `.nothingAttached` says
  "Nothing connected."; expanded `.identifying` uses its catalog label. Keep
  device-specific controls and metadata out of these states.
- Add an `InlineWarning` for `overTemperature == true` reading "Charger reports
  over-temperature." and one for `catalog.problem`. These warnings must not
  add reading dimming. Add known fault/device information before readings in
  row accessibility, the hint "Shows device details", and a normal accessibility
  container for expanded controls.
- `Tests/Snapshots/Snapshots.swift`: extend `SnapshotBackend.requestSnapshot`
  and `Fixture.make` with invented detail data and a temporary synthetic
  catalog. Add a fault/identity/temperature state and an expanded named row
  to the rendered-state list. Update the PNG guard and message from that
  rendered-state list; retain the existing geometry and pixel guards.
- Once the increment is confirmed, update maintained version/build declarations
  found by repository-wide `rg` for the current values. Use `git show --stat
  eb29268` as a prior-bump checklist, including the root deployment fixtures and
  tests; classify historical documentation matches rather than rewriting history.
- Update README's panel/naming guidance and record implementation bug lessons in
  `docs/lessons_learned.md`.

**Tests**

- `PanelViewTests`: assert presentation contracts through the shared model/actions
  used by the view, including `expandedIdentityStates` for the identity cases.
  Test naming commits, cancellation, save failure/retry, catalog reload and device
  replacement through the panel interaction contract; include a hosted field
  focus-loss case rather than testing model methods alone. Include a failed-save
  row switch followed by retry and cancellation paths.
- `StatusPanelTests`: dispatch a real synthetic Escape key event with a hosted
  field editor and exercise direct cancellation on the panel and hosting
  controller. Assert the panel interaction contract's Escape rule after each
  dispatch, including the subsequent focus transition.
- `ReleaseTests` and root deployment tests/fixtures: assert the confirmed release.

**Acceptance**

- Apply "Validation for implementation tasks", "Deployment validation" and
  "Release acceptance".
- Deployment and real installed-app observation require separate authorization.
  Once authorized and installed through the README workflow, Kevin checks real
  identity labels, naming across quit/reopen, live catalog edits and normal
  physical keyboard/mouse interaction. Verify source, deployed metadata and
  Settings version agree before reporting the released version.

## Validation for implementation tasks

Run the commands in repository-root [AGENTS.md, Validation
Matrix](../../AGENTS.md#validation-matrix), entry `anker_charge_monitor`, after
each implementation task. Require the complete suite without skips and
successful snapshot guards. Inspect the generated maintained views, including
Settings provenance and expanded panel layouts, under each maintained appearance.
Run the scanner exactly as documented in [README, Privacy and
development](../README.md#privacy-and-development), including its working
directory and prerequisites; require `clean`. These are future implementation
acceptance gates, not tests claimed to have run while editing this plan.

**Release acceptance:** use the release-build command in [README, Requirements
and build](../README.md#requirements-and-build), with signing requirements from
"Signing and installation". Require a successful build and strict signature
verification.

## Risks

- The owner verification gate can reveal a mismatch with the protocol authority.
- Consult the protocol authority's fault-name entries for their uncertainty
  markers. Do not induce hardware faults to validate labels.
- The catalog has no product-name mapping beyond user entries. New classes use
  the panel's unknown-class presentation until the catalog is edited.
- Store reload detection and editor-write concurrency have the limits stated
  in the store contract.

## Out of scope

- Port switching/restart and other cloud write commands.
- Fault/temperature changes to menu bar icon, tooltip or accessibility.
- Other status settings, firmware/OTA display and the realtime stream.
