# Port control: implementation plan

Status: implemented on branch `anker-port-control` (release 0.4.0, build 6),
pending the owner gates (real-charger acceptance before merge, installed
acceptance after merge). Builds on the merged device identity and fault
display (`023737f`).

Paths below are relative to `anker_charge_monitor/` unless marked repository
root. Defaults below are selected; implementation approval remains separate.

## Goal

Control port power from the expanded row, including recovery of a stuck or
faulted device, and show charger-reported switch state independently of which
app or setting changed it. Protocol behavior follows "Source of the protocol".

## Decisions

Confirmed by Kevin on 2026-10-22:
- **USB-A controls** follow the upstream target mapping in "Source of the
  protocol" and the pair-specific text in "Wording".
- **Confirmation and interruptions:** use the contracts under "Design decisions".
- **Version.** Release 0.4.0 with `CFBundleVersion` 6.
- **Timing:** use `PortControlPolicy` below. The restart pause is confirmed;
  the remaining values are selected defaults, with no pending timing approval.

The comments explain the defaults. Adjustments after owner acceptance belong
in this declaration rather than in separate prose values.

```swift
public enum PortControlPolicy {
    /// Time a restart holds the port off, counted from the reply confirming off.
    public static let restartPause: TimeInterval = 5
    /// Gap between confirmation requests; favors feedback over normal cadence.
    /// This is a request interval, not a bound on device or network latency.
    public static let confirmationInterval: TimeInterval = 1
    /// How long a switch change may go unconfirmed before it is reported.
    /// Reuses the app's existing "reply is late" threshold.
    public static let confirmationDeadline: TimeInterval = PollPolicy.replyDeadline
    /// Expiry for the confirming click; bounds how long an armed action remains.
    public static let confirmationWindow: TimeInterval = 5
    /// Budget for the ending attempt, including cancellation and draining.
    /// Bounds added lifecycle delay; does not guarantee power restoration.
    public static let exitAttemptTimeout: TimeInterval = 3
}
```

## Source of the protocol

The wire details this plan depends on come from anker-solix-api at
`9e72894181aef868e7b3ed0ba05bd322d54bb5d7`. The encoder and decoder behave as
the cited upstream code does.

- **Command:**
  - `mqttmap.py`, the `A2345` entry `"0207"`;
  - `mqttcmdmap.py` `CMD_USB_PORT_SWITCH`, `CHARGER_PORT_IDS` and `CMD_COMMON`;
  - `mqtt.py` `generate_mqtt_command`, including its docstring vector.

- **Envelope:** behave as `mqtt.py` `publish` does; preserve the local
  `MQTTEnvelope.statusRequest` contract.
- **State:** behave as `mqttmap.py` `_A2345_0a00`'s per-target switch entries
  do, using `PortDecoder.acceptsType` and protocol reference "Detail fields".
- **Owner evidence:**
  [anker-solix-api discussion #252](https://github.com/thomluther/anker-solix-api/discussions/252).
  Consult its owner reports and maintainer replies for capture provenance and
  Anker-app visibility limits; do not copy captures into the repository.
- **Publish semantics:** consult `mqtt_device.py` `_send_mqtt_command`.

## Design decisions

- **Switch state and actions.**
  `ChargerDetails` gains the decoded switch per target. An undecoded switch
  follows the unknown-versus-none rule in the
  [identity plan, Snapshot contract](device_identity_and_faults_implementation_plan.md#snapshot-contract);
  preserve the current `ChargerDetails.fault(_:)` optional-value contract.
  Resolve A1 and A2 through the upstream target mapping. A reported-on target
  offers restart and turn-off; reported-off offers turn-on; unknown offers each
  action in "Wording". Disable controls while disconnected or stale and apply
  the operation exclusion below. Derive display state from decoded replies,
  rather than charging measurements or optimistic command state.
- **Timing is a pure state machine in Core.** `PortOperation` takes these
  events:
  - `requested`, `published`, `publishFailed`;
  - `snapshot`, `tick`;
  - `disconnected`, `reconnected`;
  - `ending`, with reasons defined in "Interrupted operations".

  It returns these actions: `publish(target, on)`, `requestStatus` and
  `finish(outcome)`. Drive ticks through `MonitorController.scheduleTick`;
  the state machine schedules nothing itself.
  Restart phases are turning off, paused and turning on. The off phase must
  satisfy "Confirmation freshness" before the pause begins; the pause uses
  `PortControlPolicy.restartPause`, then the on phase begins. The ending attempt
  is the exception to this sequence. Confirming either switch change uses the
  policy's interval and deadline; an unconfirmed phase finishes with an outcome.
- **One operation at a time.** While one runs, the other ports' actions are
  unavailable and say why. Reject overlapping requests for the active target
  too. Finished results follow "Outcome lifetime".
- **The controller owns operations.** `MonitorController` owns the running
  operation, so closing the panel mid-restart changes nothing.
  Add the armed confirmation to `PortDetailState`.
- **Confirmation.**
  - Turn off and Restart arm on the first click and act on a second click of
    the same button within the policy window. Turn on acts immediately. Use
    the armed strings from "Wording".
  - Arming disarms on: expiry, a click on any other action, a change of the
    expanded row, panel close (`StatusItemController.hidePanel`), loss of control
    availability, an account/charger context change, and Escape. Bind the armed
    action to its account, charger and connection generations; recheck them
    before the confirming click can dispatch.
  - Escape reaches disarming through the single cancel owner
    `StatusItemController.cancel` and through `PanelView`'s standalone fallback
    (`cancelNaming`). Successful disarming consumes that Escape and returns
    immediately, preserving naming state, focus and panel visibility. With no
    armed action, behave as the existing naming/dismissal paths do.
    `cancelNaming` delegates to `cancelAction` first when present; only its
    no-action branch performs fallback disarming and returns on success before
    calling `detail.cancelEditing(context:)`. This branch belongs here because
    standalone hosted views have no `StatusItemController` cancel owner.
- **Confirmation freshness.** Use the `0a00` switch report. Each phase captures
  its command generation and a backend-issued publish receipt, then requests
  status immediately, independently of normal polling. The receipt contains the
  connection identity and latest receive sequence at send completion; take this
  fence in the backend, not from the controller's last delivered snapshot.
  Accept a matching snapshot only after that phase's status request
  starts, with `receivedAt` no earlier than that request and a receive sequence
  newer than the boundary. Carry sequence/context metadata from backend receipt
  to controller delivery so queued earlier snapshots cannot advance a phase.
  Ignore prior-phase and obsolete-connection evidence. Apply the same boundary
  when clearing an outcome. The protocol provides no request correlation here:
  confirmation means a subsequently received state report, not a command ack.
- **Interrupted operations.**
  - **Sleep and network loss:** follow the disconnect behavior in
    `MonitorController.receive(_: SystemEvent)` and suspend publishing.
    - On reconnection in the same process, a restart continues from its phase.
    - "Turning off" requests status again with a fresh deadline and receipt
      fence for the replacement connection, without resending the switch command.
    - "Paused" keeps its original end time.
    - "Turning on" resends "on".
    - A plain turn-off or turn-on resumes confirmation only, using that same
      replacement-connection fence. A resumed on phase takes its new publish receipt.
  - **Ending** includes quit, sign-out, charger change, credential selection
    edits and explicit authentication replacement (Retry, Reload Credentials,
    Sign In Again). During a restart, attempt "on" against the captured old
    context before invalidating it, if it remains connected and authorized.
    Do not reconnect or retrieve credentials for this attempt. A plain turn-off
    is not reversed. End the operation even when the replacement selects the
    same account; same-process network recovery above is the resume path.
  - **Bounded ending:** block new control dispatch synchronously; serialize the
    ending write after any in-flight switch write, within `exitAttemptTimeout`.
    On expiry, revoke the old command context and close its captured link,
    cancel queued writes, and drain pending sends before permitting a replacement
    connection. Extend `MQTTConnection.swift` `NWMQTTLink.send/close` so close
    resumes pending send continuations exactly once and late callbacks are inert;
    cancelling a task alone is insufficient. Include this cleanup in the budget,
    using an injected deadline rather than the ordinary graceful-disconnect path.
    Already transmitted bytes cannot be recalled. Use "Outcome lifetime" for
    the result; publish completion alone must not claim restored power.
  - **Context ordering:** `endPortOperation()` captures the old backend target
    before awaiting; preserve the controller's synchronous supersession guards.
    Credential edits must invalidate acceptance immediately, then perform owned
    cleanup using that captured context. Repeated or overlapping endings share
    the same cleanup; a late completion cannot send to a replacement charger.
  - **A terminal authentication status** (session ended, sign-in failed,
    verification required) prevents publishing. The operation finishes with an
    outcome from "Wording" without attempting an ending publish.
- **Outcome lifetime.** `PortOperationOutcome` carries its originating account
  context, charger label, target, wanted state and confirmation boundary. It
  blocks no action. Successful ordinary confirmation clears phase text. Use the
  outcome-table condition to select failure text. Ending a restart
  without a fresh on confirmation leaves an uncertain result even if the publish
  completed. Keep it in memory across sign-out, charger change and authentication
  replacement, displayed above the panel's empty/readings branches with its
  original charger label. Do not attach it to the newly selected charger's rows.
  Clear it on Dismiss, a new operation, or matching fresh evidence from its own
  account/charger context. A reconnect in that context acquires a replacement
  fence through "Confirmation freshness" before accepting clearing evidence.
  Operations and outcomes stay in memory; relaunch uses "Switch state
  and actions" against new readings. Plain switch actions retain their failure
  result through context changes using this same presentation.

## Wording

Define new UI strings in this table and compare presentation tests against it.
Lifecycle and clearing behavior belongs in "Outcome lifetime"; it needs prose
because a string table cannot specify state transitions.

| Where | Text |
| --- | --- |
| Row secondary text, switch off | `Off` |
| Detail line label | `Port switch` (values `On`, `Off`, or the existing not-reported wording) |
| Buttons | `Restart`, `Turn off`, `Turn on`; USB-A forms `Restart USB-A ports`, `Turn off USB-A ports`, `Turn on USB-A ports` |
| Armed buttons | `Confirm restart`, `Confirm turn off` |
| Armed caption | `{port or "A1 and A2"} is supplying {power} to {device label or "a connected device"}.` |
| Phase text | `Turning off…`, `On again in {n} s`, `Turning on…` |
| Unavailable reason | `Another port is changing.`, `Reconnect to control ports.`, `Readings are stale.` |
| Off phase/action fails to confirm | `Couldn't confirm {target} turned off.` |
| On phase/action fails with a fresh off report | `{target} is still off. Turn it on to restore power.` |
| On phase/action fails without a fresh off report | `Couldn't confirm {target} turned on.` |
| Restart ends under the interruption rules without confirmed restoration | `{target} may still be off. Check the charger and turn the port on if needed.` |
| Outcome context, including after sign-out or charger change | `{original charger label}: {outcome}`; use the same outcome strings above |
| Outcome dismissal | `Dismiss` |

## Tasks

### Task: Decode and show port switch state

**Changes**
- `Sources/PrimeMonitorCore/ChargerDetails.swift`:
  - a public `PortSwitch` type for the USB-C ports and the USB-A pair. Its wire
    index follows upstream `CHARGER_PORT_IDS`, and it maps from `PortID`;
  - `public let switches: [PortSwitch: Bool]`, with a public initializer
    parameter following lesson "Check dispatch and responder paths when reviewing
    plans"; use a default empty dictionary for compatibility with current callers;
  - `public func switchedOn(_ port: PortID) -> Bool?`;
  - the switch field IDs added to `ChargerDetails.fieldIDs`, so `rawFields`
    keeps them.
- `Sources/AnkerCloud/PortDecoder.swift` `details(from:)`: extend its `value(_:)`
  helper for the switch entries under "Source of the protocol", applying
  "Switch state and actions".
- `Sources/PrimeMonitor/DiagnosticReadout.swift`: a line per target, using the
  readout's existing `unavailable` wording for unknown values.
- `Sources/PrimeMonitor/PortRowView.swift` `PortRowPresentation`: the off text
  from "Wording" joins `secondaryText`, after any fault text and before the
  device label. It is also included in `PortRowView.accessibilityText`.
- `Sources/PrimeMonitor/PanelView.swift`: the port-switch detail line from
  "Wording", next to the fault lines.
- `tools/generate_synthetic_frames.mjs` and
  `Tests/AnkerCloudTests/Fixtures/README.md`: add switch fields to the details
  corpus, covering on, off, missing, an unaccepted type, and the shared USB-A
  switch.
- `Tests/Snapshots/Snapshots.swift`: `SnapshotBackend` can deliver switch
  states, and `panelStates` gains a state with a USB-C port and the USB-A pair
  off.
- Protocol reference: a subsection after the detail-fields subsection, citing
  the upstream switch keys and commit without restating the layout.

**Tests**
- `ZeroAZeroDecodeTests`:
  - literal switch expectations for the extended corpus;
  - original-corpus and malformed-field cases against "Switch state and actions"
    and the existing decoder contract.
- `ChargerDetailsTests`: target mapping against "Source of the protocol",
  through ordinary `import PrimeMonitorCore` to check public API construction.
- `PanelViewTests`: the off text and the port-switch line in each state, plus
  the accessibility label.
- `LiveCheckTests`: the readout lines.

**Acceptance**
- Apply "Validation for implementation tasks".
- **Owner gate.** Kevin runs it; the output stays private.
  1. Switch one USB-C port off in the Anker app.
  2. Run `make -C anker_charge_monitor release` and quit the GUI app.
  3. From the project directory, run
     `"build/release/Anker Charge Monitor.app/Contents/MacOS/PrimeMonitor" --live-check`.
  4. Confirm that port reads off and the others read on.
  5. Switch it on in the Anker app and repeat.

  1Password may ask for a new approval for the build path (README "Signing
  and installation"). If the state doesn't match, fix the decoder with a
  synthetic regression before continuing.

### Task: Turn ports off, on and restart from the controller

Implement encoding, publication, the state machine and controller integration;
the tests below exercise the named contracts against synthetic backends.

**Changes**
- `Sources/AnkerCloud/StatusRequest.swift`: a general command-frame builder
  that behaves as `generate_mqtt_command` does for the command mapping under
  "Source of the protocol".
  - `StatusRequest.frame(timestamp:)` calls it; retain compatibility through
    `StatusRequestEncodeTests`.
  - Add `PortSwitchCommand.frame(target:on:timestamp:)` for `0207`.
- `Sources/AnkerCloud/MQTTEnvelope.swift`: a command envelope that takes a
  frame. Retain compatibility through the current `EnvelopeTests` literals.
- `Sources/PrimeMonitorCore/ChargerBackend.swift`: add
  `setPortSwitch(_ target: PortSwitch, on: Bool) async throws -> PortCommandReceipt`
  to `ChargerBackend`, documented as publish-only. Add public receipt/evidence
  types with explicit public initializers for "Confirmation freshness". Extend
  `BackendEvent` snapshot delivery to carry that evidence;
  update event producers, consumers and synthetic fixtures together. Add a backend
  fence accessor for reconnection without a repeated switch publish.
- `Sources/AnkerCloud/AnkerCloudBackend.swift`: implement it as
  `requestSnapshot` publishes; retain `PortDecoder.snapshot`'s message-type guard.
  Extend snapshot event metadata for "Confirmation freshness" without changing
  port measurements or their reported receive time.
- `Sources/AnkerCloud/MQTTConnection.swift`: implement the pending-write disposal
  required by "Bounded ending" and keep the existing link cleanup ownership.
- `Sources/PrimeMonitorCore/PortOperation.swift` (new):
  - `PortControlPolicy`, exactly as under "Decisions";
  - `PortOperation` and `PortOperationOutcome`, implementing the events,
    actions and interruption rules under "Design decisions".
- `Sources/PrimeMonitor/MonitorController.swift`:
  - observable `portOperation` and `portOutcome`;
  - `turnPort(_:on:)` and `restartPort(_:)`;
  - feed backend, system, tick and context events through "Design decisions";
  - execute its actions through `backend.setPortSwitch` and `sendRequest`;
  - capture account, selection and connection generations before each await,
    as the existing connection and request paths do;
  - add `endPortOperation()` and wire the context-changing entry points named
    in "Interrupted operations", including `setCredentialSelection`,
    `connect(using:reload:)`, `authenticate`, `signOut`, and `select`;
    coordinate synchronous invalidation with asynchronous cleanup through the
    existing retained-task pattern rather than making credential edits await.
- `Sources/PrimeMonitor/AppDelegate.swift` `applicationShouldTerminate`: await
  `controller.endPortOperation()` before `controller.stop()`.
- Find affected backends with `rg ': ChargerBackend' Sources Tests`; update
  conformers and record synthetic calls in the test/snapshot implementations.
- Docs:
  - protocol reference: a command section citing the upstream symbols and the
    owner evidence;
  - `docs/architecture.md`: `PortOperation`, the controller's ownership and
    the interruption rules, by reference to this plan's section.

**Tests**
- `CommandFrameTests` (new):
  - the builder reproduces the `generate_mqtt_command` docstring frame, with
    the checksum computed;
  - a synthetic `0207` vector per target and value, using the existing
    invented timestamp convention (`Fixtures/README.md`) and written
    independently of the builder;
  - every frame parses through `HexFrame.parse` with type `0x0207`.
- **Private encoder check.** Kevin or the implementer compares the
  encoder against the Anker app frames in discussion #252. Encode each
  target/value with the frame's own timestamp and match byte for byte. Record
  the result in the PR, following `Fixtures/README.md` provenance rules.
- `EnvelopeTests`:
  - the command envelope carries the new frame;
  - its echo yields no snapshot.
- `AnkerCloudBackendTests`:
  - `setPortSwitch` publishes to the `req` topic;
  - it throws when not connected;
  - a context replaced during the await is rejected.
- `PortOperationTests` (new): event/action tables against the state-machine,
  freshness, interruption and outcome contracts in "Design decisions", with
  success, publish failure and deadline cases.
- `MonitorControllerTests`, with `ManualScheduler` and `AppBackend`:
  - the publish/status sequence for each kind;
  - operation exclusion and outcomes against their named contracts;
  - interruption cases, including credential edits, reload, Retry and reauth;
  - stale generations, queued pre-command snapshots, prior-phase replies, and
    replies arriving before publish completion against "Confirmation freshness";
  - overlapping endings and an older completion after replacement selection.
- `AnkerCloudBackendTests` and transport regressions: hold a write beyond the
  ending deadline, then exercise close and a late send callback against "Bounded
  ending". Exercise actual disposal in the transport fixture rather than making
  its suspended send return merely because the task was cancelled.
- `AppDelegateTests`: exercise termination during each restart phase and with a
  blocked publish against "Bounded ending", including ordering before `stop()`.

**Acceptance**
- Apply "Validation for implementation tasks" and the private encoder check.

### Task: Port control in the panel, and release

**Changes**
- `Sources/PrimeMonitor/PortDetailState.swift`: implement "Confirmation" with
  target, action, expiry and captured context.
- `Sources/PrimeMonitor/StatusItemController.swift`:
  - wire `cancel()` and `hidePanel()` through "Confirmation".
- `Sources/PrimeMonitor/PanelView.swift`:
  - **`PortDetailView` actions:** implement "Switch state and actions", with
    strings from "Wording".
  - **Phase and outcome presentation:** apply "Outcome lifetime" as well as
    row/detail phase text; keep context warnings visible in the empty panel.
  - **Announcements** of phase changes and outcomes, through SwiftUI's
    accessibility announcement API.
  - **`cancelNaming`:** implement the delegation and fallback contract in
    "Confirmation".
- `Tests/Snapshots/Snapshots.swift`: `panelStates` gains:
  - an armed confirmation, set on `PortDetailState`;
  - a restart held in its paused phase: drive `restartPort` against a
    `SnapshotBackend` that confirms off and then stops replying, under the
    fixture's non-firing scheduler;
  - an outcome with a port left off.

  Preserve the PNG guard in `Snapshots.main`.
- **Version bump** to the values under "Decisions". The places to change are
  the files touched by the previous bump: run `git show --stat 023737f` and
  check its version-bearing files. These include the release checks and the
  root `tools/tests` deployment fixture and test.
- README:
  - port control, confirmation and interruption behaviour, by reference to
    the in-app wording;
  - the Anker-app visibility limits in the owner evidence under "Source of the
    protocol", by reference to the discussion rather than a permanent guarantee.
- Protocol reference: replace its read-only framing with the read-plus-command
  scope.
- `docs/lessons_learned.md`: an entry for any bug fixed along the way.

**Tests**
- `PanelViewTests`:
  - actions per switch state;
  - arming and disarming against "Confirmation", including context changes;
  - the caption for a USB-C port and for the USB-A pair;
  - each unavailable reason;
  - phase and outcome text against "Wording".
- `StatusPanelTests`: dispatch hosted key events and direct cancel calls against
  "Confirmation", including armed plus naming, armed without naming, subsequent
  Escape, and standalone fallback/delegated paths; compare draft, focus and
  visibility before and after each dispatch to that contract.
- The version-bearing tests from the bump list carry the new version.

**Acceptance**
- Apply "Validation for implementation tasks".
- `make -C anker_charge_monitor release` builds and verifies the signed bundle.
- The bump changes root `tools/tests`, so run every command in the root
  `AGENTS.md` Validation Matrix entry "Static deployment/fleet audit tooling",
  plus `node tools/deploy_anker_charge_monitor.mjs --dry-run`.
- **Owner gate before merge.** Kevin runs the built release app against the
  real charger, using a USB-C port with a device you can watch (a phone, a USB
  light), never the port powering this Mac. Confirm on the device and in the
  panel, not in the Anker app (see "Source of the protocol"):
  - **Turn off:** the device loses power, and the panel shows the port off.
  - **Turn on:** power returns.
  - **Restart:** compare observed behavior with `PortControlPolicy` and the
    state-machine contract; judge whether the selected default is suitable.
  - **USB-A pair:** turn it off and on.
  - **Quit during a restart:** observe the ending attempt and recovery under
    "Interrupted operations"; distinguish a sent command from restored power.

  Record the outcome in the PR, without readings or identifiers. If the charger
  ignores a command, stop and diagnose with live-check before merging.
- **Installed acceptance:** after merge to `main` and separately authorized
  installation through README "Signing and installation", turn a port off and
  on with the installed app. Verify source version, installed plist and Settings
  footer agree with "Decisions".

## Validation for implementation tasks

Apply repository-root `AGENTS.md` "Validation Matrix", entry
`anker_charge_monitor`, after each implementation task. Require its complete
suite without skips and inspect generated maintained views under each maintained
appearance. Run the scanner as documented in README "Privacy and development",
with its prerequisites and working directory, and require `clean`. These are
future implementation gates; this plan edit does not claim they have run.

## Risks

- **Turning off the wrong port cuts power to whatever is on it.** That could be
  this Mac. See "Confirmation", "Wording" and "Out of scope".
- **A charger slow to update its status** could miss the confirmation deadline
  while actually succeeding. Recovery presentation follows "Outcome lifetime".
- **Interrupted restarts:** see "Interrupted operations" and "Outcome lifetime".

## Out of scope

- Decoding `0302` and `0a07` for immediate feedback.
- Port timers, schedules, priority, usage modes, power limits and display
  settings.
- Menu bar indication of off ports or operations.
- Any live-check option that sends commands.
- Identifying the port that powers this Mac. The decoded USB-PD identities
  could support a warning later.
