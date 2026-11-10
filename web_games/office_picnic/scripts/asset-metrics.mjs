import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { readPng, writePng } from "./png.mjs";
const root = new URL("../dist/assets/", import.meta.url);
const refs = [
  { file: "plane-sheet.png", cols: 2, rows: 2, metres: 16 },
  { file: "pigeon-sheet.png", cols: 2, rows: 2, metres: 20 },
  { file: "washer-v1.png", cols: 1, rows: 1, metres: 40 },
];
const lum = (r, g, b) => (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
const sat = (r, g, b) => {
  const max = Math.max(r, g, b),
    min = Math.min(r, g, b);
  return max ? (max - min) / max : 0;
};
export function resize(im, w, h) {
  const out = { width: w, height: h, pixels: new Uint8Array(w * h * 4) };
  for (let y = 0; y < h; y++)
    for (let x = 0; x < w; x++) {
      const x0 = (x * im.width) / w,
        x1 = ((x + 1) * im.width) / w,
        y0 = (y * im.height) / h,
        y1 = ((y + 1) * im.height) / h;
      let a = 0,
        r = 0,
        g = 0,
        b = 0,
        area = 0;
      for (let sy = Math.floor(y0); sy < Math.ceil(y1); sy++)
        for (let sx = Math.floor(x0); sx < Math.ceil(x1); sx++) {
          const weight =
              (Math.min(x1, sx + 1) - Math.max(x0, sx)) *
              (Math.min(y1, sy + 1) - Math.max(y0, sy)),
            k = (sy * im.width + sx) * 4,
            alpha = im.pixels[k + 3] / 255;
          a += alpha * weight;
          r += im.pixels[k] * alpha * weight;
          g += im.pixels[k + 1] * alpha * weight;
          b += im.pixels[k + 2] * alpha * weight;
          area += weight;
        }
      const k = (y * w + x) * 4;
      if (a) {
        out.pixels[k] = Math.round(r / a);
        out.pixels[k + 1] = Math.round(g / a);
        out.pixels[k + 2] = Math.round(b / a);
      }
      out.pixels[k + 3] = Math.round((255 * a) / area);
    }
  return out;
}
export function texture(im) {
  let x0 = im.width,
    y0 = im.height,
    x1 = -1,
    y1 = -1;
  for (let y = 0; y < im.height; y++)
    for (let x = 0; x < im.width; x++)
      if (im.pixels[(y * im.width + x) * 4 + 3] > 8) {
        x0 = Math.min(x0, x);
        x1 = Math.max(x1, x);
        y0 = Math.min(y0, y);
        y1 = Math.max(y1, y);
      }
  if (x1 < 0) return 0;
  const bw = x1 - x0 + 1,
    bh = y1 - y0 + 1,
    crop = { width: bw, height: bh, pixels: new Uint8Array(bw * bh * 4) };
  for (let y = 0; y < bh; y++)
    crop.pixels.set(
      im.pixels.subarray(
        ((y + y0) * im.width + x0) * 4,
        ((y + y0) * im.width + x1 + 1) * 4,
      ),
      y * bw * 4,
    );
  const scale = 96 / Math.max(bw, bh),
    scaled = resize(
      crop,
      Math.max(1, Math.round(bw * scale)),
      Math.max(1, Math.round(bh * scale)),
    ),
    p = scaled.pixels,
    values = [],
    w = scaled.width,
    h = scaled.height;
  for (let y = 2; y < h - 2; y++)
    for (let x = 2; x < w - 2; x++) {
      let ok = true,
        sum = 0,
        sum2 = 0;
      for (let dy = -2; dy <= 2 && ok; dy++)
        for (let dx = -2; dx <= 2; dx++) {
          const k = ((y + dy) * w + x + dx) * 4;
          if (p[k + 3] < 248) {
            ok = false;
            break;
          }
          const v = lum(p[k], p[k + 1], p[k + 2]);
          sum += v;
          sum2 += v * v;
        }
      if (ok) values.push(Math.sqrt(Math.max(0, sum2 / 25 - (sum / 25) ** 2)));
    }
  values.sort((a, b) => a - b);
  return values.length ? values[Math.floor(values.length / 2)] : 0;
}
export function transparency(c, multi) {
  return (
    c.corners.every((a) => a <= 8) &&
    c.clearShare >= 0.3 &&
    (!multi || c.borderShare <= 0.005)
  );
}
export function referenceLimits(cells) {
  return {
    vivid: Math.max(...cells.map((cell) => cell.neonShare)) * 1.5,
    minSaturation: Math.min(...cells.map((cell) => cell.meanSaturation)) - 0.1,
    maxSaturation: Math.max(...cells.map((cell) => cell.meanSaturation)) + 0.1,
    texture: Math.min(...cells.map((cell) => cell.texture)) * 0.5,
  };
}
export function cellFailures(
  cell,
  limits,
  { multi = false, cutout = true } = {},
) {
  const failures = [];
  if (cutout && !transparency(cell, multi)) failures.push("A3");
  if (cell.matteShare > 0.02) failures.push("A4");
  const paletteFailures = [];
  if (cell.foreignVividShare > 0.02) paletteFailures.push("A6-hue");
  if (cell.neonShare > limits.vivid) paletteFailures.push("A6-vivid");
  if (cell.blackShare > 0.03) paletteFailures.push("A6-black");
  if (
    cell.meanSaturation < limits.minSaturation ||
    cell.meanSaturation > limits.maxSaturation
  )
    paletteFailures.push("A6-saturation");
  if (paletteFailures.length) failures.push("A6", ...paletteFailures);
  if (cell.texture < limits.texture) failures.push("A7");
  return failures;
}
export function measure(im, cols, rows, metres = 28) {
  if (im.width % cols || im.height % rows)
    throw new Error("Image dimensions do not divide evenly by grid");
  const cw = im.width / cols,
    ch = im.height / rows,
    cells = [];
  for (let row = 0; row < rows; row++)
    for (let col = 0; col < cols; col++) {
      const px = new Uint8Array(cw * ch * 4);
      let clear = 0,
        border = 0,
        bad = 0,
        edge = 0,
        matte = 0,
        opaque = 0,
        neon = 0,
        foreign = 0,
        black = 0,
        saturation = 0,
        minx = cw,
        miny = ch,
        maxx = -1,
        maxy = -1,
        weight = 0,
        sumx = 0;
      for (let y = 0; y < ch; y++)
        for (let x = 0; x < cw; x++) {
          const k = ((row * ch + y) * im.width + col * cw + x) * 4,
            d = (y * cw + x) * 4,
            [r, g, b, a] = im.pixels.subarray(k, k + 4);
          px.set(im.pixels.subarray(k, k + 4), d);
          if (a <= 8) clear++;
          else {
            minx = Math.min(minx, x);
            maxx = Math.max(maxx, x);
            miny = Math.min(miny, y);
            maxy = Math.max(maxy, y);
            weight += a;
            sumx += x * a;
          }
          if (
            x < cw * 0.04 ||
            x >= cw - cw * 0.04 ||
            y < ch * 0.04 ||
            y >= ch - ch * 0.04
          ) {
            border++;
            if (a > 8) bad++;
          }
          const s = sat(r, g, b),
            v = Math.max(r, g, b) / 255;
          if (a > 8 && a < 248) {
            edge++;
            if (s < 0.1 && v > 0.9) matte++;
          }
          if (a >= 248) {
            opaque++;
            saturation += s;
            if (s > 0.85 && v > 0.8) {
              neon++;
              const max = Math.max(r, g, b),
                min = Math.min(r, g, b),
                delta = max - min;
              let hue =
                max === r
                  ? 60 * (((g - b) / delta) % 6)
                  : max === g
                    ? 60 * ((b - r) / delta + 2)
                    : 60 * ((r - g) / delta + 4);
              if (hue < 0) hue += 360;
              if (hue < 10 || hue > 65) foreign++;
            }
            if (lum(r, g, b) < 0.06) black++;
          }
        }
      const corners = [
        px[3],
        px[(cw - 1) * 4 + 3],
        px[(ch - 1) * cw * 4 + 3],
        px[(ch * cw - 1) * 4 + 3],
      ];
      cells.push({
        corners,
        clearShare: clear / (cw * ch),
        borderShare: bad / border,
        matteShare: edge ? matte / edge : 0,
        neonShare: opaque ? neon / opaque : 0,
        foreignVividShare: opaque ? foreign / opaque : 0,
        blackShare: opaque ? black / opaque : 0,
        meanSaturation: opaque ? saturation / opaque : 0,
        height: maxy - miny + 1,
        bottom: maxy,
        centroid: weight ? sumx / weight : 0,
        texture: texture({ width: cw, height: ch, pixels: px }),
      });
    }
  return {
    width: im.width,
    height: im.height,
    cellWidth: cw,
    cellHeight: ch,
    cells,
  };
}
export function preview(im, cols, rows, metres) {
  const palette = JSON.parse(readFileSync(new URL("palette.json", root)));
  const colors = [palette.sampled.sky, palette.derived.park].map((s) =>
    [1, 3, 5].map((i) => parseInt(s.slice(i, i + 2), 16)),
  );
  const items = [];
  for (let i = 0; i < cols * rows; i++)
    items.push({
      im,
      col: i % cols,
      row: Math.floor(i / cols),
      cols,
      rows,
      metres,
    });
  for (const r of refs)
    items.push({
      ...r,
      im: readPng(readFileSync(new URL(r.file, root))),
      col: 0,
      row: 0,
    });
  const margin = 16,
    tileHeight =
      Math.ceil(Math.max(...items.map((item) => item.metres * 3.2 * 2))) +
      margin * 2;
  const widths = items.map(
    (item) =>
      Math.ceil(
        (item.metres * 3.2 * 2 * (item.im.width / item.cols)) /
          (item.im.height / item.rows),
      ) +
      margin * 2,
  );
  const width = widths.reduce((a, b) => a + b, 0),
    height = tileHeight * 4,
    pixels = new Uint8Array(width * height * 4);
  for (let band = 0; band < 4; band++) {
    const bg = colors[Math.floor(band / 2)],
      factor = band % 2 ? 1 : 2;
    for (let y = band * tileHeight; y < (band + 1) * tileHeight; y++)
      for (let x = 0; x < width; x++)
        pixels.set([...bg, 255], (y * width + x) * 4);
    let left = 0;
    items.forEach((item, i) => {
      const sw = item.im.width / item.cols,
        sh = item.im.height / item.rows,
        sub = { width: sw, height: sh, pixels: new Uint8Array(sw * sh * 4) };
      for (let y = 0; y < sh; y++)
        sub.pixels.set(
          item.im.pixels.subarray(
            ((item.row * sh + y) * item.im.width + item.col * sw) * 4,
            ((item.row * sh + y) * item.im.width + (item.col + 1) * sw) * 4,
          ),
          y * sw * 4,
        );
      const dh = Math.round(item.metres * 3.2 * factor),
        dw = Math.max(1, Math.round((dh * sw) / sh)),
        small = resize(sub, dw, dh),
        ox = left + Math.floor((widths[i] - dw) / 2),
        oy = band * tileHeight + Math.floor((tileHeight - dh) / 2);
      for (let y = 0; y < dh; y++)
        for (let x = 0; x < dw; x++) {
          const k = (y * dw + x) * 4,
            d = ((oy + y) * width + ox + x) * 4,
            a = small.pixels[k + 3] / 255;
          for (let c = 0; c < 3; c++)
            pixels[d + c] = Math.round(
              small.pixels[k + c] * a + pixels[d + c] * (1 - a),
            );
        }
      left += widths[i];
    });
  }
  return { width, height, pixels };
}
if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  try {
    const args = process.argv.slice(2),
      options = { cols: 1, rows: 1, metres: 28 };
    let file,
      makePreview = false;
    for (let i = 0; i < args.length; i++) {
      const a = args[i];
      if (a === "--preview") {
        makePreview = true;
        file = args[++i];
      } else if (["--cols", "--rows", "--metres"].includes(a))
        options[a.slice(2)] = Number(args[++i]);
      else file = a;
    }
    if (makePreview) {
      if (!file) throw new Error("Missing preview file");
      const dir = mkdtempSync(join(tmpdir(), "office-picnic-preview-")),
        out = join(dir, "preview.png");
      writeFileSync(
        out,
        writePng(
          preview(
            readPng(readFileSync(file)),
            options.cols,
            options.rows,
            options.metres,
          ),
        ),
      );
      console.log(out);
    } else {
      let entries = refs.map((r) => ({ ...r, path: new URL(r.file, root) }));
      if (file) entries.push({ ...options, file, path: file });
      else {
        const manifest = JSON.parse(
          readFileSync(new URL("manifest.json", root)),
        );
        entries.push(
          ...Object.values(manifest).map((a) => ({
            ...a,
            path: new URL(a.file, root),
          })),
        );
      }
      for (const e of entries) {
        const m = measure(
          readPng(readFileSync(e.path)),
          e.cols,
          e.rows,
          e.metres,
        );
        console.log(
          e.file.padEnd(22),
          m.width + "×" + m.height,
          "clear=" +
            m.cells.map((c) => (c.clearShare * 100).toFixed(1)).join("/") +
            "%",
          "border=" +
            m.cells.map((c) => (c.borderShare * 100).toFixed(2)).join("/") +
            "%",
          "matte=" +
            m.cells.map((c) => (c.matteShare * 100).toFixed(2)).join("/") +
            "%",
          "vivid=" +
            m.cells.map((c) => (c.neonShare * 100).toFixed(2)).join("/") +
            "%",
          "foreign=" +
            m.cells
              .map((c) => (c.foreignVividShare * 100).toFixed(2))
              .join("/") +
            "%",
          "black=" +
            m.cells.map((c) => (c.blackShare * 100).toFixed(2)).join("/") +
            "%",
          "sat=" + m.cells.map((c) => c.meanSaturation.toFixed(3)).join("/"),
          "texture=" + m.cells.map((c) => c.texture.toFixed(4)).join("/"),
          "height=" + m.cells.map((c) => c.height).join("/"),
          "bottom=" + m.cells.map((c) => c.bottom).join("/"),
          "centroid=" + m.cells.map((c) => c.centroid.toFixed(1)).join("/"),
        );
      }
    }
  } catch (e) {
    console.error(e.message);
    process.exitCode = 1;
  }
}
