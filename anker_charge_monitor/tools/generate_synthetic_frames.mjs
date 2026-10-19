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
