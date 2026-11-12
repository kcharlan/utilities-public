import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const BEGIN = "// ladder-math:begin";
const END = "// ladder-math:end";

function loadMath() {
  const here = dirname(fileURLToPath(import.meta.url));
  const lines = readFileSync(join(here, "..", "..", "model_ladder"), "utf8").split("\n");
  const begins = lines.reduce((acc, line, i) => (line.trim() === BEGIN ? acc.concat(i) : acc), []);
  const ends = lines.reduce((acc, line, i) => (line.trim() === END ? acc.concat(i) : acc), []);
  if (begins.length !== 1) throw new Error(`expected exactly one "${BEGIN}" marker, found ${begins.length}`);
  if (ends.length !== 1) throw new Error(`expected exactly one "${END}" marker, found ${ends.length}`);
  if (ends[0] <= begins[0]) throw new Error("ladder-math end marker comes before the begin marker");
  const code = lines.slice(begins[0] + 1, ends[0]).join("\n");
  const module = { exports: {} };
  const ladderCore = createRequire(import.meta.url)("../../../tools/frontend_vendor/ladder_core.js");
  new Function("module", "ladderCore", code)(module, ladderCore);
  return module.exports;
}

const m = loadMath();
const ORDER = ["max", "xhigh", "high", "medium", "low", "minimal", "non-reasoning"];
const MAKER = "Example Lab";

function row(family, rung, index, cost, extra = {}) {
  return {
    slug: `${family}-${rung}`.toLowerCase().replace(/ /g, "-"),
    name: family + (rung ? " " + rung : ""),
    maker: MAKER,
    family,
    family_key: JSON.stringify([MAKER, family]),
    rung,
    tags: [],
    index,
    cost,
    ...extra,
  };
}

const FIXTURE = [
  row("Alpha Test 1", "medium", 40.4, 2.0),
  row("Alpha Test 1", "high", 45.8, 5.0),
  row("Alpha Test 1", "xhigh", 46.2, 8.0),
  row("Alpha Test 1", "max", 48.6, 14.0),
  row("Beta Test 1", "medium", 32.2, 1.0),
  row("Beta Test 1", "high", 35.8, 1.4),
  row("Beta Test 1", "xhigh", 41.4, 3.0),
  row("Beta Test 1", "max", 43.1, 5.5),
];
const keysOf = (rows) => [...new Set(rows.map((r) => r.family_key))];

function select(rows, mode, extra = {}) {
  return m.selectRows(rows, { keys: keysOf(rows), hi: "max", lo: "medium", rungOrder: ORDER, mode, ...extra });
}
const labels = (rows) => rows.map((r) => r.label);

test("whole points rounds halves up", () => {
  const cases = [[61.8, 62], [62.2, 62], [61.5, 62], [61.4, 61], [0.5, 1], [28.5, 29], [64.6, 65]];
  for (const [raw, want] of cases) assert.equal(m.wholePoints(raw), want, String(raw));
});

test("frontier combines rows on the same whole point", () => {
  const rows = select(FIXTURE, "whole");
  assert.deepEqual(labels(m.frontier(rows)), [
    "Beta Test 1 Medium", "Beta Test 1 High", "Alpha Test 1 Medium",
    "Beta Test 1 XHigh", "Alpha Test 1 High", "Alpha Test 1 Max",
  ]);
});

test("dominated rows cite the right row", () => {
  const pareto = m.paretoRows(select(FIXTURE, "whole"));
  const dominated = pareto.filter((r) => r.status === "dominated");
  assert.deepEqual(dominated.map((r) => [r.label, r.by.label]), [
    ["Beta Test 1 Max", "Alpha Test 1 High"],
    ["Alpha Test 1 XHigh", "Alpha Test 1 High"],
  ]);
  assert.ok(pareto.filter((r) => r.status === "frontier").every((r) => r.by == null));
});

test("pareto rows are ordered by cost, score descending, then label", () => {
  const rows = [row("B", "high", 10, 1), row("A", "high", 10, 1), row("C", "high", 12, 1), row("D", "high", 5, 0.5)];
  assert.deepEqual(labels(m.paretoRows(select(rows, "whole", { hi: null, lo: null }))), ["D High", "C High", "A High", "B High"]);
});

test("decimal mode keeps both", () => {
  const rows = select(FIXTURE, "decimal");
  assert.ok(labels(m.frontier(rows)).includes("Alpha Test 1 XHigh"));
  assert.equal(rows.find((r) => r.label === "Alpha Test 1 High").score, 45.8);
});

test("frontier steps", () => {
  const pareto = m.paretoRows(select(FIXTURE, "whole"));
  const front = pareto.filter((r) => r.status === "frontier");
  const betaX = front.find((r) => r.label === "Beta Test 1 XHigh");
  assert.equal(betaX.up.points, 5);
  assert.ok(Math.abs(betaX.up.cost - 2.0) < 1e-9);
  assert.ok(Math.abs(betaX.up.perPoint - 0.4) < 1e-9);
  const alphaMax = front.find((r) => r.label === "Alpha Test 1 Max");
  assert.equal(alphaMax.down.points, -3);
  assert.ok(Math.abs(alphaMax.down.cost + 9.0) < 1e-9);
  assert.ok(Math.abs(alphaMax.down.perPoint - 3.0) < 1e-9);
  assert.equal(front[0].down, null);
  assert.equal(front[front.length - 1].up, null);
});

test("family steps follow effort order", () => {
  const steps = m.familySteps(select(FIXTURE, "whole"));
  const alphaHigh = steps.find((r) => r.label === "Alpha Test 1 High");
  assert.equal(alphaHigh.up.to.label, "Alpha Test 1 XHigh");
  assert.equal(alphaHigh.up.points, 0);
  assert.equal(alphaHigh.up.note, "no gain");
  assert.equal(alphaHigh.up.perPoint, null);
  const alphaX = steps.find((r) => r.label === "Alpha Test 1 XHigh");
  assert.equal(alphaX.down.to.label, "Alpha Test 1 High");
  assert.equal(alphaX.down.note, "no loss");
});

test("missing rung is skipped", () => {
  const rows = [row("Gamma Test", "high", 50, 4), row("Gamma Test", "low", 40, 1)];
  const steps = m.familySteps(select(rows, "whole", { lo: "low" }));
  const high = steps.find((r) => r.rung === "high");
  const low = steps.find((r) => r.rung === "low");
  assert.equal(high.down.to.rung, "low");
  assert.equal(low.up.to.rung, "high");
  assert.equal(high.up, null);
  assert.equal(low.down, null);
});

test("lower rung that costs more", () => {
  const rows = [row("Delta Test", "low", 10.0, 0.5), row("Delta Test", "non-reasoning", 9.0, 0.7)];
  const steps = m.familySteps(select(rows, "whole", { lo: "non-reasoning" }));
  const low = steps.find((r) => r.rung === "low");
  const nr = steps.find((r) => r.rung === "non-reasoning");
  assert.equal(low.down.note, "saves nothing");
  assert.ok(Math.abs(low.down.cost - 0.2) < 1e-9);
  assert.equal(low.down.perPoint, null);
  assert.equal(nr.up.note, "costs no more");
  assert.equal(nr.up.perPoint, null);
});

test("higher rung that scores lower", () => {
  const rows = [row("Eps Test", "xhigh", 50.0, 10), row("Eps Test", "max", 49.2, 13)];
  const steps = m.familySteps(select(rows, "whole"));
  assert.equal(steps.find((r) => r.rung === "xhigh").up.note, "scores lower");
  assert.equal(steps.find((r) => r.rung === "max").down.note, "scores higher");
});

test("null cost rung", () => {
  const rows = [row("Zeta Test", "high", 50, 4), row("Zeta Test", "low", 40, null)];
  const selected = select(rows, "whole", { lo: "low" });
  const high = m.familySteps(selected).find((r) => r.rung === "high");
  assert.equal(high.down.points, -10);
  assert.equal(high.down.cost, null);
  assert.equal(high.down.perPoint, null);
  assert.equal(high.down.note, null);
  assert.ok(!labels(m.paretoRows(selected)).includes("Zeta Test Low"));
});

test("identical rows are both frontier", () => {
  const rows = [row("Eta Test", "high", 50, 4), row("Theta Test", "high", 50, 4)];
  const pareto = m.paretoRows(select(rows, "whole"));
  assert.deepEqual(pareto.map((r) => r.status), ["frontier", "frontier"]);
});

test("effort range", () => {
  const rows = FIXTURE.concat([row("Alpha Test 1", null, 30, 0.5, { tags: ["Preview", "Beta"] }), row("Other Test", "high", 1, 1)]);
  const picked = m.selectRows(rows, { keys: keysOf(FIXTURE), hi: "high", lo: "medium", rungOrder: ORDER, mode: "whole" });
  assert.deepEqual(labels(picked), [
    "Alpha Test 1 Medium", "Alpha Test 1 High", "Beta Test 1 Medium", "Beta Test 1 High", "Alpha Test 1 (Preview, Beta)",
  ]);
  assert.equal(picked[0].rank, 3);
  assert.equal(picked[4].rank, null);
  assert.equal(m.selectRows(rows, { keys: [], hi: "max", lo: "low", rungOrder: ORDER, mode: "whole" }).length, 0);
});

test("findings", () => {
  const selected = select(FIXTURE, "whole");
  const out = m.findings(m.paretoRows(selected), m.familySteps(selected), "whole");
  assert.deepEqual(out, [
    "Beta Test 1 Max is dominated: Alpha Test 1 High scores 3 higher for $0.50 less per task.",
    "Alpha Test 1 XHigh is dominated: Alpha Test 1 High scores the same for $3.00 less per task.",
    "Cheapest step on the frontier: Beta Test 1 Medium to Beta Test 1 High, $0.10 per point.",
    "Most expensive step on the frontier: Alpha Test 1 High to Alpha Test 1 Max, $3.00 per point.",
    "Alpha Test 1 High to XHigh adds $3.00 per task and no points.",
  ]);
});

test("findings in decimal mode print one decimal and omit a repeated step", () => {
  const rows = [row("Iota Test", "low", 10, 1), row("Iota Test", "high", 20.5, 3)];
  const selected = select(rows, "decimal", { hi: "high", lo: "low" });
  const out = m.findings(m.paretoRows(selected), m.familySteps(selected), "decimal");
  assert.deepEqual(out, ["Cheapest step on the frontier: Iota Test Low to Iota Test High, $0.19 per point."]);
  const costly = [row("Kappa Test", "high", 20, 1), row("Kappa Test", "max", 19.4, 3)];
  const sel2 = select(costly, "decimal");
  const text = m.findings(m.paretoRows(sel2), m.familySteps(sel2), "decimal");
  assert.ok(text.includes("Kappa Test High to Max adds $2.00 per task and scores 0.6 lower."), text.join("|"));
});

test("dominated reason is the findings sentence after the label", () => {
  const pareto = m.paretoRows(select(FIXTURE, "whole"));
  const reasons = pareto.filter((r) => r.status === "dominated").map((r) => m.dominatedReason(r, "whole"));
  assert.deepEqual(reasons, [
    "Alpha Test 1 High scores 3 higher for $0.50 less per task",
    "Alpha Test 1 High scores the same for $3.00 less per task",
  ]);
  const same = [row("Mu Test", "high", 50, 4), row("Nu Test", "high", 40, 4)];
  const sameCost = m.paretoRows(select(same, "whole")).find((r) => r.status === "dominated");
  assert.equal(m.dominatedReason(sameCost, "whole"), "Mu Test High scores 10 higher for the same cost per task");
  assert.equal(m.dominatedReason({ status: "frontier", by: null }, "whole"), null);
  assert.equal(m.rungLabel("xhigh"), "XHigh");
});

test("sort puts nulls last both directions and is stable", () => {
  const rows = [
    { label: "a", score: 5, cost: null },
    { label: "b", score: 5, cost: 2 },
    { label: "c", score: 7, cost: 3 },
    { label: "d", score: 5, cost: 2 },
    { label: "e", score: 5, cost: 1 },
  ];
  assert.deepEqual(m.sortRows(rows, "cost", "asc").map((r) => r.label), ["e", "b", "d", "c", "a"]);
  assert.deepEqual(m.sortRows(rows, "cost", "desc").map((r) => r.label), ["c", "b", "d", "e", "a"]);
  assert.deepEqual(m.sortRows(rows, "score", "asc").map((r) => r.label), ["e", "b", "d", "a", "c"]);
  assert.deepEqual(rows.map((r) => r.label), ["a", "b", "c", "d", "e"]);
  const nested = [{ label: "x", score: 1, cost: 1, up: null }, { label: "y", score: 1, cost: 1, up: { perPoint: 2 } }];
  assert.deepEqual(m.sortRows(nested, "up.perPoint", "desc").map((r) => r.label), ["y", "x"]);
  assert.deepEqual(m.sortRows(nested, "up.perPoint", "asc").map((r) => r.label), ["y", "x"]);
});

test("search", () => {
  const list = m.families(FIXTURE);
  assert.deepEqual(m.searchFamilies(list, "beta").map((f) => f.family), ["Beta Test 1"]);
  assert.equal(m.searchFamilies(list, "EXAMPLE").length, 2);
  assert.equal(m.searchFamilies(list, "").length, 2);
  assert.equal(m.searchFamilies(list, "nothing here").length, 0);
});

test("families summary", () => {
  const list = m.families(FIXTURE);
  assert.deepEqual(list.map((f) => f.family), ["Alpha Test 1", "Beta Test 1"]);
  assert.equal(list[0].levels, 4);
  assert.equal(list[0].top, 49);
  assert.equal(list[0].key, FIXTURE[0].family_key);
  assert.equal(list[0].maker, MAKER);
  assert.equal(list[1].top, 43);
});

test("families count only rows with an effort level", () => {
  const rows = FIXTURE.concat([row("Alpha Test 1", null, 30.0, 1.0, { slug: "alpha-plain" })]);
  assert.equal(m.families(rows)[0].levels, 4);
  assert.equal(m.families([row("Plain Test 1", null, 10.0, 1.0)])[0].levels, 0);
});

test("row search matches maker, family and the full name with tags", () => {
  const tagged = row("Iota Test 1", "high", 30.0, 1.0, {
    name: "Iota Test 1 (High, Synthetic Tag)", tags: ["Synthetic Tag"],
  });
  const rows = FIXTURE.concat([tagged]);
  assert.deepEqual(m.searchRows(rows, "synthetic TAG").map((r) => r.slug), [tagged.slug]);
  assert.equal(m.searchRows(rows, "beta").length, 4);
  assert.equal(m.searchRows(rows, "example lab").length, 9);
  assert.equal(m.searchRows(rows, "  ").length, 9);
  assert.equal(m.searchRows(rows, "nothing here").length, 0);
});

test("present rungs", () => {
  assert.deepEqual(m.presentRungs(FIXTURE, ORDER), ["max", "xhigh", "high", "medium"]);
});

test("money", () => {
  assert.equal(m.money(26.5386), "$26.54");
  assert.equal(m.money(0.0844), "$0.084");
  assert.equal(m.money(0.1), "$0.10");
  assert.equal(m.money(null), "");
  assert.equal(m.money(-3), "$3.00");
  assert.equal(m.money(0), "$0.00");
  assert.equal(m.money(-0), "$0.00");
  assert.equal(m.money(0.0996), "$0.10");
  assert.equal(m.money(-0.0996), "$0.10");
  assert.equal(m.money(0.0994), "$0.099");
});

test("data age", () => {
  const last = "2026-11-11T00:00:00Z";
  const t = Date.parse(last);
  assert.deepEqual(m.dataAge(last, t - 5 * 3.6e6, 12), { text: "Data is less than an hour old", stale: false });
  assert.deepEqual(m.dataAge(last, t + 1.5 * 3.6e6, 12), { text: "Data is 1 hour old", stale: false });
  assert.deepEqual(m.dataAge(last, t + 13 * 3.6e6, 12), { text: "Data is 13 hours old", stale: true });
  assert.deepEqual(m.dataAge(last, t + 72 * 3.6e6, 12), { text: "Data is 3 days old", stale: true });
});

test("index rows and unscored rows use family and range filtering", () => {
  const rows = [row("Alpha", "high", 1, 1, {scores: {finance: 12}}),
    row("Alpha", "medium", 1, 1, {scores: {finance: null}}),
    row("Alpha", "low", 1, 1, {scores: {finance: null}}),
    row("Beta", "high", 1, 1, {scores: {finance: null}})];
  assert.deepEqual(m.rowsForIndex(rows, "finance").map(r => r.index), [12]);
  assert.notEqual(m.rowsForIndex(rows, "finance")[0], rows[0]);
  const selected = m.unscoredRows(rows, "finance", {keys: keysOf(rows), hi: "high", lo: "medium", rungOrder: ORDER});
  assert.deepEqual(selected.map(r => [r.label, r.rank]), [["Alpha Medium", 3], ["Beta High", 2]]);
  assert.deepEqual(m.unscoredRows(rows, "finance", {keys: [rows[0].family_key], hi: "high", lo: "medium", rungOrder: ORDER}).map(r => r.label), ["Alpha Medium"]);
});

test("unscored rows follow the selection order, then effort order", () => {
  const none = {scores: {finance: null}};
  const rows = [row("Beta", "low", 1, 1, none), row("Alpha", "medium", 1, 1, none), row("Beta", "max", 1, 1, none),
    row("Alpha", "xhigh", 1, 1, none), row("Alpha", null, 1, 1, none), row("Alpha", "high", 1, 1, none)];
  const keys = [rows[1].family_key, rows[0].family_key];
  assert.deepEqual(m.unscoredRows(rows, "finance", {keys, hi: null, lo: null, rungOrder: ORDER}).map(r => r.label),
    ["Alpha XHigh", "Alpha High", "Alpha Medium", "Alpha", "Beta Max", "Beta Low"]);
});

test("changes filter uses per-index scores including null", () => {
  const changes = {
    changed: [
      { slug: "a", name: "A", scores: {intelligence: [61.8, 62.2]}, cost: [1, 1] },
      { slug: "b", name: "B", scores: {intelligence: [61.4, 61.6]}, cost: [1, 1] },
      { slug: "c", name: "C", scores: {intelligence: [50, 50]}, cost: [1.2341, 1.2349] },
      { slug: "d", name: "D", scores: {intelligence: [50, 50]}, cost: [1.23, 1.25] },
      { slug: "e", name: "E", scores: {intelligence: [null, 0]}, cost: [1, 1] },
      { slug: "f", name: "F", scores: {intelligence: [null, null]}, cost: [1, 1] },
    ],
  };
  assert.deepEqual(m.changesToShow(changes, "whole", "intelligence").map((c) => c.slug), ["b", "d", "e"]);
  assert.deepEqual(m.changesToShow(changes, "decimal", "intelligence").map((c) => c.slug), ["a", "b", "d", "e"]);
  const domain = {changed: [
    {slug: "appears", scores: {finance: [null, 0]}, cost: [1, 1]},
    {slug: "disappears", scores: {finance: [5, null]}, cost: [1, 1]},
    {slug: "unchanged", scores: {finance: [null, null]}, cost: [1, 1]},
    // Not scored in this index before or after, so the view does not list it: a cost change alone stays out.
    {slug: "cost-only-unscored", scores: {finance: [null, null]}, cost: [1, 2]},
    {slug: "cost-only-scored", scores: {finance: [7, 7]}, cost: [1, 2]},
  ]};
  assert.deepEqual(m.changesToShow(domain, "whole", "finance").map(c => c.slug), ["appears", "disappears", "cost-only-scored"]);
  assert.deepEqual(m.changesToShow(null, "whole"), []);
});
