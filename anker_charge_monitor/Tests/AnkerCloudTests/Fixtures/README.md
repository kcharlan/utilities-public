# Synthetic fixture provenance

`synthetic_0a00_frames.txt` contains 115 generated 326-byte wire frames, constructed
solely from the public protocol layout. No captured payload, owner measurement,
account identifier or device configuration is an input. Reproduce it with
`node tools/generate_synthetic_frames.mjs` (Node is needed only for regeneration).
The binary padding spells `SYNTHETIC-NOT-A-DEVICE-ROW-…` in ASCII.

Row zero invents C3 at 12345 mV, 321 mA, 123 cW and C4 at 23456 mV, 654 mA,
456 cW. Each subsequent row increments the two currents and reported powers by
the row number; odd rows reverse wire port order. C1/C2 retain invented 7 mA idle
current. These deliberately inconsistent V×A/reported power values detect an
incorrect calculated-power substitution. Unknown binary padding maintains
326-byte frame coverage. Literal expectations in Swift are independent of the
generator; all 115 replies must parse, preserve port order and retain idle data.
Separate tests cover signed Int16 extremes, malformed/truncated data, checksums,
one/two-byte lengths, optional increments, envelope handling and CLI output.

`synthetic_0a00_details_frames.txt` contains 23 generated frames from the same
command, adding invented detail fields `a3`, `b7`, `bd` and `be` (anker-solix-api
commit `9e72894`, `mqttmap.py:_A2345_0a00`) to row zero's port readings above.
Vendor/product IDs `FEED`, `BEEF`, `C0DE` and `0042`, model codes and the
unknown classes are invented, not taken from any device. Its padding TLV spells
`SYNTHETIC-NOT-A-DEVICE-DETAILS-ROW-…`; odd rows reverse wire field order.
Rows cover the identity sentinels, independently absent class/model code,
unknown classes, identity-support values, fault mask combinations, a
`sile`-encoded fault field, each wire type for all four fields, and missing,
short or unsupported fields. Literal expectations in Swift are independent of
the generator, and the earlier corpus is generated unchanged.

`login_vectors.json` is demonstrably synthetic: its scalar is 32 repeated `01`
bytes and its only password input is `synthetic-password-123`. The original
development generator derived P-256 ECDH against the upstream public server
point, then upstream AES-CBC/PKCS7 encryption. Its deterministic expected public
point/shared secret/ciphertext are retained as cross-implementation vectors;
they are not usable account secrets. No original development environment or
upstream authentication cache is needed or distributed.

Status-request and envelope literals use the invented timestamp `0x12345678`.
App, formatting and snapshot fixtures likewise contain invented inputs. Public
fixtures do not establish installed-app authorization, real charger behavior or
native login-item registration.
