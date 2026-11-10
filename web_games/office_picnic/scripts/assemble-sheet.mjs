import { readFileSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { readPng, writePng } from "./png.mjs";
import { resize } from "./asset-metrics.mjs";

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
          if (nx < 0 || ny < 0 || nx >= w || ny >= h) continue;
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
    // Only substantial components can connect groups. Tiny flecks may be
    // attached afterward, but cannot form a bridge between whole subjects.
    const substantial = regions.filter((r) => r.count >= largest * 0.005);
    const parent = substantial.map((_, i) => i);
    const find = (i) => (parent[i] === i ? i : (parent[i] = find(parent[i])));
    const distance = (a, b) =>
      Math.hypot(
        Math.max(0, a.x0 - b.x1 - 1, b.x0 - a.x1 - 1),
        Math.max(0, a.y0 - b.y1 - 1, b.y0 - a.y1 - 1),
      );
    for (let i = 0; i < substantial.length; i++)
      for (let j = i + 1; j < substantial.length; j++)
        if (distance(substantial[i], substantial[j]) < im.width * 0.03)
          parent[find(j)] = find(i);
    const groups = new Map();
    const add = (g, r) => {
      g.ids.add(r.id);
      g.x0 = Math.min(g.x0, r.x0);
      g.y0 = Math.min(g.y0, r.y0);
      g.x1 = Math.max(g.x1, r.x1);
      g.y1 = Math.max(g.y1, r.y1);
    };
    substantial.forEach((r, i) => {
      const root = find(i),
        g = groups.get(root) || {
          im,
          index,
          labels,
          ids: new Set(),
          x0: im.width,
          y0: im.height,
          x1: 0,
          y1: 0,
        };
      add(g, r);
      groups.set(root, g);
    });
    for (const r of regions.filter((r) => r.count < largest * 0.005)) {
      let best = -1,
        dist = im.width * 0.03;
      substantial.forEach((seed, i) => {
        const d = distance(seed, r);
        if (d < dist) {
          dist = d;
          best = i;
        }
      });
      if (best >= 0) add(groups.get(find(best)), r);
    }
    subjects.push(...groups.values());
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
  const width = single ? maxw + 2 * Math.ceil(maxw * 0.02) : cols * cell;
  const height = single ? maxh + 2 * Math.ceil(maxh * 0.02) : rows * cell;
  const pixels = new Uint8Array(width * height * 4);
  // Crop whole subjects once, keeping only pixels belonging to their regions.
  for (const subject of subjects) {
    const sw = subject.x1 - subject.x0 + 1,
      sh = subject.y1 - subject.y0 + 1;
    subject.crop = {
      width: sw,
      height: sh,
      pixels: new Uint8Array(sw * sh * 4),
    };
    for (let y = 0; y < sh; y++)
      for (let x = 0; x < sw; x++) {
        const sourceX = mirror ? subject.x1 - x : subject.x0 + x;
        const source = (subject.y0 + y) * subject.im.width + sourceX;
        if (subject.ids.has(subject.labels[source]))
          subject.crop.pixels.set(
            subject.im.pixels.subarray(source * 4, source * 4 + 4),
            (y * sw + x) * 4,
          );
      }
  }
  let scale = single
    ? 1
    : Math.min(1, (cell * 0.84) / maxw, (cell * 0.84) / maxh);
  let prepared = [];
  // Rounding during area resampling can move alpha centroids, especially for
  // thin details. Recompute them from the actual output and keep the gutters.
  for (let attempt = 0; attempt < 12; attempt++) {
    prepared = subjects.map((subject) => {
      const sw = subject.crop.width,
        sh = subject.crop.height;
      const im = resize(
        subject.crop,
        Math.max(1, Math.floor(sw * scale)),
        Math.max(1, Math.floor(sh * scale)),
      );
      let weight = 0,
        sumX = 0,
        minX = im.width,
        maxX = -1,
        minY = im.height,
        maxY = -1;
      for (let y = 0; y < im.height; y++)
        for (let x = 0; x < im.width; x++) {
          const alpha = im.pixels[(y * im.width + x) * 4 + 3];
          if (alpha <= 8) continue;
          weight += alpha;
          sumX += x * alpha;
          minX = Math.min(minX, x);
          maxX = Math.max(maxX, x);
          minY = Math.min(minY, y);
          maxY = Math.max(maxY, y);
        }
      if (!weight) throw new Error("Subject disappeared during downscale");
      const centroid = centre ? sumX / weight : (minX + maxX) / 2;
      return { im, minX, maxX, minY, maxY, centroid };
    });
    if (single) break;
    const maxHorizontal = Math.max(
      ...prepared.map((p) =>
        Math.max(p.centroid - p.minX, p.maxX + 1 - p.centroid),
      ),
    );
    const maxVertical = Math.max(...prepared.map((p) => p.maxY - p.minY + 1));
    const factor = Math.min(
      1,
      (cell * 0.42 - 1) / maxHorizontal,
      (cell * 0.84 - 1) / maxVertical,
    );
    if (factor >= 1) break;
    scale *= Math.min(factor, 0.95);
    if (attempt === 11)
      throw new Error("Cannot fit subjects into cells with required gutters");
  }
  prepared.forEach((subject, i) => {
    const cellX = (i % cols) * cell,
      cellY = Math.floor(i / cols) * cell;
    const ox = single
      ? Math.ceil(maxw * 0.02)
      : Math.round(cellX + cell / 2 - subject.centroid);
    const oy = single
      ? Math.ceil(maxh * 0.02)
      : Math.round(
          cellY +
            (foot
              ? cell * 0.92 - (subject.maxY + 1)
              : (cell - subject.im.height) / 2),
        );
    for (let y = 0; y < subject.im.height; y++)
      for (let x = 0; x < subject.im.width; x++) {
        const dx = ox + x,
          dy = oy + y;
        if (dx >= 0 && dx < width && dy >= 0 && dy < height)
          pixels.set(
            subject.im.pixels.subarray(
              (y * subject.im.width + x) * 4,
              (y * subject.im.width + x) * 4 + 4,
            ),
            (dy * width + dx) * 4,
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
