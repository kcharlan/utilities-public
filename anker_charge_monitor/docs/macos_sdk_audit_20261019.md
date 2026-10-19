# macOS SDK currency audit — 2026-10-19

Examined Xcode 27.0 (27A266a), macOS 27.0 SDK and Apple Swift 6.4
(swiftlang-6.4.0.34.1), targeting native arm64 macOS 27. The audit covers all
first-party Sources, Tests, Package.swift, resources, Makefile and shell tools.
Ignored reference clones, private account material and generated artifacts are
excluded. Introduction dates are not deprecation dates. These findings describe
the inspected SDK and published guidance, without guaranteeing future support.

## Required findings

- **F1 repaired:** TLSIdentity constructs transient Security objects with
  SecKeyCreateWithData, SecCertificateCreateWithData and SecIdentityCreate.
  Deprecated SecKeychain lifecycle calls and disk/keychain identity persistence
  are removed. Synthetic tests exercise actual certificate equality, private-key
  signatures, mismatched keys, malformed PEM and local TLS trust/hostname checks.
  [SecIdentityCreate](https://developer.apple.com/documentation/security/secidentitycreate(_:_:_:))
  supports direct certificate/private-key composition. This is offline synthetic
  evidence; live service compatibility is a separate checkpoint.
- **F2 repaired — selected replacement 1Password with memory cache:**
  The production KeychainStore and actual generic-password Keychain tests are
  removed. A small provider-neutral async CredentialProvider feeds the shared
  MemorySessionStore; OnePasswordProvider is the first adapter. Only nonsecret
  provider configuration is persisted. Credentials and refreshed sessions remain
  in memory, and historical Keychain items are never automatically read/deleted.
  [Apple DTS](https://developer.apple.com/forums/thread/724023) describes that
  implementation as on the road to deprecation; SecItem itself is supported.
  [TN3137](https://developer.apple.com/documentation/technotes/tn3137-on-mac-keychains)
  recommends data protection and explains provisioned access-group requirements.
  The adapter uses 1Password with memory caching and recoverable errors.
  Synthetic CLI boundary and REST/session tests do not prove installed GUI
  authorization, cloud access, or the physical charger checkpoint.
- **F3 repaired:** all first-party URL appendingPathComponent, fileURLWithPath,
  path and host properties use appending(path:directoryHint:),
  filePath:directoryHint:, path(percentEncoded:false) and
  host(percentEncoded:false). The SDK marks the former APIs with the future
  sentinel deprecated:100000.0; quiet compilation did not mean current advice.
  [URL path](https://developer.apple.com/documentation/foundation/url/path(percentencoded:))
  defaults to encoded output, so filesystem/POSIX calls explicitly request decoded
  paths. REST endpoint appending preserves multi-segment separators. Synthetic
  paths cover spaces, percent, Unicode and literal %2F, atomic inode replacement,
  both quarantine naming branches, absence of encoded siblings and exclusive
  instance locking. Supported appendingPathExtension, deletingLastPathComponent,
  URL(string:) and custom MQTT host fields remain.
- **F4 repaired:** synthetic certificate generation already uses throwing
  FileHandle.write(contentsOf:), readToEnd() and close(). No nonthrowing legacy
  FileHandle read/write/close operations remain. NSFileHandle.h marks the older
  variants API_TO_BE_DEPRECATED; the throwing successors preserve Swift errors.
  [Legacy write documentation](https://developer.apple.com/documentation/foundation/filehandle/write(_:))
  explains the replacement. Actual synthetic certificate generation remains
  exercised, rather than replacing the operation with a stub.

## Remaining surface inventory

| Surface | Reviewed uses and conclusion |
| --- | --- |
| App lifecycle/UI | AppKit application/delegate/menu/window/alert, SwiftUI views and modifiers, Observation macros: supported. No UIKit scene migration applies; activate() is used. |
| Persistence/locking | FileManager/Data/JSON, private modes, Darwin open/fchmod/flock/rename/close/errno: supported. Decoded paths preserved. Credential cache is memory-only; F2 repaired. |
| Credential subprocess | Foundation Process.executableURL/run/isRunning/terminate/waitUntilExit, Pipe, throwing FileHandle.close, DispatchQueue, Darwin fcntl/read/kill: supported in the installed macOS 27 SDK. Nonblocking POSIX read preserves fragmented byte counts where Foundation's filling read can throw after partial consumption. No legacy launchPath/launch or deprecated FileHandle read/close calls. One worker bounds output/deadline and owns termination, reader closure and child reap. |
| HTTP/authentication | URLSession ephemeral async data(for:), URLRequest/HTTPURLResponse, CryptoKit P256, CommonCrypto CCCrypt CBC/PKCS7, CryptoKit Insecure.MD5: supported. MD5/CBC are required protocol compatibility, not SDK deprecations. |
| TLS/security | Security certificate/key/identity/trust and sec_protocol options, custom root/hostname validation: supported. No Secure Transport, deprecated SecTrustEvaluate or SecKeychain lifecycle remains. |
| MQTT/network — M1 | NWConnection/NWParameters/NWProtocolTLS/NWEndpoint and NWPathMonitor callbacks remain supported; no matched removal announcement. NetworkConnection and path AsyncSequence are optional successors, not required deprecation fixes. |
| Notifications — M2 | NSWorkspace sleep/wake names and NotificationCenter block observers remain supported. Typed messages are optional supported successors. |
| Concurrency/core | Task/actor/AsyncStream/continuations, NSLock.withLock, DispatchQueue, Date/TimeZone/Duration/ContinuousClock, Codable/value types and numeric formatting: supported. |
| Tests | Swift Testing, Bundle resource lookup, Process/Pipe/current FileHandle and synthetic Security operations: supported. No XCTest legacy async boundary. |
| Build/resources/tools | SwiftPM macOS27/Swift6, plist metadata, shared matching-identity resolver using security find-identity -p codesigning (without valid-only filtering), codesign resolved-hash signing/strict verification, PlistBuddy/vtool, Bash/Git/ripgrep and installer filesystem tools: no matched SDK deprecation. A separately provisioned usable signing identity is required. Structural signing mocks do not prove real trust. |

[TN3151](https://developer.apple.com/documentation/technotes/tn3151-choosing-the-right-networking-api)
documents networking choices; [notification messages](https://developer.apple.com/documentation/foundation/notification-center-messages)
documents typed observers. Neither establishes expiration of the exact M1/M2
operations used here. NSLock is also supported; an available successor is not
evidence that the current symbol is deprecated.

The synthetic test helper uses the installed /usr/bin/openssl command (LibreSSL).
Apple's historical OpenSSL **library** deprecation does not establish a dated
removal of that CLI. Its continued presence is a test dependency risk. No Python generator is shipped or needed for the runtime or tests. The retained
login-vector provenance is documented with the synthetic fixtures.

## Validation boundary

Normal make build/test/release commands pass -Xswiftc -warnings-as-errors.
This catches compiler-active warnings; future sentinel deprecations still need
SDK review. Full make test includes Swift, secrets-scanner regressions and real
release/bundle/install structure in private scratch locations with synthetic
signing. Owner secrets scanning is required before handoff. Production
installation, launch, credential reads, real signing trust and live charger
behavior are not established by these checks. F1–F4 are repaired in source;
the explicit installed-app and live checkpoint gates remain open.

## Menu-bar shell surfaces

Reviewed the installed macOS27 SDK headers and Swift interfaces before copying
brew_version at 579ebb7. NSStatusItem.h:27–34,80–84 declares the expanded-interface delegate,
session and callbacks available in macOS27. Its contract sets the session before
begin and clears it before end; the port preserves identity guards and owned
nonactivating-panel presentation. NSStatusBar variableLength, NSPanel window
styles/levels, NSWindow moveToActiveSpace/fullScreenAuxiliary and native scrolling,
constraints, screen conversion and Escape handling have no matched active or
future-sentinel deprecation on the used declarations. The port uses supported
NSVisualEffectView semantic `.popover` material, not deprecated appearance/light/
dark variants. NSView.h:120,702–704 supports frame-change notifications;
NSFont.h:63–66 supports monospaced digit system fonts; NSButton.h:120–121 supports
contentTintColor but explicitly excludes attributed strings, so title foreground
color is set independently. Accessibility, template symbols and appearance are
supported on the inspected AppKit declarations.

NSApplication.h:222 announces future deprecation of activateIgnoringOtherApps;
both copied activation closures use activate() (line236, macOS14+) instead.
SwiftUI's NSHostingController.sizingOptions/preferredContentSize and SwiftUICore
onGeometryChange are supported; grouped Form and Observation use current APIs.
SMAppService.h:91,172,201,248,283 declares mainApp/status/register/unregister/
openSystemSettingsLoginItems available macOS13+, without active or announced
future deprecation. LoginItem preserves requiresApproval and the explicit system
approval action through injected LoginService. Offline tests never register the
owner's login item or open System Settings.

The symbol/header references above record the inspected SDK provenance.
No third-party Swift dependency or additional scheduler was introduced.

## Final content and source-copy renderer

Inspected the installed macOS27 Foundation and SwiftUI/SwiftUICore interfaces
and AppKit headers for newly used surfaces. `Locale.Region.identifier` and
`Locale.Region.isoRegions` are supported macOS13+; the old
`Locale.isoRegionCodes` accessor is explicitly deprecated and is not used.
Grouped Form, LabeledContent, Picker, ProgressView, monospaced digits,
accessibilityElement(children: .ignore), accessibilityLabel/help,
accessibilityReduceMotion and withAnimation have no active or future-sentinel
deprecation on the used declarations. Reduce Motion bypasses withAnimation and
uses an hourglass rather than an animated refresh progress indicator.

The copied renderer uses `URL(filePath:directoryHint:)`,
`appending(path:directoryHint:)`, `path(percentEncoded:)`, pathComponents and
resolvingSymlinksInPath rather than reintroducing the reference's older URL
accessors. Foundation directory URLs retain a trailing slash through
path(percentEncoded:), so the private temporary-root guard compares resolved
path components instead of constructing a double-slash prefix. NSView.h:209–210
declares bitmapImageRepForCachingDisplay/cacheDisplay; NSBitmapImageRep.h:147
declares PNG representation; NSAppearance.h:36 declares
performAsCurrentDrawingAppearance (macOS11+). None has a matched deprecation.
The deprecated NSBitmapImageRep focused-view initializer and NSAppearance's
currentAppearance setter are not used. NSControl.sizeToFit remains supported.
The extracted status-button apply method is explicitly @MainActor.

The inspected interface/header symbol locations above are the audit provenance.
The source-copy builder and bundle regression use strict compilation and check
the snapshot executable minimum OS and SDK against macOS 27. Future-sentinel
checks still require SDK review even when compilation is warning-free.
