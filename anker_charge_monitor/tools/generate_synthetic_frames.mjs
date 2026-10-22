#!/usr/bin/env node
// Invented protocol corpus: no input captures, private configuration or network.
import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const littleEndian = value => [value & 255, (value >> 8) & 255];
const rows = [];
for (let row = 0; row < 115; row++) {
  // C1/C2 retain invented idle current; C3/C4 vary independently of V×A.
  const ports = [
    [0xa4, 0, 0, 7, 0], [0xa5, 0, 0, 7, 0],
    [0xa6, 1, 12345, 321 + row, 123 + row],
    [0xa7, 1, 23456, 654 + row, 456 + row],
    [0xa8, 0, 0, 0, 0], [0xa9, 0, 0, 0, 0],
  ];
  if (row % 2) ports.reverse();
  const fields = ports.flatMap(([id, active, volts, amps, watts]) =>
    [id, 8, 4, active, ...littleEndian(volts), ...littleEndian(amps), ...littleEndian(watts)]);
  // Unknown binary TLV retains the original long-frame/length coverage while
  // making its invented provenance conspicuous even in a raw wire dump.
  const label = Buffer.from(`SYNTHETIC-NOT-A-DEVICE-ROW-${row}-`);
  const padding = Array.from({ length: 252 }, (_, index) => label[index % label.length]);
  const frame = [0xff, 9, 0x46, 1, 3, 1, 15, 10, 0, 0,
    ...fields, 0xc0, 253, 4, ...padding];
  frame.push(frame.reduce((checksum, byte) => checksum ^ byte, 0));
  if (frame.length !== 326) throw new Error('Synthetic frame length changed');
  rows.push(Buffer.from(frame).toString('hex'));
}
const destination = fileURLToPath(new URL('../Tests/AnkerCloudTests/Fixtures/synthetic_0a00_frames.txt', import.meta.url));
writeFileSync(destination, `${rows.join('\n')}\n`);

// Detail fields a3/b7/bd/be (anker-solix-api 9e72894, mqttmap.py _A2345_0a00).
// Every vendor/product ID, class and code is invented (FEED, BEEF, C0DE).
const BIN = 0x04;
const words = values => values.flatMap(littleEndian);
const field = (id, type, value) => [id, 1 + value.length, type, ...value];
const faults = (type, low, high = 0) => field(0xa3, type, [low, high]);
const support = (type, value) => field(0xb7, type, [0xff, value]);
const ids = (type, pairs) => field(0xbd, type, words(pairs.flat()));
const metadata = (type, pairs) => field(0xbe, type, words(pairs.flat()));
const NONE = [0xfffa, 0xfffb], PENDING = [0, 0], ABSENT = [0xffff, 0xffff];
const mixedIDs = [NONE, PENDING, [0xfeed, 0xbeef], [0xc0de, 0x0042]];
const mixedMetadata = [ABSENT, ABSENT, [10, 7], [99, 0x0101]];
const fourIDs = [[0xfeed, 0xbeef], [0xc0de, 0x0042], [0xfeed, 0x0001], [0xfeed, 0x0002]];
const identityFields = type => [support(type, 6), ids(type, mixedIDs), metadata(type, mixedMetadata)];
const detailRows = [
  [faults(BIN, 0x00), ...identityFields(BIN)],                       // 0 baseline
  [faults(BIN, 0x01), support(BIN, 2), ids(BIN, [NONE, NONE, NONE, NONE]),
    metadata(BIN, [ABSENT, ABSENT, ABSENT, ABSENT])],                // 1 unsupported, over-temperature
  [faults(0x02, 0x3f), ...identityFields(BIN)],                      // 2 sile fault field, every bit
  [faults(0x03, 0x0a), ...identityFields(BIN)],                      // 3 var: C1 + C3
  [faults(BIN, 0x14), ...identityFields(BIN)],                       // 4 C2 + C4
  [faults(BIN, 0x20, 0xff), ...identityFields(BIN)],                 // 5 USB-A, high byte ignored
  [faults(BIN, 0xc0), ...identityFields(BIN)],                       // 6 unmapped bits only
  // 7-15: one wire type for all four detail fields, with a C3 fault.
  ...[0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0xfe, 0xff]
    .map(type => [faults(type, 0x08), ...identityFields(type)]),
  [faults(BIN, 0), ids(BIN, mixedIDs), metadata(BIN, mixedMetadata)], // 16 missing support
  [faults(BIN, 0), support(BIN, 6), field(0xbd, BIN, words([0xfeed, 0xbeef, 0xc0de])),
    metadata(BIN, [[10, 7], [99, 0x0101], ABSENT, ABSENT])],         // 17 short bd
  [support(BIN, 6), ids(BIN, fourIDs), field(0xbe, BIN, words([10, 7, 99, 0x0101, 5]))], // 18 short be
  [[0xa3, 1, BIN], [0xb7, 2, BIN, 0xff], ids(BIN, fourIDs), [0xbe, 1, BIN]], // 19 missing values
  [faults(BIN, 0), support(BIN, 6), ids(BIN, fourIDs), metadata(0x01, mixedMetadata)], // 20 be type ui
  [faults(BIN, 0), support(BIN, 6), ids(BIN, fourIDs),
    metadata(BIN, [[0xffff, 7], [10, 0xffff], [19, 0], [0x1234, 0]])], // 21 independent metadata
  [support(BIN, 2)],                                                 // 22 support only
];
const detailFrames = detailRows.map((details, row) => {
  // Row zero's readings from the corpus above, for parity with detail-free frames.
  const ports = [
    [0xa4, 0, 0, 7, 0], [0xa5, 0, 0, 7, 0], [0xa6, 1, 12345, 321, 123],
    [0xa7, 1, 23456, 654, 456], [0xa8, 0, 0, 0, 0], [0xa9, 0, 0, 0, 0],
  ].map(([id, active, volts, amps, watts]) =>
    [id, 8, 4, active, ...littleEndian(volts), ...littleEndian(amps), ...littleEndian(watts)]);
  const fields = [...ports, ...details];
  // Odd rows reverse wire field order; decoding must not depend on it.
  if (row % 2) fields.reverse();
  const label = Buffer.from(`SYNTHETIC-NOT-A-DEVICE-DETAILS-ROW-${row}-`);
  const padding = Array.from({ length: 48 }, (_, index) => label[index % label.length]);
  const frame = [0xff, 9, 0, 0, 3, 1, 15, 10, 0, 0, ...fields.flat(), 0xc0, 49, 4, ...padding];
  frame[2] = (frame.length + 1) & 255;
  frame[3] = (frame.length + 1) >> 8;
  frame.push(frame.reduce((checksum, byte) => checksum ^ byte, 0));
  return Buffer.from(frame).toString('hex');
});
writeFileSync(fileURLToPath(new URL('../Tests/AnkerCloudTests/Fixtures/synthetic_0a00_details_frames.txt', import.meta.url)),
  `${detailFrames.join('\n')}\n`);
