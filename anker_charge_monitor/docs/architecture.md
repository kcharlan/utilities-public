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
replacement. `AppInstanceGate` holds an exclusive process lease. No backend,
credential provider or shell redesign is required for the repository migration.

The expanded status-item session owns a nonactivating panel, with native Escape,
outside-dismissal and Settings window behavior. Synthetic tests and offscreen
renders exercise maintained sources; physical click/Space behavior and system
login registration require installed-app observation.
