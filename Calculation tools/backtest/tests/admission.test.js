"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { execFileSync } = require("node:child_process");
const zlib = require("node:zlib");

// Invented observations exercise signatures only; none come from history.
function inventedData() {
  return { rows: Array.from({ length: 20 }, (_, i) => ({ year: 2000 + i,
    stock_tr: 0.123, bond10_tr: 0.234, tbill_tr: 0.345, cpi_change: 0.456, quality: "ok" })) };
}
const load = () => import("../tools/check_admission.mjs");

test("admission rejects prohibited paths even without observations", async () => {
  const { inspectBlob } = await load();
  for (const name of ["market-data.js", "market-data.csv", "renamed.xls", "renamed.xlsx", "datasets/id/data.json", "exports/example.csv"])
    assert.ok(inspectBlob(name, Buffer.from("invented")), name);
  assert.equal(inspectBlob("tests/synthetic.example.csv", Buffer.from("synthetic,value\nDEMO,1\n")), null);
});

test("admission rejects renamed JSON, CSV and JS dataset-shaped copies", async () => {
  const { inspectBlob } = await load();
  const json = JSON.stringify(inventedData());
  const csv = "year,stock_tr,bond10_tr,tbill_tr,cpi_change,quality\n" + inventedData().rows.map(r => Object.values(r).join(",")).join("\n");
  for (const contents of [json, csv, `globalThis.MARKET_DATA = ${json};`,
    zlib.gzipSync(json)])
    assert.ok(inspectBlob("innocent-copy.txt", Buffer.isBuffer(contents) ? contents : Buffer.from(contents)));
  assert.equal(inspectBlob("engine.js", Buffer.from('const schema = "stock_tr"; // synthetic formula')) , null);
});

test("admission refuses unsupported binary material instead of treating it as source", async () => {
  const { inspectBlob } = await load();
  assert.ok(inspectBlob("renamed.txt", Buffer.from([0xff, 0xfe, 0xfd])));
});





test("stage-zero inventory rejects a force-added ignored file and renamed data copy", async () => {
  const { checkIndex } = await load();
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "synthetic-market-admission-"));
  const git = (...args) => execFileSync("git", args, { cwd: root, stdio: "pipe" });
  try {
    git("init", "--quiet");
    const project = path.join(root, "Calculation tools", "backtest");
    fs.mkdirSync(project, { recursive: true });
    fs.writeFileSync(path.join(project, ".gitignore"), "market-data.js\n");
    fs.writeFileSync(path.join(project, "engine.js"), "// conspicuously synthetic source\n");
    git("add", ".");
    assert.equal(checkIndex({ repoRoot: root }).ok, true);
    fs.writeFileSync(path.join(project, "market-data.js"), "synthetic forced fixture");
    git("add", "--force", "Calculation tools/backtest/market-data.js");
    let result = checkIndex({ repoRoot: root });
    assert.equal(result.ok, false);
    assert.equal(result.findings.length, 1);
    git("rm", "--cached", "--force", "Calculation tools/backtest/market-data.js");
    fs.writeFileSync(path.join(project, "renamed.txt"), JSON.stringify(inventedData()));
    git("add", "Calculation tools/backtest/renamed.txt");
    result = checkIndex({ repoRoot: root });
    assert.equal(result.ok, false);
    assert.match(result.findings[0].reason, /dataset/);
    assert.ok(!JSON.stringify(result).includes("0.123"), "reports contain no observations");
    git("rm", "--cached", "--force", "Calculation tools/backtest/renamed.txt");
    fs.writeFileSync(path.join(root, "outside-copy.txt"), JSON.stringify(inventedData()));
    git("add", "outside-copy.txt");
    assert.equal(checkIndex({ repoRoot: root }).ok, false, "staged renamed data outside the project is checked");
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});

test("source recipe names only approved HTTPS acquisition and reviewed range", () => {
  const recipe = JSON.parse(fs.readFileSync(path.join(__dirname, "../data/sources.json"), "utf8"));
  assert.equal(recipe.schemaVersion, 1);
  assert.deepEqual(recipe.output, { firstYear: 1872, lastYear: 2025, spliceYear: 1928, reconciliationLastYear: 2022 });
  assert.deepEqual(recipe.sources.map(s => s.id), ["damodaran", "shiller"]);
  for (const source of recipe.sources) {
    const url = new URL(source.url);
    assert.equal(url.protocol, "https:");
    assert.ok(source.allowedOrigins.includes(url.origin));
    assert.equal(source.format, "OLE/XLS");
    assert.ok(source.requiredSheets.length);
  }
  assert.ok(!Object.hasOwn(recipe, "rows"));
});



// Recursive encoding and parser-vendor fingerprint policies are withdrawn.
test("admission allows ordinary code with harmless encoded constants",async()=>{const {inspectBlob}=await load();const encoded=Buffer.alloc(100,0xff).toString('base64');assert.equal(inspectBlob('tools/example.js',Buffer.from('const demo = '+JSON.stringify(encoded)+';')),null);});
