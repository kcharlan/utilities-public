# Architecture

`PrimeMonitorCore` owns ports, reported readings, presentation formatting, cadence,
staleness, backoff and backend contracts. `AnkerCloud` owns REST/login crypto,
throttling, MQTT framing and transient TLS identity composition. `PrimeMonitor`
composes the live backend with native AppKit menu/panel/Settings hosting and a
provider-neutral credential boundary. The first adapter invokes the 1Password
CLI through bounded asynchronous subprocess handling.

`MonitorController` owns authentication, connection and charger-selection
generations. It rejects obsolete async results and renews event subscriptions at
account boundaries so queued old events cannot cross into a new session. Polling
has one guarded connected transition. Sleep/network recovery cleans up before
reconnecting; terminal authentication failure requires explicit sign-in.

Port switch control follows [the port-control plan's "Design
decisions"](port_control_implementation_plan.md#design-decisions). `PortOperation`
(Core) is a clock-free state machine for one turn-off, turn-on or restart: it
takes `requested`, publish results, snapshots with their receive marks, ticks,
disconnection, reconnection fences and ending reasons, and returns publish,
status-request and finish actions. `MonitorController` owns the one running
operation (`portOperation`) and the last unconfirmed result (`portOutcome`), so
closing the panel changes nothing. It refuses a second operation, and any while
disconnected or stale (`portControlBlock`). It executes publishes through
`ChargerBackend.setPortSwitch` and issues operation status requests beside
normal polling, which the staleness tracker still records. The 1 s
`scheduleTick` drives operation time. Link loss suspends the operation; each
reconnection reads `commandFence()` to resume it and to move the outcome's
clearing boundary onto the new connection. Publish results are accepted only
for the same operation, account, selection and connection generations. A write
that fails with `ChargerBackendError.linkClosed` is a link loss, not a publish
failure: the backend also reports the loss as a status, in either order. If that
status already arrived, the result is obsolete; otherwise the controller waits for
it and reports the publish as failed only if none follows within the confirmation
deadline. Any other write error fails the phase at once.

Sign-out, charger selection, credential edits, Retry, Reload Credentials, sign-in
and quit end the operation synchronously at entry, before they invalidate
anything. A restart's ending "on" write is issued to the backend while its old
connection is still current, after any in-flight switch write, in one task that
becomes `cleanup`. No link is captured: ordering comes from that task running
before the caller's disconnect (which awaits `cleanup`), and so before any
replacement connection, plus the backend's own context check on the write.
Overlapping endings share the task. `PortControlPolicy.exitAttemptTimeout`, on
the injected scheduler, bounds the attempt: the write gets the budget less
`MonitorController.portEndingDrainReserve`, and on expiry the controller calls
`abortCommands()`, which revokes the context and drains pending sends within the
reserve. A drain that outlasts the reserve is still awaited, since bytes already
written cannot be recalled and a replacement must not start first. If no
context change replaced the connection, it then reconnects through the
ordinary disconnect path. Terminal authentication statuses end the operation
without a write. `AppDelegate` awaits `endPortOperation()` before
`MonitorController.stop()`. The outcome survives these context changes. Dismiss,
a new operation, or fresh matching evidence from its own account and charger
clears it.

`MemorySessionStore` retains credentials and renewed service sessions only in
RAM. `StateStore` persists nonsecret configuration using private modes and atomic
replacement (`PrivateFile.replace`). `AppInstanceGate` holds an exclusive process lease. No backend,
credential provider or shell redesign is required for the repository migration.

`DeviceCatalog` (Core) validates the device-name JSON document by hand and
resolves port labels. `DeviceCatalogStore` owns `devices.json`: seeding from
the bundled catalog, signature-checked reload, retained last-good catalog with
a recoverable problem, and read/validate/write naming through the same private
replacement as `StateStore`. File access sits behind `DeviceCatalogFiles`.
Only the GUI branch of `PrimeMonitorApp.main` creates the persistent store
(beside `StateStore().fileURL`, seeded from `Bundle.main`) and injects it
through `AppDelegate`, `StatusItemController`, `StatusContent` and `PanelView`;
live-check never creates it. An omitted dependency is the memory-only
`DeviceCatalogStore()`, which has no file URL, seed, file access or timer, so
tests and snapshot fixtures cannot reach the owner's runtime file.
`StatusItemController` pairs the store's `panelOpened`/`panelClosed` with the
monitor's, which bounds the one-second reload loop to panel visibility.

`PortDetailState`, owned by `StatusItemController` and passed through
`StatusContent` to `PanelView`, holds the one expanded port row, the naming draft
bound to its charger, port and device key, editing state and the last naming
failure, so they survive snapshot replacement and panel closing. Return, focus
loss, closing and row switching all save through `DeviceCatalogStore.setName`.
Escape has one owner action, `StatusItemController.cancel`, reached from
`StatusPanel.performKeyEquivalent`, `StatusPanel.cancelOperation`,
`StatusHostingController.cancelOperation` and the naming field's
`onExitCommand`; none forwards the command to another. While a field in the
hosted content is editing, it cancels the edit (marking cancellation before
clearing focus); it also discards a shown draft left by a failed save when the
field is not focused; otherwise it dismisses the panel. A field removed by a row
or snapshot change ends editing without saving, and `AppDelegate` settles a
pending draft through the same save path before termination.

The expanded status-item session owns a nonactivating panel, with native Escape,
outside-dismissal and Settings window behavior. Synthetic tests and offscreen
renders exercise maintained sources; physical click/Space behavior and system
login registration require installed-app observation.

The status item shows one image drawn by `StatusImage`: the symbol, a 4 pt gap
and the reading. A button title would add NSStatusBarButton title-cell insets
(about 3 pt per side). Colours resolve in the image's drawing handler, under
the menu bar's real appearance; the macOS 27 menu bar draws tinted template
images and tinted titles black on a dark bar.
