import test from "node:test";
import assert from "node:assert/strict";
import { crc32, readPng, writePng } from "../scripts/png.mjs";
import {
  measure,
  cellFailures,
  referenceLimits,
} from "../scripts/asset-metrics.mjs";
import { assemble } from "../scripts/assemble-sheet.mjs";
import { readFileSync } from "node:fs";

const image = (width, height) => ({
  width,
  height,
  pixels: new Uint8Array(width * height * 4),
});
function rect(im, x0, y0, w, h, rgba) {
  for (let y = y0; y < y0 + h; y++)
    for (let x = x0; x < x0 + w; x++)
      im.pixels.set(rgba, (y * im.width + x) * 4);
}

test("PNG CRC and lossless RGBA writer round trip", () => {
  assert.equal(crc32(Buffer.from("IEND")), 0xae426082);
  const src = image(3, 2);
  rect(src, 0, 0, 2, 2, [14, 100, 240, 187]);
  const decoded = readPng(writePng(src));
  assert.equal(decoded.width, 3);
  assert.equal(decoded.height, 2);
  assert.deepEqual(decoded.pixels, src.pixels);
});

test("assembler keeps distinct subjects inside aligned cells without upscaling", () => {
  const src = image(120, 60);
  rect(src, 12, 12, 12, 32, [80, 50, 70, 255]);
  rect(src, 76, 10, 12, 34, [40, 70, 80, 255]);
  const result = assemble([src], { cols: 2, rows: 1, cell: 64 });
  assert.equal(result.width, 128);
  assert.equal(result.height, 64);
  const m = measure(result, 2, 1);
  assert.ok(m.cells.every((c) => c.borderShare <= 0.005));
  assert.equal(m.cells[0].bottom, m.cells[1].bottom);
  assert.equal(m.cells[0].height, 32);
  assert.throws(
    () => assemble([src], { cols: 3, rows: 1, cell: 64 }),
    /subjects/i,
  );
});

function controlFigure() {
  const figure = image(128, 128);
  const colour = [125, 96, 112, 255];
  rect(figure, 48, 44, 32, 55, colour);
  rect(figure, 38, 99, 15, 23, colour);
  rect(figure, 75, 99, 15, 23, colour);
  for (let y = 15; y < 45; y++) {
    for (let x = 0; x < 128; x++) {
      if ((x - 64) ** 2 + (y - 30) ** 2 < 15 ** 2)
        rect(figure, x, y, 1, 1, colour);
    }
  }
  return figure;
}

test("A8 controls fail the same gates used for production", () => {
  const configs = [
    ["plane-sheet.png", 2, 2],
    ["pigeon-sheet.png", 2, 2],
    ["washer-v1.png", 1, 1],
  ];
  const refs = configs.flatMap(
    ([file, cols, rows]) =>
      measure(
        readPng(
          readFileSync(new URL("../dist/assets/" + file, import.meta.url)),
        ),
        cols,
        rows,
      ).cells,
  );
  const limits = referenceLimits(refs);
  const flat = controlFigure();
  assert.ok(cellFailures(measure(flat, 1, 1).cells[0], limits).includes("A7"));
  const gradient = controlFigure();
  for (let y = 0; y < 128; y++)
    for (let x = 0; x < 128; x++) {
      const k = (y * 128 + x) * 4;
      if (gradient.pixels[k + 3])
        gradient.pixels.set([100 + y, 85 + y, 70 + y, 255], k);
    }
  assert.ok(
    cellFailures(measure(gradient, 1, 1).cells[0], limits).includes("A7"),
  );
  const opaque = controlFigure();
  for (let i = 0; i < 128 * 128; i++)
    if (!opaque.pixels[i * 4 + 3])
      opaque.pixels.set([220, 220, 220, 255], i * 4);
  assert.ok(
    cellFailures(measure(opaque, 1, 1).cells[0], limits).includes("A3"),
  );
  const halo = controlFigure();
  for (let y = 3; y < 125; y++)
    for (let x = 3; x < 125; x++) {
      const k = (y * 128 + x) * 4;
      if (flat.pixels[k + 3]) continue;
      let close = false;
      for (let dy = -3; dy <= 3 && !close; dy++)
        for (let dx = -3; dx <= 3; dx++)
          if (flat.pixels[((y + dy) * 128 + x + dx) * 4 + 3]) {
            close = true;
            break;
          }
      if (close) halo.pixels.set([255, 255, 255, 128], k);
    }
  assert.ok(cellFailures(measure(halo, 1, 1).cells[0], limits).includes("A4"));
  for (const colour of [
    [0, 255, 0, 255],
    [255, 128, 0, 255],
  ]) {
    const candidate = controlFigure();
    for (let i = 0; i < 128 * 128; i++)
      if (candidate.pixels[i * 4 + 3]) candidate.pixels.set(colour, i * 4);
    assert.ok(
      cellFailures(measure(candidate, 1, 1).cells[0], limits).includes("A6"),
    );
  }
});

test("A8 reference metrics satisfy applicable A3 A4 A6 A7 gates", () => {
  const configs = [
    ["plane-sheet.png", 2, 2],
    ["pigeon-sheet.png", 2, 2],
    ["washer-v1.png", 1, 1],
  ];
  const refs = configs.map(([f, c, r]) =>
    measure(
      readPng(readFileSync(new URL("../dist/assets/" + f, import.meta.url))),
      c,
      r,
    ),
  );
  const limits = referenceLimits(refs.flatMap((ref) => ref.cells));
  for (const [i, ref] of refs.entries())
    for (const c of ref.cells) {
      assert.deepEqual(
        cellFailures(c, limits, { multi: ref.cells.length > 1 }),
        [],
        configs[i][0],
      );
    }
});

test("preview reserves full natural-width tiles at both scales", async () => {
  const { preview } = await import("../scripts/asset-metrics.mjs");
  const src = image(100, 100);
  rect(src, 10, 10, 80, 80, [70, 80, 90, 255]);
  const out = preview(src, 1, 1, 28);
  // At 2× the washer alone is 384×256, and all four tiles need margins.
  assert.ok(
    out.width >= Math.ceil(384 + 2 * 28 * 3.2 + 2 * 16 * 3.2 + 2 * 20 * 3.2),
  );
  assert.ok(out.height >= 4 * 256);
  for (let y = 0; y < out.height; y++) {
    const k = (y * out.width + out.width - 1) * 4;
    const park = y >= out.height / 2;
    assert.deepEqual(
      [...out.pixels.subarray(k, k + 3)],
      park ? [125, 136, 125] : [155, 140, 187],
    );
  }
});

test("PNG reader reverses all five filters and RGB expands alpha", async () => {
  const { deflateSync } = await import("node:zlib");
  function chunk(name, data) {
    const type = Buffer.from(name),
      out = Buffer.alloc(data.length + 12);
    out.writeUInt32BE(data.length);
    type.copy(out, 4);
    data.copy(out, 8);
    out.writeUInt32BE(crc32(out.subarray(4, 8 + data.length)), 8 + data.length);
    return out;
  }
  const width = 3,
    height = 5,
    channels = 3,
    raw = Buffer.alloc((width * channels + 1) * height),
    samples = Uint8Array.from(
      { length: width * height * channels },
      (_, i) => (i * 37 + 7) & 255,
    );
  const paeth = (a, b, c) => {
    const p = a + b - c,
      pa = Math.abs(p - a),
      pb = Math.abs(p - b),
      pc = Math.abs(p - c);
    return pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
  };
  for (let y = 0; y < height; y++) {
    raw[y * 10] = y;
    for (let x = 0; x < 9; x++) {
      const a = x >= 3 ? samples[y * 9 + x - 3] : 0,
        b = y ? samples[(y - 1) * 9 + x] : 0,
        c = y && x >= 3 ? samples[(y - 1) * 9 + x - 3] : 0;
      raw[y * 10 + 1 + x] =
        (samples[y * 9 + x] -
          [0, a, b, Math.floor((a + b) / 2), paeth(a, b, c)][y]) &
        255;
    }
  }
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width);
  header.writeUInt32BE(height, 4);
  header[8] = 8;
  header[9] = 2;
  const bytes = Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(raw)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
  const decoded = readPng(bytes);
  for (let i = 0; i < width * height; i++)
    assert.deepEqual(
      [...decoded.pixels.subarray(i * 4, i * 4 + 4)],
      [...samples.subarray(i * 3, i * 3 + 3), 255],
    );
  const damaged = Buffer.from(bytes);
  damaged[20] ^= 1;
  assert.throws(() => readPng(damaged), /CRC/);
});

test("renderer selects rectangular grid source cells from decoded images", async () => {
  const { Renderer } = await import("../dist/game/render.js");
  const draws = [],
    ctx = new Proxy(
      { drawImage: (...a) => draws.push(a) },
      { get: (o, k) => (k in o ? o[k] : () => {}) },
    ),
    im = { complete: true, naturalWidth: 900, naturalHeight: 400 };
  const renderer = Object.assign(Object.create(Renderer.prototype), { ctx });
  renderer.sprite(im, 5, 10, 20, 60, 40, 0, 3, 2);
  assert.deepEqual(draws[0].slice(1, 5), [600, 200, 300, 200]);
});

test("assembler joins a nearby detached detail", () => {
  const source = image(100, 100);
  rect(source, 20, 35, 20, 20, [100, 90, 80, 255]);
  rect(source, 42, 42, 5, 5, [100, 90, 80, 255]);
  assert.doesNotThrow(() => assemble([source], { cols: 1, rows: 1, cell: 64 }));
});

test("assembler centres asymmetric content without clipping", () => {
  const asymmetric = image(100, 100);
  rect(asymmetric, 10, 20, 20, 31, [100, 90, 80, 255]);
  rect(asymmetric, 30, 20, 60, 2, [100, 90, 80, 255]);
  const result = assemble([asymmetric, asymmetric], {
    cols: 2,
    rows: 1,
    cell: 64,
  });
  for (const c of measure(result, 2, 1).cells)
    assert.ok(Math.abs(c.centroid - 32) <= 2.56, `centroid ${c.centroid}`);
});

test("A6 reports the specific vivid-colour rule that rejected each control", () => {
  const limits = {
    vivid: 0.17,
    minSaturation: 0,
    maxSaturation: 1,
    texture: 0,
  };
  for (const [colour, rule] of [
    [[0, 255, 0, 255], "A6-hue"],
    [[255, 128, 0, 255], "A6-vivid"],
  ]) {
    const figure = controlFigure();
    for (let i = 0; i < figure.width * figure.height; i++)
      if (figure.pixels[i * 4 + 3]) figure.pixels.set(colour, i * 4);
    assert.ok(
      cellFailures(measure(figure, 1, 1).cells[0], limits).includes(rule),
    );
  }
});

test("assembler does not join distinct bodies through speck chains", () => {
  const src = image(200, 80);
  rect(src, 20, 20, 25, 30, [100, 90, 80, 255]);
  rect(src, 90, 20, 25, 30, [100, 90, 80, 255]);
  for (let x = 49; x < 90; x += 4) rect(src, x, 30, 1, 1, [100, 90, 80, 255]);
  assert.doesNotThrow(() => assemble([src], { cols: 2, rows: 1, cell: 64 }));
  assert.throws(
    () => assemble([src], { cols: 1, rows: 1, cell: 64 }),
    /subjects/,
  );
});

test("assembler joins substantial details within three percent", () => {
  const src = image(100, 100);
  rect(src, 20, 35, 20, 20, [80, 90, 100, 255]);
  rect(src, 42, 39, 12, 12, [80, 90, 100, 255]);
  assert.doesNotThrow(() => assemble([src], { cols: 1, rows: 1, cell: 64 }));
});

test("assembler preserves thin asymmetric detail while centering resampled alpha", () => {
  const src = image(100, 100);
  rect(src, 10, 10, 10, 30, [80, 90, 100, 255]);
  rect(src, 20, 10, 80, 1, [80, 90, 100, 255]);
  const result = assemble([src, src], { cols: 2, rows: 1, cell: 64 });
  for (const [i, c] of measure(result, 2, 1).cells.entries()) {
    assert.ok(Math.abs(c.centroid - 32) <= 2.56, `centroid ${c.centroid}`);
    let left = 64,
      right = -1,
      top = 64,
      bottom = -1;
    for (let y = 0; y < 64; y++)
      for (let x = 0; x < 64; x++)
        if (result.pixels[(y * result.width + i * 64 + x) * 4 + 3] > 8) {
          left = Math.min(left, x);
          right = Math.max(right, x);
          top = Math.min(top, y);
          bottom = Math.max(bottom, y);
        }
    assert.ok(
      left >= 6 && right < 59 && top >= 6 && bottom < 59,
      `content outside 8% gutter: ${left},${right},${top},${bottom}`,
    );
    assert.ok(right - left > 20, "thin bar survived downscaling");
  }
});

test('transparent pixels from one subject cannot erase its neighbor', () => {
  const full=image(100,40),delicate=image(100,40);
  rect(full,0,0,100,40,[80,90,100,255]);
  rect(delicate,95,0,5,40,[80,90,100,255]);
  rect(delicate,0,0,95,1,[80,90,100,9]);
  const baseline=assemble([full,full],{cols:2,rows:1,cell:64});
  const mixed=assemble([full,delicate],{cols:2,rows:1,cell:64});
  for(let y=0;y<64;y++)for(let x=0;x<64;x++){
    const k=(y*baseline.width+x)*4;
    assert.deepEqual([...mixed.pixels.subarray(k,k+4)],[...baseline.pixels.subarray(k,k+4)],`neighbor pixel ${x},${y}`);
  }
});

test('metrics and preview reject invalid grids before producing output',async()=>{
  const {preview}=await import('../scripts/asset-metrics.mjs');
  const {spawnSync}=await import('node:child_process');
  const {mkdtempSync,readdirSync,rmSync}=await import('node:fs');
  const {tmpdir}=await import('node:os');
  const {join}=await import('node:path');
  const src=image(12,12);
  for(const [cols,rows] of [[0,1],[-1,1],[1.5,1],[Infinity,1],[NaN,1],[1,0],[1,-1],[1,1.5],[1,Infinity],[1,NaN]]){
    assert.throws(()=>measure(src,cols,rows),/positive integers/);
    assert.throws(()=>preview(src,cols,rows,28),/positive integers/);
  }
  assert.throws(()=>preview(src,1,1,0),/metres.*positive/i);
  assert.throws(()=>preview(src,1,1,NaN),/metres.*positive/i);
  const dir=mkdtempSync(join(tmpdir(),'office-picnic-cli-test-'));
  try {
    const script=new URL('../scripts/asset-metrics.mjs',import.meta.url).pathname;
    const file=new URL('../dist/assets/pickup-token.png',import.meta.url).pathname;
    for(const args of [[file,'--cols','0'],['--preview',file,'--cols','0'],['--preview',file,'--metres','0']]){
      const result=spawnSync(process.execPath,[script,...args],{encoding:'utf8',env:{...process.env,TMPDIR:dir}});
      assert.notEqual(result.status,0);assert.match(result.stderr,/positive/i);assert.deepEqual(readdirSync(dir),[]);
    }
  } finally {rmSync(dir,{recursive:true,force:true});}
});
