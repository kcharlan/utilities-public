# Anker Charge Monitor

Anker Charge Monitor 0.2.0 is a native macOS menu bar app for the Anker Prime
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
Stale data and errors dim retained readings while data age continues advancing;
a session-ended error offers Sign In Again. A new setup opens Settings.

Only nonsecret provider configuration, charger selection, cadence and menu bar
text size are saved in `state.json` under
`~/Library/Application Support/Prime Monitor/`, beside `instance.lock`.
The process lock prevents concurrent instances. The executable, Swift products
and modules retain `PrimeMonitor`; the bundle identifier remains
`local.utilities.prime-monitor`. These internal names preserve settings across
the display-name change. They do not promise continuity of 1Password/TCC grants.
MQTT private identities use transient Security objects rather than disk files.

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
`mqtttypes.py`, `session.py`, `mqtt.py` and `errors.py`. Its applicable
[MIT license and copyright notice](docs/anker-solix-api-LICENSE.txt) are retained.
The public server key is a protocol constant, not an owner credential.
App/menu/plist/release and snapshot structure derive from `brew_version` at
`579ebb7`; local installer staging/recovery derives from
`tools/deploy_brew_version.mjs` at that revision. No upstream clone, authentication
cache, private capture or development environment is distributed here.
