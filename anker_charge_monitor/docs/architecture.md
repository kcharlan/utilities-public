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

The expanded status-item session owns a nonactivating panel, with native Escape,
outside-dismissal and Settings window behavior. Synthetic tests and offscreen
renders exercise maintained sources; physical click/Space behavior and system
login registration require installed-app observation.

The status item shows one image drawn by `StatusImage`: the symbol, a 4 pt gap
and the reading. A button title would add NSStatusBarButton title-cell insets
(about 3 pt per side). Colours resolve in the image's drawing handler, under
the menu bar's real appearance; the macOS 27 menu bar draws tinted template
images and tinted titles black on a dark bar.
