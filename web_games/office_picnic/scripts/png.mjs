import { deflateSync, inflateSync } from "node:zlib";

const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
const table = Uint32Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let i = 0; i < 8; i++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});
export function crc32(data) {
  let c = 0xffffffff;
  for (const b of data) c = table[(c ^ b) & 255] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}
function chunk(type, data = Buffer.alloc(0)) {
  const name = Buffer.from(type),
    buf = Buffer.alloc(data.length + 12);
  buf.writeUInt32BE(data.length, 0);
  name.copy(buf, 4);
  data.copy(buf, 8);
  buf.writeUInt32BE(crc32(buf.subarray(4, 8 + data.length)), 8 + data.length);
  return buf;
}
export function writePng({ width, height, pixels }) {
  if (
    !Number.isInteger(width) ||
    !Number.isInteger(height) ||
    width < 1 ||
    height < 1 ||
    pixels.length !== width * height * 4
  )
    throw new Error("Invalid RGBA image");
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header[8] = 8;
  header[9] = 6;
  const raw = Buffer.alloc((width * 4 + 1) * height);
  for (let y = 0; y < height; y++)
    Buffer.from(
      pixels.buffer,
      pixels.byteOffset + y * width * 4,
      width * 4,
    ).copy(raw, y * (width * 4 + 1) + 1);
  return Buffer.concat([
    signature,
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(raw)),
    chunk("IEND"),
  ]);
}
export function readPng(input) {
  const b = Buffer.from(input);
  if (!b.subarray(0, 8).equals(signature))
    throw new Error("Invalid PNG signature");
  let pos = 8,
    width,
    height,
    channels,
    parts = [],
    ended = false;
  while (pos + 12 <= b.length) {
    const n = b.readUInt32BE(pos),
      end = pos + 12 + n;
    if (end > b.length) throw new Error("Truncated PNG chunk");
    const type = b.toString("ascii", pos + 4, pos + 8),
      data = b.subarray(pos + 8, pos + 8 + n);
    if (crc32(b.subarray(pos + 4, pos + 8 + n)) !== b.readUInt32BE(pos + 8 + n))
      throw new Error("PNG CRC mismatch");
    if (type === "IHDR") {
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
      if (
        data[8] !== 8 ||
        ![2, 6].includes(data[9]) ||
        data[10] ||
        data[11] ||
        data[12]
      )
        throw new Error("Only 8-bit non-interlaced RGB or RGBA PNG supported");
      channels = data[9] === 6 ? 4 : 3;
    }
    if (type === "IDAT") parts.push(data);
    if (type === "IEND") {
      ended = true;
      break;
    }
    pos = end;
  }
  if (!width || !height || !ended || !parts.length)
    throw new Error("Incomplete PNG");
  const raw = inflateSync(Buffer.concat(parts)),
    stride = width * channels;
  if (raw.length !== (stride + 1) * height)
    throw new Error("Invalid PNG scanline length");
  const decoded = Buffer.alloc(stride * height);
  const paeth = (a, b, c) => {
    const p = a + b - c,
      pa = Math.abs(p - a),
      pb = Math.abs(p - b),
      pc = Math.abs(p - c);
    return pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
  };
  for (let y = 0; y < height; y++) {
    const filter = raw[y * (stride + 1)];
    if (filter > 4) throw new Error("Invalid PNG filter");
    for (let x = 0; x < stride; x++) {
      const a = x >= channels ? decoded[y * stride + x - channels] : 0,
        up = y ? decoded[(y - 1) * stride + x] : 0,
        c = y && x >= channels ? decoded[(y - 1) * stride + x - channels] : 0;
      const predictor = [0, a, up, Math.floor((a + up) / 2), paeth(a, up, c)][
        filter
      ];
      decoded[y * stride + x] =
        (raw[y * (stride + 1) + 1 + x] + predictor) & 255;
    }
  }
  const pixels = new Uint8Array(width * height * 4);
  for (let i = 0; i < width * height; i++) {
    pixels.set(decoded.subarray(i * channels, i * channels + 3), i * 4);
    pixels[i * 4 + 3] = channels === 4 ? decoded[i * channels + 3] : 255;
  }
  return { width, height, pixels };
}
