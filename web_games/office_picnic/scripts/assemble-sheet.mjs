import { readFileSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { readPng, writePng } from "./png.mjs";

function components(im) {
  const { width: w, height: h, pixels: p } = im,
    labels = new Int32Array(w * h),
    queue = new Int32Array(w * h),
    regions = [];
  for (let i = 0; i < w * h; i++) {
    if (labels[i] || p[i * 4 + 3] <= 8) continue;
    const id = regions.length + 1;
    let head = 0,
      tail = 0;
    queue[tail++] = i;
    labels[i] = id;
    let x0 = w,
      y0 = h,
      x1 = 0,
      y1 = 0;
    while (head < tail) {
      const n = queue[head++],
        x = n % w,
        y = Math.floor(n / w);
      x0 = Math.min(x0, x);
      x1 = Math.max(x1, x);
      y0 = Math.min(y0, y);
      y1 = Math.max(y1, y);
      for (let dy = -1; dy <= 1; dy++)
        for (let dx = -1; dx <= 1; dx++) {
          const nx = x + dx,
            ny = y + dy;
          if (
            nx < 0 ||
            ny < 0 ||
            nx >= w ||
            ny >= h
          )
            continue;
          const k = ny * w + nx;
          if (!labels[k] && p[k * 4 + 3] > 8) {
            labels[k] = id;
            queue[tail++] = k;
          }
        }
    }
    regions.push({ id, x0, y0, x1, y1, count: tail });
  }
  return { regions, labels };
}
export function assemble(
  images,
  { cols, rows, cell, mirror = false, foot = true, centre = true },
) {
  if (
    !Number.isInteger(cols) ||
    cols < 1 ||
    !Number.isInteger(rows) ||
    rows < 1 ||
    !Number.isInteger(cell) ||
    cell < 1
  )
    throw new Error("Invalid sheet dimensions");
  let subjects = [];
  images.forEach((im, index) => {
    const { regions, labels } = components(im),
      largest = Math.max(0, ...regions.map((r) => r.count));
    // A detached detail can join its nearest large body, but chains of tiny
    // flecks must never merge two distinct figures.
    const groups = regions
      .filter((r) => r.count >= largest * 0.05)
      .map((r) => ({ ...r, im, index, labels, ids: new Set([r.id]) }));
    for (const r of regions.filter((r) => r.count < largest * 0.05)) {
      let nearest = null,
        distance = Infinity;
      for (const g of groups) {
        const dx = Math.max(0, g.x0 - r.x1, r.x0 - g.x1),
          dy = Math.max(0, g.y0 - r.y1, r.y0 - g.y1),
          d = Math.hypot(dx, dy);
        if (d < distance) {
          nearest = g;
          distance = d;
        }
      }
      if (nearest && distance < im.width * 0.03) {
        nearest.ids.add(r.id);
        nearest.x0 = Math.min(nearest.x0, r.x0);
        nearest.y0 = Math.min(nearest.y0, r.y0);
        nearest.x1 = Math.max(nearest.x1, r.x1);
        nearest.y1 = Math.max(nearest.y1, r.y1);
        nearest.count += r.count;
      } else if (r.count >= largest * 0.005)
        groups.push({ ...r, im, index, labels, ids: new Set([r.id]) });
    }
    subjects.push(...groups);
  });
  if (subjects.length !== cols * rows)
    throw new Error(
      `Expected ${cols * rows} subjects, found ${subjects.length}`,
    );
  subjects.sort(
    (a, b) => a.index - b.index || a.y0 + a.y1 - (b.y0 + b.y1) || a.x0 - b.x0,
  );
  for (let row = 0; row < rows; row++)
    subjects.splice(
      row * cols,
      cols,
      ...subjects
        .slice(row * cols, (row + 1) * cols)
        .sort((a, b) => a.x0 - b.x0),
    );
  const single = cols * rows === 1,
    maxw = Math.max(...subjects.map((s) => s.x1 - s.x0 + 1)),
    maxh = Math.max(...subjects.map((s) => s.y1 - s.y0 + 1));
  const scale = single
      ? 1
      : Math.min(1, (cell * 0.84) / maxw, (cell * 0.84) / maxh),
    width = single ? maxw + 2 * Math.ceil(maxw * 0.02) : cols * cell,
    height = single ? maxh + 2 * Math.ceil(maxh * 0.02) : rows * cell,
    pixels = new Uint8Array(width * height * 4);
  subjects.forEach((s, i) => {
    let sum = 0,
      sx = 0;
    for (let y = s.y0; y <= s.y1; y++)
      for (let x = s.x0; x <= s.x1; x++) {
        const k = y * s.im.width + x;
        if (s.ids.has(s.labels[k])) {
          const a = s.im.pixels[k * 4 + 3];
          sum += a;
          sx += (mirror ? s.x1 - x : x - s.x0) * a;
        }
      }
    const sw = s.x1 - s.x0 + 1,
      sh = s.y1 - s.y0 + 1,
      dw = Math.max(1, Math.floor(sw * scale)),
      dh = Math.max(1, Math.floor(sh * scale)),
      cellX = (i % cols) * cell,
      cellY = Math.floor(i / cols) * cell;
    const cx = centre ? sx / sum : (sw - 1) / 2;
    let ox = single
        ? Math.ceil(maxw * 0.02)
        : Math.round(cellX + cell / 2 - cx * scale),
      oy = single
        ? Math.ceil(maxh * 0.02)
        : Math.round(cellY + (foot ? cell * 0.92 - dh : (cell - dh) / 2));
    ox = Math.max(cellX, Math.min(ox, (single ? width : cellX + cell) - dw));
    oy = Math.max(cellY, Math.min(oy, (single ? height : cellY + cell) - dh));
    for (let y = 0; y < dh; y++)
      for (let x = 0; x < dw; x++) {
        let ix = Math.min(sw - 1, Math.floor((x + 0.5) / scale)),
          iy = Math.min(sh - 1, Math.floor((y + 0.5) / scale));
        if (mirror) ix = sw - 1 - ix;
        const k = (s.y0 + iy) * s.im.width + s.x0 + ix;
        if (s.ids.has(s.labels[k]))
          pixels.set(
            s.im.pixels.subarray(k * 4, k * 4 + 4),
            ((oy + y) * width + ox + x) * 4,
          );
      }
  });
  return { width, height, pixels };
}
if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  try {
    const args = process.argv.slice(2),
      files = [],
      opts = { foot: true, centre: true };
    for (let i = 0; i < args.length; i++) {
      const a = args[i];
      if (a === "--mirror") opts.mirror = true;
      else if (a === "--no-foot") opts.foot = false;
      else if (a === "--no-centre") opts.centre = false;
      else if (["--cols", "--rows", "--cell", "--out"].includes(a))
        opts[a.slice(2)] = a === "--out" ? args[++i] : Number(args[++i]);
      else if (a.startsWith("--")) throw new Error(`Unknown option ${a}`);
      else files.push(a);
    }
    if (!files.length || !opts.out)
      throw new Error(
        "Usage: assemble-sheet.mjs <raw.png>... --cols C --rows R --cell PX --out FILE [--mirror]",
      );
    const result = assemble(
      files.map((f) => readPng(readFileSync(f))),
      opts,
    );
    writeFileSync(opts.out, writePng(result));
    console.log(`Wrote ${opts.out}: ${result.width}×${result.height}`);
  } catch (e) {
    console.error(e.message);
    process.exitCode = 1;
  }
}
