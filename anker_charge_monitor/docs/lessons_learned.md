# Lessons learned

## 2026-10-19: Preserve a single owner of bundle activation

The root deployment CLI captures tracked release inputs and checks app/receipt
provenance; the existing shell installer owns whole-bundle staging and moves.
This keeps the retained legacy-name, failed-activation and held-reader tests on
the actual activation path. A receipt publication or scratch-cleanup failure
must recover app and receipt together, including a first installation. Never
probe this app with CLI help/version flags: they can start production work.
The private build snapshot also explicitly restores indexed file modes after
creation, so a restrictive owner umask cannot silently change build inputs.

## 2026-10-19: Check external argument contracts and installed-version scope

`codesign -R` reads a filename unless literal requirement source begins with `=`.
Synthetic signing must assert the actual argument, including that prefix and the
identifier/certificate constraints, rather than accepting any verification call.
Existing-app ownership validation must allow a legitimate older version; exact
current-release version checks belong to source, staged and activated bundles.
Lower-version legacy and renamed fixtures now exercise success, original-path/
inode rollback, independent recovery and held-reader bytes.

## 2026-10-19: Rename installed bundles with original-path rollback

A display-name migration needs separate destination and previous paths. Validate
the previous bundle identity/signature before displacing it, reject both names
present together, preserve an independent byte copy, and restore the original
path/inode on activation failure. Whole-bundle moves keep existing executable
readers intact. Synthetic regressions cover those guarantees without interacting
with the running process or repeating credential gates.

## 2026-10-19: Preserve decoded paths when modernizing Foundation URLs

URL.path(percentEncoded:) defaults to true, unlike the former path property.
Explicitly request false for POSIX and path-based FileManager calls; otherwise
spaces, Unicode and literal percent escapes can address different files.
Use appending(path:directoryHint:) for multi-segment REST paths and known file
types. Synthetic state/lock tests now cover spaces, percent, café and literal
%2F, held readers across atomic replacement, repeated corrupt-file quarantine
and exclusive locking. They passed before the migration: this is prevention
of a migration regression, not evidence of a pre-existing path bug.

Swift warnings-as-errors does not diagnose every announced migration. The
SDK's deprecated:100000.0/API_TO_BE_DEPRECATED markers require direct review;
supported successor APIs alone do not prove that existing APIs are obsolete.

## 2026-10-19: Compute struct properties before mutating stored arrays

Swift rejects a mutating `removeAll` closure that reads a computed property on
the same struct because the accesses overlap. Capture the computed age limit
in a local value before filtering staleness grace records. The Swift build
checks this exclusivity rule; deterministic staleness tests cover the filtering
behavior.

## 2026-10-19: Keep REST retry delays inside the normal throttle gate

A random retry backoff must still pass through the endpoint's minute limit.
Applying the random delay as a replacement for the normal request gate skipped
that limit after an HTTP 429. Wait for the retry backoff, then re-evaluate current
endpoint history and the global response gap. Hold the transport permit across
its await so overlapping actor calls cannot observe the same available slot.

## 2026-10-19: Separate login time-zone offsets from the header offset

Upstream freezes its GMT header when constructing the session, while the login
body uses the current date's UTC offset. Passing a dynamic time zone to the
header builder on every request silently changes this behavior across daylight
saving transitions. Capture a fixed-offset zone at client construction and keep
the original zone for the login body; a synthetic November-to-July test pins both.

## 2026-10-19: Follow the REST counter helper's actual minute window

The protocol summary calls endpoint history a minute, but upstream
`helpers.py:RequestCounter.last_minute` at `8a5222b` includes a two-second margin.
Keep attempts younger than 62 seconds when deciding whether ten attempts trigger
the 65-second oldest-attempt delay. A boundary regression with a 61-second-old
attempt catches using a literal 60-second window.

## 2026-10-19: Capture account generations before asynchronous cleanup

A restore that first awaited a slow MQTT close could resume after a newer
restore and replace the newer account. Change the authentication generation
before the first await and validate it after each asynchronous boundary.
Retain and await cleanup already in progress so actor reentry cannot open a
replacement link before the previous link and temporary identity are disposed.
A gated-close regression reproduces the obsolete account overwrite.

## 2026-10-19: MQTT publishes can arrive while awaiting subscription acknowledgments

A PUBLISH can be interleaved before SUBACK. Treating the next packet as the
acknowledgment incorrectly rejected a working connection. Continue decoding
publishes while waiting for the matching control packet, and gate connected
status on all acknowledged subscriptions. An interleaved-PUBLISH test pins this.

## 2026-10-19: Separate initial metadata acquisition from certificate refresh

A failed initial REST metadata fetch must not consume the once-per-recovery
certificate refresh. Retry initial acquisition through normal backoff until
metadata exists; only then can a refused MQTT handshake trigger that refresh.
Keep later reconnect backoff continuous across its first delayed attempt.
Tests cover initial REST failure followed by a refused CONNACK and successful
refresh, plus several refused connections before eventual success.

## 2026-10-19: Preserve terminal REST authentication failures across recovery layers

The REST client bounds HTTP 401/403 reauthentication and then throws
`AnkerError.http(status)`; login lockout code 100053 becomes `.retryExceeded`.
A backend classifier that recognizes only `.authorization` restarts its own
recovery loop after REST has deliberately stopped, potentially retrying stored
credentials or swallowing lockout during certificate refresh. Classify all
terminal REST representations at the shared backend boundary, emit the
session/sign-in failure and propagate the original error. A six-case regression
covers exhausted 401, exhausted 403 and lockout during both initial MQTT info
acquisition and certificate refresh, asserting exact REST/login call counts,
identity cleanup and no reconnect delay.

## 2026-10-19: Reserve terminal auth events for actual authentication failures

A deliberate backend disconnect previously emitted `sessionEnded`. A controller
that correctly prevents automatic retries after token rejection then treated
sleep or network loss as a terminal authentication failure and never reconnected.
Explicit disconnect now performs cleanup without an auth-status event; the
controller owns the lifecycle presentation. The same backend terminal classifier
also reports sign-in and discovery errors through Core, so the app need not
import transport error types. Capture authentication and connection generations
before awaiting and suppress obsolete results. Backend and controller regressions
cover explicit disconnect, offline wake, invalid credentials, verification,
lockout, exhausted HTTP authentication, and replacement of a pending account.

## 2026-10-19: Unify the connected event and connect-return transition

The backend emits connected status before its `connect` call returns. Starting
polling independently at both boundaries can publish twice, depending on task
scheduling. Route both through one guarded transition. A fake backend that emits
connected status and then holds the call open reproduces the duplicate reliably.
Cancelling an `AsyncStream` iterator terminates that subscription. Use a fresh,
independent subscription after invalidating old backend producers and cancelling/
awaiting its consumer; never reuse a terminated subscription for a new account.
The original lifetime-consumer workaround was insufficient because an already
queued same-user session or terminal status could cross account replacement.

## 2026-10-19: Producer generations do not protect already queued events

A backend generation guard prevents obsolete work from emitting later, but it
cannot retract events already queued in an AsyncStream. Matching user IDs is
also insufficient: two sign-ins to one account have different authentication
contexts. Use a fresh nonreplaying subscription at every sign-in/restore boundary,
including reconnect. First invalidate producers through awaited disconnect, then
cancel and await the old consumer, then subscribe before accepting the new
context. Never bridge old buffers into the new subscription. Lazy subscriptions
avoid an unused compatibility queue retaining unbounded events. Deterministic
tests retain the old delivery queue and attempt same-user session and terminal
status delivery after both replacement and sign-out/re-sign-in.

## 2026-10-19: Give selections their own pre-await generation

Account generations do not order two charger selections within that account.
Supersede the prior selection before awaiting disconnect, and validate both the
selection generation and selected charger before connecting. Otherwise selection
A can queue a connection while B is being persisted, leaving the display showing
B while monitoring A. Also ignore connection-status events during deliberate
cleanup: a queued connected event can otherwise prevent the replacement
connection from starting. Gated cleanup tests exercise both interleavings.

## Public migration: keep scanner inputs external and scope Git enumeration

Git supports project-relative enumeration in a monorepo. A scanner must inspect
both staged blobs and working files under that scope, including staged-only
findings, while excluding unrelated neighboring projects. Private owner patterns
belong outside the checkout; reject missing, blank, unreadable or linked files.
Do not replace captured data with lightly edited copies: construct test frames
from public field layouts and independently invented values before importing.

## 2026-10-19: Check symlinks in every working-file path component

A tracked file can remain in the index after its parent directory is replaced
by a symlink. Checking only the final path component follows that link into an
ignored tree. Walk the path components before opening a working file, skip
linked paths, and independently scan the original index blob. The scanner
regression suite reproduces that replacement and also covers direct symlinks.


## 2026-10-19: Distinguish unreadable ancestors from deleted working files

A shell existence test returns false for both deletion and a file hidden behind
an unsearchable parent directory. Checking only the index then accepts an older
safe blob while the current unreadable file may contain a secret. Check existing
parent search permissions before accepting an indexed deletion. Git enumeration
has a separate trap: `ls-files --others` can warn about an unreadable directory
while returning zero and omitting its files. Capture that stderr privately and
reject it rather than claiming a complete scan. Regress tracked descendants and
untracked directories with mode 000, and preserve clean results for intentional
deletions, symlinks and ignored locked trees.


## 2026-10-19: Exclude reconnect while accepting a charger selection

Giving a selection a new generation before cleanup is necessary but insufficient
if the persisted charger still names the old choice. A path-available or wake
event can reconcile that new generation with the old charger and retain an
aborted connection task forever. Keep a supersession-safe pending-selection
token that excludes reconciliation until the winning selection is installed.
Release connection slots in a defer that checks attempt ownership, so every
early return frees its own slot without clearing a successor. The regression
holds selection cleanup, sends network/wake, then checks the selected charger
connects and later system events remain usable.


## 2026-10-19: Replace REST context before exposing its fresh relay

Subscribing to REST session updates and only later replacing REST authentication
creates a relay window: a pending old login may be accepted into the fresh
backend forwarder. Prepare authentication atomically within the REST actor:
replace the old context, create the nonreplaying relay, and return an opaque
prepared-login capability. Network login then checks that capability. Assign an
ordered preparation sequence in the backend before its first await and validate
it inside REST, so an obsolete backend message arriving late cannot replace a
newer REST setup. Disconnect also advances that ordering and invalidates REST.
Tests prove the former subscribe-first window, obsolete preparation rejection,
old prepared-login rejection, and suspended-old/current-only relay behavior.


## 2026-10-19: Publish startup status before awaiting restore

A configured controller briefly retained `.notConfigured` after `start()` while
its restore task waited. A one-shot diagnostic read that state synchronously and
returned missing-account code 2 before connecting. Publish `.connecting` as soon
as saved secrets are loaded, while retaining state-load errors. The synthetic-frame
live-check regression catches premature exit before readings arrive.


## 2026-10-19: Display signing authority with sufficient verbosity

`codesign -dv` omits the Authority line even for a valid installed signature.
Use `codesign -dvv` to display the authority and separately run strict signature
verification. Missing display output at lower verbosity does not establish a
missing or invalid signing identity.


## 2026-10-19: Preserve state-load diagnostics without an account

When state decoding failed, `start()` replaced its diagnostic with
`.notConfigured` if no saved account existed. The one-shot mode then returned 2
instead of the required persistence-failure code 5. Retain an existing error in
that path; a corrupt synthetic state-file regression covers the distinction.


## 2026-10-19: Explicitly return failures from shell validation functions

Bash suppresses `errexit` inside a function invoked by an `if ! function` test,
including nested validation calls. A failed plist comparison could otherwise be
followed by a successful signature command and accept the activation. Return
explicitly on every failed contract check. A private test PATH mutates activated
synthetic metadata and verifies that installation fails and restores the prior
bundle.


## 2026-10-19: Keep vault adapters separate from session lifetime

Use a small asynchronous CredentialProvider for a coherent credential pair and
inject it through composition. The controller compares an opaque nonsecret
CredentialSelection; only settings/composition interpret adapter keys. The
shared MemorySessionStore knows neither 1Password arguments nor field JSON.
A later Azure adapter can reuse cache, backend and controller unchanged.
Credentials and refreshed sessions now last only for this process. Same-selection
reload fetches a candidate before replacing known-good cache; failure retains the
cache and a visible warning even across reconnect events. Item/vault/country
edits and sign-out invalidate immediately. Each retrieval needs its own ordering:
provider-context generations alone let an older same-provider read overwrite a
newer credential/session. Cancel superseded reads, reject older candidates, and
retain drain tasks so shutdown joins them without delaying the replacement read.
Synthetic tests reproduced both the stale overwrite and the blocked replacement.


## 2026-10-19: Preserve fragmented nonblocking process output

Foundation read(upToCount:) can consume partial pipe output and then throw a
Cocoa file-read error wrapping POSIX EAGAIN. Treating that error as an empty poll
silently loses bytes and intermittently rejects valid JSON. A synthetic executable
writing its JSON in two delayed fragments reproduced this deterministically.
Use supported Darwin.read on the nonblocking FileHandle descriptor to retain the
actual partial byte count; use current throwing FileHandle.close for cleanup.
One worker owns both readers, enforces the combined output bound and deadline,
terminates then kills a resistant child after a short grace period, and joins it
before resuming. Tests check that the PID is gone before timeout/cancel returns.
No raw stdout, stderr or item metadata is used in errors.

A settings-save failure also must survive successful authentication and sign-out:
otherwise a failed removal of saved provider settings looks like durable sign-out.
Keep state diagnostics separate from transient cache/retrieval diagnostics.


## 2026-10-19: Give the shared cache its complete provider selection

A replacement controller's initialization recreated its provider and cleared the
shared in-process credential/session cache, even when persisted settings still
selected the same account. A configured flag cannot distinguish accounts. Keep
an opaque CredentialSelection in the shared store: replacing a provider for the
same complete selection preserves cached credentials and refreshed session;
changed provider/item/vault/country or unspecified context invalidates them.
The REST integration must include persisted selection and the production-style
factory on both controllers. With the subsequent reader unavailable it now proves
one provider read total, no restart login, and reuse of the refreshed token. The
older test omitted selection/factory and therefore bypassed the initialization
branch where the cache was lost. Fresh-process retrieval remains independent.

Directory observations in identity tests must also distinguish an absent root
from other I/O failures. Sort successful entries, return an empty observation
only for file-read-no-such-file, and propagate other errors. Keep the independent
real SecItem negative-persistence check intact.


## 2026-10-19: Observe status-button geometry on AppKit's notification center

Injecting lifecycle notification centers does not redirect NSView's frame-change
notifications. Observe button frame changes through NotificationCenter.default,
with postsFrameChangedNotifications enabled, and unregister during teardown.
A real button-width regression caught the panel remaining at its former anchor.
Use the current frame independently for each mouse-down and mouse-up hit test.


## 2026-10-19: Gate synthetic pending reads before timeout assertions

New concurrent AppKit setup exposed a lost-release race in the pending LiveCheck
test: its 50ms sleep could finish before the provider installed its continuation.
Wait for an explicit provider-entry latch, then observe the actual timeout output
before checking that cleanup still holds the lease. Release that established
read and retain the exact timeout/no-login assertions. Wall-clock sleeps do not
prove an asynchronous operation has reached the intended boundary.


## 2026-10-19: Keep literal vault item names through observed Settings edits

Settings observation can echo a just-saved credential selection while the user
is still typing. Rehydrating the input on every echo removed a space before the
next word, turning "Synthetic Login" into "SyntheticLogin". Preserve the current
draft when its selection already matches the controller. A different saved
selection still updates item, vault and country. Item names also remain literal
through persistence and view reappearance, including leading/trailing spaces;
trim only to reject an all-whitespace name, as OnePasswordProvider already does.
Focused regressions reproduced both the typing loss and persisted-name loss
before the fixes. Edits still synchronously invalidate the old cache context.


## 2026-10-19: Render maintained views within a private temporary boundary

The final source-copy snapshot executable compiles actual Core/app sources with
fake backend/provider, process-memory cache, inert SystemEvents/manual scheduler
and fake LoginService. No installed app, real vault, owner settings or login
registration is needed. Resolved path-component containment avoids the trailing
directory slash retained by modern URL.path(percentEncoded:). Pixel checks sample
every pixel for the tiny icon-only menu image, rather than sparsely sampling away
the bolt's antialiasing; panel/Settings captures retain sampled pixel checks.
Rendering both appearances exposed a redundant serial row after the native
picker began showing the serial as secondary text; remove the duplicate row.
The 460x600 reused Settings viewport scrolls to Updates/General while its version
and protocol footer stay visible. Existing owned-panel size/visibility/lifecycle
assertions were retained unchanged. Synthetic renders do not establish native
MenuBarAgent physical clicks, actual Spaces or the user's login registration.


## 2026-10-19: Observe time when displaying retained-reading age

Calling Date() inside a SwiftUI body does not create a redraw dependency. After
network loss, an error or session-ended, snapshot/status/staleness can all settle.
The existing one-second tick then assigns the same Equatable stale Bool, which
Observation does not notify, so the displayed retained-reading age freezes.
Publish displayTime from the injected clock in the existing updateStale/tick
path and use it in the actual panel header. Keep one scheduler owner and the
existing request cadence. A regression observes the maintained PanelView.body,
holds snapshot/status/stale unchanged and advances that existing manual clock:
all four stale/network/error/session-ended cases failed with zero invalidations
before the fix, then passed with advancing2min→3min labels and no extra polling.

## 2026-10-19: Share observed display time with status-button metadata

The panel's observed time dependency also belongs in StatusObservation. Its
separate unobserved now closure let actual status-button tooltip, accessibility
label and accessibility help retain an old age after readings/status/staleness
settled. Remove that duplicate clock and read controller.displayTime inside the
maintained observation. This reuses the injected controller clock and existing
tick, with no new timer or network owner. A real-button regression holds the
retained state unchanged in stale/network/error/session-ended cases and advances
the existing manual clock: tooltip plus both AX strings must move2min→3min,
while request counts retain the established cadence. It failed in all four cases
before the fix and passed afterward.
## Transient identity checks must prove behavior

Use SecKeyCreateWithData, SecCertificateCreateWithData and SecIdentityCreate to
compose a memory-only TLS identity. A floating RSA key may report isPermanent
true in copied attributes even though the public API never persists it. Verify
nonpersistence using an independent persistent-reference lookup; verify key
compatibility by signing a synthetic challenge and checking its certificate
public key. Do not require raw private-key export. Retain the identity until the
link and timers finish, then release it before retry/disconnect completes.

## Preserve reported scaled integers

Keep signed voltage/current/power wire integers through decoding and sum reported
power fields. Display hundredths of watts and thousandths of volts and amps.
Do not infer inactivity from zero reported watts or erase idle current.
