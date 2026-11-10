import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { readPng } from "../scripts/png.mjs";
import {
  measure,
  cellFailures,
  referenceLimits,
} from "../scripts/asset-metrics.mjs";
const root = new URL("../dist/assets/", import.meta.url),
  manifest = JSON.parse(readFileSync(new URL("manifest.json", root)));
const references = [
  ["plane-sheet.png", 2, 2],
  ["pigeon-sheet.png", 2, 2],
  ["washer-v1.png", 1, 1],
].map(([f, c, r]) => measure(readPng(readFileSync(new URL(f, root))), c, r));
const limits = referenceLimits(
  references.flatMap((reference) => reference.cells),
);
test("manifest assets meet A1–A7", () => {
  const size = readdirSync(root).reduce(
    (n, f) => n + statSync(new URL(f, root)).size,
    0,
  );
  assert.ok(size <= 16_000_000, `assets total ${size}`);
  for (const [name, a] of Object.entries(manifest)) {
    const data = readFileSync(new URL(a.file, root));
    assert.ok(data.length <= 2_500_000, `${name} file size`);
    assert.equal(data[24], 8, `${name} bit depth`);
    assert.equal(data[25], 6, `${name} RGBA`);
    assert.equal(data[28], 0, `${name} interlace`);
    const im = readPng(data),
      m = measure(im, a.cols, a.rows);
    assert.equal(im.width % a.cols, 0);
    assert.equal(im.height % a.rows, 0);
    for (const [i, c] of m.cells.entries()) {
      const height = Array.isArray(a.height) ? a.height[i % a.cols] : a.height;
      assert.ok(
        c.height >= height * 6.4,
        `${name} cell ${i} resolution ${c.height}`,
      );
      const failures = cellFailures(c, limits, {
        cutout: a.cutout,
        multi: m.cells.length > 1,
      });
      assert.deepEqual(
        failures,
        [],
        `${name} cell ${i} failed ${failures.join(", ")}`,
      );
    }
    if (["people", "token", "bowl", "trees"].includes(name))
      assert.ok(
        Math.max(...m.cells.map((c) => c.bottom)) -
          Math.min(...m.cells.map((c) => c.bottom)) <=
          m.cellHeight * 0.02,
        `${name} foot lines`,
      );
    if (["people", "token"].includes(name)) {
      for (let row = 0; row < a.rows; row++) {
        const cells = m.cells.slice(row * a.cols, (row + 1) * a.cols),
          heights = cells.map((c) => c.height);
        assert.ok(
          (Math.max(...heights) - Math.min(...heights)) /
            Math.max(...heights) <=
            0.06,
          `${name} row ${row} heights`,
        );
      }
      for (const c of m.cells)
        assert.ok(
          Math.abs(c.centroid - m.cellWidth / 2) <= m.cellWidth * 0.04,
          `${name} centroid`,
        );
    }
  }
});
