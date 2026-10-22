# Anker Charge Monitor

Anker Charge Monitor 0.4.0 is a native macOS menu bar app for the Anker Prime
250W six-port charger (A2345). It displays charger-reported power, voltage and
current in physical C1–C4, A1–A2 order. Reported watts are authoritative; the app
does not substitute voltage × current. Inactive readings remain visible.

## Requirements and build

Use macOS 27 or newer, Xcode or Command Line Tools with Swift 6 and the macOS 27
SDK, Git, Bash and ripgrep. Deployment also requires Node.js. There are no third-party Swift dependencies or Python
runtime requirements. From `anker_charge_monitor/`:

```sh
make build
make test
make signing-preflight
make release
```

Normal compilation treats warnings as errors. `make test` runs every Swift test,
scanner regressions and release/install structure checks. The bundle gate builds
the maintained synthetic snapshot renderer once, including its macOS 27 runtime
checks. It writes PNGs and the executable to a private temporary directory.
Signing commands are synthetic only inside isolated release tests; these tests
cannot establish real certificate trust, vault access, physical input delivery,
cloud connectivity or login-item registration. See [SDK audit](docs/macos_sdk_audit_20261019.md)
and [architecture](docs/architecture.md).

## Credentials and setup

Install the [1Password CLI](https://developer.1password.com/docs/cli/get-started/)
(`op`) at `/opt/homebrew/bin/op` or `/usr/local/bin/op`. Open and unlock 1Password
and enable **Settings → Developer → Integrate with 1Password CLI**. Create a
Login item with standard username and password fields. In Settings, enter the
editable item name (initial default **Anker**), an optional vault name or ID to
disambiguate duplicate names, and your country code. Select **Sign In using
1Password / Retry**, approve the normal authorization request, reload chargers
and select the supported A2345. If you rename the item, update the setting.

Credentials and refreshed Anker sessions stay in process memory, including when
1Password closes. Quitting clears this cache, so each fresh process retrieves
credentials and signs in again. **Reload Credentials** fetches password rotations;
a failed reload retains the working cache and shows a recoverable error.
Changing item, vault or country invalidates the prior cache immediately.
**Sign Out** clears memory and saved provider configuration without changing the
1Password item. Resolve any displayed settings-save failure before assuming
sign-out will survive restart.

For retrieval failures, open/unlock 1Password, verify integration and Retry.
If prompted on macOS 27, approve **System Settings → Privacy & Security → Files &
Folders → Anker Charge Monitor → Data shared by 1Password**. See
[1Password integration troubleshooting](https://www.1password.dev/cli/app-integration).
No permission or authorization checks are bypassed. Historical Keychain items
are never automatically read, migrated or deleted.

## Operation and state

Opening the status panel requests readings immediately and every five seconds.
Settings controls closed-panel cadence, charger selection, menu bar text size
and launch at login. Text size runs from 10 pt to the standard 13 pt menu bar
size; the icon scales with it, and a change applies to the status item at once.
The icon and reading are drawn as one image, so the item carries only the menu
bar's own spacing. Stale data and errors dim the icon and retained reading to
grey in light and dark menu bars while data age continues advancing;
a session-ended error offers Sign In Again. A new setup opens Settings.

Each port row shows its connected USB-C device label beside the readings;
hovering shows the full text of a shortened label. A
reported port fault turns the row's label red with a warning triangle and "Fault
reported"; the charger reports one fault bit for both USB-A ports, shown as
"USB-A fault" on each. A charger over-temperature report appears as a red
warning above the rows. A port whose switch the charger reports off shows "Off" in its row, and the two
USB-A ports share one switch, so both show it. Click a row, or press Space or Return on it, to expand
it; one row is expanded at a time and it stays expanded as readings update. The
expanded row shows the fault state, raw fault bits and **Port switch** (On, Off or the
not-reported wording) and, for an identified
USB-C device, a **Name this device** field, the brand class (or "Unknown class
N"), the hexadecimal USB IDs and the device model code. Values the charger did
not report read "Not reported by this charger". The charger's identity-support
value is not used to hide identities: a charger reporting 2 has still
identified devices. The port controls follow these lines (see "Port control").

Press Return or move focus away to save a name; closing the panel, expanding
another row or quitting the app also saves it, and a blank name removes it.
Escape abandons the edit and keeps the panel open, and also discards a typed name
left after a failed save when the field is no longer focused; a second Escape
closes the panel. If a save fails, the typed name and an inline error stay, the
edited row stays expanded, and the name remains available for retry after the
panel is reopened. It is kept in memory only: a save that still fails when you
quit does not stop quitting, and the name is lost. A problem in `devices.json` is
shown once, as a warning below the rows naming the failing entry.

## Port control

The expanded row also turns the port's power off and on. The buttons follow
the switch state the charger reports: a port reported on offers **Restart** and
**Turn off**, one reported off offers **Turn on**, and a port whose switch was not
reported offers all three. A1 and A2 share one switch, so their buttons read
**Restart USB-A ports**, **Turn off USB-A ports** and **Turn on USB-A ports** and act
on both. Never turn off the port that powers this Mac: the app cannot tell which
port that is.

Turn on acts at once. Turn off and Restart cut power, so the first click only arms
them: the button becomes **Confirm turn off** or **Confirm restart** and a caption
names the port, the power it is supplying and the connected device. A second
click of the same button within 5 seconds acts. The action disarms when that time
passes, when you click any other action or change the expanded row, when the panel
closes, when controls become unavailable, and when the account, charger or
connection changes. Escape also disarms it; that Escape does nothing else, so a
name being typed stays as it is and the panel stays open, and the next Escape
behaves as described above.

One operation runs at a time. While it runs, the other ports' controls are
disabled with "Another port is changing."; controls also read "Reconnect to
control ports." while disconnected and "Readings are stale." when readings are
stale. The changing port shows its phase in its row and expanded detail:
"Turning off…", "On again in N s" during a restart's 5-second pause, and
"Turning on…". The charger sends no acknowledgment of a command, so the app
requests status after each command and treats only a later report of the wanted
switch state as confirmation; a restart's pause starts from the report that the
port is off. A confirmed change simply clears the phase text. A change that is
not confirmed within 10 seconds is reported above the rows, prefixed with the
name of the charger it was sent to, with a **Dismiss** button; the in-app
[wording](docs/port_control_implementation_plan.md#wording) lists each message.
A restart whose "off" is not confirmed, because no report arrives in time or the
command fails, does not stop there: it sends "on" at once, without the pause, so
the port is not left off. If that "on" is confirmed, the restart still reports
"Couldn't confirm {port} turned off." because the off-and-on cycle was never
confirmed; if it is not, the "on" failure is reported instead.
That result stays after sign-out or a charger change and is never shown on another
charger's rows. Dismiss, a new operation or a later matching report from the same
charger clears it. Phase changes and results are announced to VoiceOver.

Closing the panel does not interrupt an operation. Sleep, network loss or a
dropped connection pauses it, and it resumes from its phase after reconnecting:
a restart's pause keeps its original end, a restart that was turning on sends
"on" again, and otherwise the app only requests status again. Quitting, signing out,
choosing a charger, editing the credential settings, Retry, Reload Credentials
and Sign In Again end it. Ending a restart attempts one "on" command over the
existing connection if it is still up and signed in; sleep, network loss, an
ended session or a failed sign-in skips it. The whole attempt is bounded to 3 seconds. A sent command
is not confirmation, so a restart ended this way reports that the port may still
be off. Ending a plain
turn-off does not turn the port back on. Check the device itself after any
reported result.

The Anker app may not show a change made here right away. Owner reports in
[anker-solix-api discussion #252](https://github.com/thomluther/anker-solix-api/discussions/252)
describe it receiving the switch states when it opens its connection to the
charger, such as when its device page opens. That is an observation, not a
guarantee: confirm a change on the device and in this panel.

Only nonsecret provider configuration, charger selection, cadence and menu bar
text size are saved in `state.json` under
`~/Library/Application Support/Prime Monitor/`, beside `instance.lock`.
The process lock prevents concurrent instances. The executable, Swift products
and modules retain `PrimeMonitor`; the bundle identifier remains
`local.utilities.prime-monitor`. These internal names preserve settings across
the display-name change. They do not promise continuity of 1Password/TCC grants.
MQTT private identities use transient Security objects rather than disk files.

Names for connected USB-C devices live in `devices.json` in the same directory.
When it is absent, the app copies its bundled `device_catalog.json` there: the
brand classes named by the protocol authority, with empty `vendors` and
`devices`. Existing content is never replaced, and deleting the file restores the
bundled names on the next check. The file is schema `1` with `brands` (decimal
class keys), `vendors` (four hexadecimal digits) and `devices` (`VID:PID`)
objects, either hex letter case. Names are strings of 1–64 characters after
trimming; two spellings of one key are rejected. `source` and other top-level
keys are kept. A label uses the device name, then the brand class, then the
vendor, then the uppercase hexadecimal `VID:PID`. A device that has not reported
its identity is labelled "Unidentified device"; some devices never answer, so
that label can persist while the device charges.
While the panel is open the app checks the file every second and decodes it
when its device, inode, size or modification time changes, so editor saves apply
without a restart. An invalid file is left untouched: the last loaded names stay
in use, the panel reports the failing entry and naming is refused until the file
is fixed. Saving a name rereads and validates the file immediately before
writing, matches entries by their decoded key, removes the entry for a blank name
and writes sorted, pretty-printed JSON by private atomic replacement. It is not a
lock shared with editors, so don't save the file in an editor during an in-app
naming write.

Launch at login uses the native service and reports registration failures and
approval requirements. Synthetic tests exercise its adapter contract. Confirm
actual registration, system approval and logout/reboot behavior on the installed
app separately; offline coverage does not establish those outcomes.

## Signing and installation

Release builds require an existing usable code-signing identity. The default
selection is **CodexBar Local**; other machines may need
`make release SIGN_IDENTITY='Your Exact Identity'` or a full 40-hex fingerprint.
Make values require `$$` for a literal dollar. The shared resolver rejects missing
or ambiguous identities before compilation/installation and never falls back to
ad-hoc signing. It uses `security find-identity -p codesigning`, since a usable
self-signed identity need not appear in the valid-only list. Signing uses
`--timestamp=none` and strict verification. Local signature integrity does not
establish Developer ID, notarization, Gatekeeper trust or entitlement grants.

`make release` creates `build/release/Anker Charge Monitor.app`. Consult the
[repository deployment guide](../docs/local_deployment_sync.md) for the maintained
installation workflow. After validation and merge to main, `make install` (or
`make deploy`) calls the root deployment CLI, which builds only the admitted
Git-index inputs in private scratch and installs at
`/Applications/Anker Charge Monitor.app`. It never falls back to `~/Applications`.
Use `SIGN_IDENTITY='Your Exact Identity' make install` to override signing.
From the repository root:

```sh
node tools/deploy_anker_charge_monitor.mjs --dry-run
node tools/deploy_anker_charge_monitor.mjs
node tools/deploy_anker_charge_monitor.mjs --audit
node tools/deploy_anker_charge_monitor.mjs --rollback /private/path/to/copy-backup
```

The mode-0600 receipt is `~/Library/Scripts/.anker-charge-monitor-native.json`;
independent recovery copies remain under
`~/.utilities-deploy-backups/anker-charge-monitor/`. Audit checks source,
receipt, complete bundle bytes/modes and metadata without executing the app.
It does not contact the vault or cloud. The local installer validates source, staged and active
versions and identity, preserves recovery copies, rejects ambiguous legacy/new
names and never stops or relaunches a running process. The old visible name or
version remains until a normal quit/reopen; that restart clears the RAM cache and
requires normal credential retrieval/authorization again. Preserve the runtime
state directory. An old copy in `~/Applications` is retired separately, with a
private backup, only after the canonical installed release is verified.
Launch the `/Applications` copy and confirm Settings → Launch at Login reports
the real system registration/approval state. Moving an app does not establish
that its login registration or 1Password grants follow the new path.

The installed executable at
`/Applications/Anker Charge Monitor.app/Contents/MacOS/PrimeMonitor` supports
`--live-check` (`make live-check`): with the GUI quit, it retrieves
the configured account, prints one fresh reading and awaits cleanup before exit.
The reading includes decoded fault bits, identity support, USB-C device
identities, port switch states and raw detail payloads, with unavailable values marked.
Exit codes are 0 success, 2 missing account/charger, 3 timeout, 4 concurrent
instance, and 5 startup/persistence/backend failure. This contacts the real vault
and service; it is a separate operator acceptance check, outside `make test`.
Its reading output is private and must remain outside the repository.

## Privacy and development

Never put owner patterns, real frames, readings, account identifiers, private
logs or configuration in this public checkout, including ignored paths. From
this project directory run:

```sh
tools/check_secrets.sh
# Optional private external file:
ANKER_CHARGE_MONITOR_SECRETS_FILE=/private/path/secrets-patterns tools/check_secrets.sh
```

The default pattern path is `~/.config/anker-charge-monitor/secrets-patterns`.
Provision it privately with one real owner literal per line, mode 0600. Do not use
blank lines, placeholders or generic protocol names. Missing, unreadable, empty,
blank-containing or linked patterns fail closed with exit 2. A match exits 1;
success prints only `clean` and exits 0. Diagnostics are redacted. The scanner
covers this project's tracked working files, nonignored untracked files, staged
blobs (including deleted working files) and pathnames, without following links
or entering ignored trees. Run from the project directory to scope the monorepo;
neighboring projects are intentionally excluded. It cannot prove that all owner
identifiers were supplied.

All protocol fixtures are conspicuously synthetic. See [fixture provenance](Tests/AnkerCloudTests/Fixtures/README.md),
[protocol reference](docs/anker_protocol_reference.md) and [lessons](docs/lessons_learned.md).

## Attribution

Protocol port: [thomluther/anker-solix-api](https://github.com/thomluther/anker-solix-api)
at `8a5222bebad7bb56b99b17ae5e86c2750b94ec83`, notably `mqttmap.py:_A2345_0a00`,
`mqtttypes.py`, `session.py`, `mqtt.py` and `errors.py`. Fault, temperature and
connected-device detail fields follow `9e72894181aef868e7b3ed0ba05bd322d54bb5d7`
(`mqttmap.py:_A2345_0a00` keys `a3`, `b7`, `bd`, `be`, the `aa` to `ae` port switches and
`mqtttypes.py:DeviceHexDataField.extract_value`), as does the `0207` port switch
command (`mqttcmdmap.py:CMD_USB_PORT_SWITCH` and `mqtt.py:generate_mqtt_command`). Its applicable
[MIT license and copyright notice](docs/anker-solix-api-LICENSE.txt) are retained.
The public server key is a protocol constant, not an owner credential.
App/menu/plist/release and snapshot structure derive from `brew_version` at
`579ebb7`; local installer staging/recovery derives from
`tools/deploy_brew_version.mjs` at that revision. No upstream clone, authentication
cache, private capture or development environment is distributed here.
