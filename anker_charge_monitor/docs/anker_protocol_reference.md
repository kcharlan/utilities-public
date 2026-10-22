# A2345 read-only cloud protocol

Baseline: [anker-solix-api](https://github.com/thomluther/anker-solix-api) commit
`8a5222bebad7bb56b99b17ae5e86c2750b94ec83`, under its retained MIT license;
detail fields (§6.2) follow commit `9e72894181aef868e7b3ed0ba05bd322d54bb5d7`.
References below are upstream module/symbol names under `src/anker_solix_api/`;
the maintained Swift code defines the port's actual behavior. No private capture
or owner activity is part of this reference.

## 1. REST and authentication

`apitypes.py:API_SERVERS/API_COUNTRIES` selects COM for US and other listed
countries, EU for other listed countries and unknown-country fallback. Requests
are JSON POSTs. `session.py:generate_header` supplies desktop/Android application
headers, country, a fixed session GMT offset and (after login) `x-auth-token` plus
lowercase MD5 of UTF-8 user ID as `gtoken`.

`passport/login` carries country `ab`, ephemeral uncompressed P-256 public point
hex in `client_secret_info.public_key`, `enc: 0`, email, encrypted password,
current UTC offset in milliseconds as `time_zone`, and millisecond Unix
`transaction` string. The public server point in `LoginCrypto` is the upstream
protocol constant. Raw 32-byte ECDH X output is the AES-256-CBC key; its first
16 bytes are the IV; UTF-8 password uses PKCS7 padding and base64 encoding.
No KDF is applied because this is compatibility with the upstream protocol.

Login consumes `auth_token`, `user_id` and Unix-second `token_expires_at`.
The Swift client renews before expiry and bounds HTTP 401/403 reauthentication
to one attempt. Body error codes follow `errors.py:ERRORS/raise_error`, including
verification, invalid credentials, lockout and kicked-out sessions. Terminal auth
errors propagate through the backend and require explicit recovery.
Unlike upstream disk caches, this app retains credentials and refreshed sessions
in process memory only. Login vectors use an intentionally fixed all-01 scalar
and `synthetic-password-123`; they are never real credentials.

## 2. Throttling and discovery

`apitypes.py` and `helpers.py:RequestCounter.last_minute`: global request gap
0.3 seconds, request timeout 10 seconds, throttled endpoint limit 10 attempts
inside a 62-second history window, with oldest-attempt delay to 65 seconds.
HTTP 429 marks an endpoint throttled and retries once. Busy and 502/504/timeout
retries wait a random 2–5 seconds and still pass through normal throttling.

`apibase.py:get_bind_devices` posts `{}` to
`power_service/v1/app/get_relate_and_bind_devices`. The response `data.data`
contains standalone chargers. Map `device_sn`, `product_code` (or `device_pn`),
`alias_name` and `device_name`. The app supports A2345 and rejects unsupported
models rather than interpreting them with this map.

## 3. MQTT connection

`session.py:get_user_mqtt_info` posts `{}` to
`app/devicemanage/get_user_mqtt_info`. Its user ID, application/thing name,
certificate ID, host, certificate PEM, private-key PEM and root-CA PEM configure
mutual TLS on port 8883. Validate the host against the supplied root, compose a
transient `SecIdentity`, and keep identity material off disk. The port does not
use the optional upstream `pkcs12` field.

`mqtt.py:create_client/connect_client_async` establishes MQTT 3.1.1, clean session,
60-second keepalive, QoS 0, no username/password. Subscribe to both
`dt/anker_power/A2345/<SYNTHETIC_SN>/#` and
`cmd/anker_power/A2345/<SYNTHETIC_SN>/#`. Commands publish to the latter prefix's
`req` topic. Device messages may be interleaved while waiting for SUBACK; process
them while requiring the matching control acknowledgment before connected state.

## 4. Envelope

`mqtt.py:publish` double-encodes a JSON payload string inside an outer object.
The head includes version `1.0.0.1`, client ID built from application/user/cert IDs,
`sess_id: "1234-5678"`, `msg_seq: 1`, `seed: 1`, Unix-second timestamp,
`cmd_status: 2`, `cmd: 17`, `sign_code: 1`, device model and serial.
Payload fields are device serial, account ID (owner user ID if shared, otherwise
MQTT user ID) and base64 wire frame. Incoming payload data is decoded only when
valid; heartbeat JSON, malformed data and echoed status requests do not create
port snapshots. Every command, including the port switch (section 7), uses this
envelope around its own frame. Tests use only synthetic IDs and timestamp `0x12345678`.

## 5. Hex framing

`mqtttypes.py:DeviceHexDataHeader/DeviceHexData/DeviceHexDataField`:

| Bytes | Meaning |
| --- | --- |
| `ff 09` | Prefix |
| `LL LL` | Total frame bytes, little endian, including checksum |
| `03 00 0f` | Request pattern (`03 01 0f` for reply fixtures) |
| `TT TT` | Message type: `02 00` status request, `02 07` port switch command (section 7) or `0a 00` reply |
| optional increment | Byte 9 is an increment unless it is in `a0...a9` |
| fields | ID, length, payload including type byte when present |
| checksum | XOR of all preceding bytes; whole-frame XOR is zero |

The port preserves upstream's one-byte/two-byte little-endian string/binary
length heuristic, with truncation checks. Status requests use fields
`a1 01 22` and `fe 05 03` followed by four little-endian timestamp bytes.
The independent synthetic worked example uses `0x12345678` and is pinned by
literal frame bytes and envelope output in tests.

## 6. Port data

### 6.1 A2345 reply map

`mqttmap.py:_A2345_0a00` maps `a4...a9` to C1, C2, C3, C4, A1, A2.
Each field starts with binary type `04`, then active byte (1 means active),
signed little-endian Int16 voltage in millivolts, current in milliamps and
power in centiwatts. Preserve negative wire values and idle current. Sum reported
centiwatts; do not replace reported power with voltage × current.
Missing, mistyped or short port fields cannot replace a complete snapshot.

The generated public corpus has 115 distinct 326-byte frames. It varies port
measurements and field order, with unmistakable synthetic padding. All values
are invented from constants, not captured or transformed owner readings. Separate
regressions cover sign extremes, incomplete messages, checksum/prefix/length
corruption, binary/string length forms and optional increments. See
[fixture provenance](../Tests/AnkerCloudTests/Fixtures/README.md).

### 6.2 Detail fields

Fault bits, over-temperature, identity support and per-USB-C connected-device
identity follow anker-solix-api commit `9e72894181aef868e7b3ed0ba05bd322d54bb5d7`:
[`mqttmap.py`, `_A2345_0a00`](https://github.com/thomluther/anker-solix-api/blob/9e72894181aef868e7b3ed0ba05bd322d54bb5d7/src/anker_solix_api/mqttmap.py#L3550)
keys `a3`, `b7`, `bd` and `be` define the masks, value offsets, sentinels,
identity-support meaning and brand classes. Value offsets index upstream
`DeviceHexDataField.f_value`, the payload after its type byte; `HexFrame`
retains that type byte. Consult the pinned map for the layout and for the
uncertainty markers on its fault names; this reference does not restate them.

Accepted wire types follow
[`DeviceHexDataField.extract_value`](https://github.com/thomluther/anker-solix-api/blob/9e72894181aef868e7b3ed0ba05bd322d54bb5d7/src/anker_solix_api/mqtttypes.py#L394)'s
dispatch into `BYTES` extraction, not the base-type enum: `sile`, `var` and
`bin` reach it for all four fields, `strb` for every field except `a3`, and
`ui` and all other types extract nothing. Identity words are unsigned; port
readings stay signed.

`PortDecoder` decodes each detail field independently. A missing, short or
unsupported field leaves only its own values unknown, and every present detail
payload is kept verbatim for diagnostics. Detail fields never relax the
mandatory port-reading validation. `--live-check` prints the decoded values
and raw payloads as owner-gate evidence. `synthetic_0a00_details_frames.txt`
covers identity sentinels, unknown classes, support values, mask combinations
and the type matrix, including a `sile`-encoded `a3`.

### 6.3 Port switch state

Each port's on/off switch follows the same commit,
`9e72894181aef868e7b3ed0ba05bd322d54bb5d7`:
[`mqttmap.py`, `_A2345_0a00`](https://github.com/thomluther/anker-solix-api/blob/9e72894181aef868e7b3ed0ba05bd322d54bb5d7/src/anker_solix_api/mqttmap.py#L3550)
keys `aa` through `ae`, entry `00` (`{port}_switch`), one per
`mqttcmdmap.py` `CHARGER_PORT_IDS` target. `PortSwitch` carries those targets and
indexes; A1 and A2 both resolve to the one USB-A target. The keys accept the wire
types of `b7` (section 6.2), and `PortDecoder` treats a value of 0 as off and 1 as
on. A missing, mistyped, short or other value leaves that switch undecoded, which
`ChargerDetails.switchedOn(_:)` returns as nil, never off. The raw payloads are
kept in `rawFields` and printed by `--live-check`. Rows 23 to 27 of
`synthetic_0a00_details_frames.txt` cover on, off, missing, unaccepted-type and
unrecognized-value cases.

## 7. Port switch command

Turning a port's power on or off follows anker-solix-api commit
`9e72894181aef868e7b3ed0ba05bd322d54bb5d7`. `mqttmap.py` gives A2345 message type
`"0207"` a command list of five targets, each mapped to `mqttcmdmap.py`
`CMD_USB_PORT_SWITCH`: `CMD_COMMON` (`a1` `pattern_22` and the `fe` var
timestamp) plus `a2` `set_port_switch_select`, a `ui` field holding the
`CHARGER_PORT_IDS` index (USB-C 1 to 4 are 0 to 3, the shared USB-A target is 4),
and `a3` `set_port_switch`, a `ui` field with 0 for off and 1 for on.

`CommandFrame` builds frames as `mqtt.py` `generate_mqtt_command` does with the
`mqtttypes.py` hex types: the `ff 09` header with the `03 00 0f` request pattern
and no increment, fields sorted by ID, each written as ID, length, type byte (when
present) and value, and the XOR checksum counted in the length. `StatusRequest`
and `PortSwitchCommand` both use it. A switch frame is therefore `a1 01 22`,
`a2 02 01` target, `a3 02 01` value and `fe 05 03` plus four little-endian
timestamp bytes. `CommandFrameTests` pins the builder to the function's docstring
example (with the checksum computed) and to independent synthetic vectors for
every target and value at timestamp `0x12345678`.

The envelope is the section 4 envelope, published to the `req` topic.
Publishing follows `mqtt_device.py` `_send_mqtt_command`: the command is complete
when it is written. The charger sends no reply correlated with the command, so
the app treats only a later `0a00` switch report (section 6.3) as confirmation.
Each such report carries the backend's receive position (connection and receive
sequence), and each command write returns a receipt with the position at write
completion; a report counts as evidence after a command only when it is on the
receipt's connection with a greater sequence. A reply still in transport buffers
at write completion is ordered after the receipt; the receive time and the
reported switch value bound what such a reply can confirm.

Owner evidence is in
[anker-solix-api discussion #252](https://github.com/thomluther/anker-solix-api/discussions/252):
owner captures of the Anker app's own `0207` commands for every target and value,
and owner and maintainer comments on the follow-up `0a07` and `0302` messages, on
`0a00` carrying the switch states in reply to a status request, and on when the
Anker app requests that reply. Its captures stay in the discussion; none is copied here or
into tests. A private check outside the repository encoded each of those
target/value commands with its own timestamp and matched it byte for byte.
