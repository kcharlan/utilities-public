import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const core = createRequire(import.meta.url)("../frontend_vendor/ladder_core.js");

test("whole points round halves and floating point noise correctly", () => {
  for (const [input, expected] of [[61.5, 62], [61.4, 61], [28.499999999999996, 29], [0.5, 1]]) {
    assert.equal(core.wholePoints(input), expected);
  }
});

test("frontier preserves ties and excludes unpriced rows", () => {
  const rows = [{label:"A", score:10, cost:1}, {label:"B", score:10, cost:1},
    {label:"C", score:9, cost:2}, {label:"D", score:99, cost:null}, {label:"E", score:99}];
  assert.deepEqual(core.frontier(rows).map(r => r.label), ["A", "B"]);
  const result = core.paretoRows(rows);
  assert.deepEqual(result.map(r => [r.label, r.status, r.by?.label ?? null]),
    [["A", "frontier", null], ["B", "frontier", null], ["C", "dominated", "A"]]);
});

test("steps describe gains and losses in each direction", () => {
  const a = {score:10, cost:1}, b = {score:12, cost:2};
  assert.equal(core.makeStep(a, b, "up").perPoint, 0.5);
  assert.equal(core.makeStep(b, a, "down").perPoint, 0.5);
  assert.equal(core.makeStep(a, {...b, cost:1}, "up").note, "costs no more");
  assert.equal(core.makeStep(b, {...a, cost:2}, "down").note, "saves nothing");
  assert.equal(core.makeStep(a, a, "up").note, "no gain");
  assert.equal(core.makeStep(a, a, "down").note, "no loss");
  assert.equal(core.makeStep(b, a, "up").note, "scores lower");
  assert.equal(core.makeStep(a, b, "down").note, "scores higher");
});

test("ticks span decades and linear intervals", () => {
  assert.deepEqual(core.logTicks(0.2, 20), [0.2, 0.5, 1, 2, 5, 10, 20]);
  assert.deepEqual(core.linearTicks(1, 13), [2, 4, 6, 8, 10, 12]);
});

test("data age uses hour, day and stale thresholds", () => {
  const then = "2020-01-01T00:00:00Z", start = Date.parse(then);
  assert.deepEqual(core.dataAge("invalid", start, 1), {text:"Data age is unknown", stale:true});
  for (const [hours, text, stale] of [[0.5, "Data is less than an hour old", false], [1, "Data is 1 hour old", false], [2, "Data is 2 hours old", true], [48, "Data is 2 days old", true]]) {
    assert.deepEqual(core.dataAge(then, start + hours * 3.6e6, 1), {text, stale});
  }
});

test('sort keys cycle and normalize without duplicates', () => {
  assert.deepEqual(core.clickSort([], 'score', 'd'), ['d:score']);
  assert.deepEqual(core.clickSort(['d:score'], 'price'), ['d:score','a:price']);
  assert.deepEqual(core.clickSort(['d:score'], 'score', 'd'), ['a:score']);
  assert.deepEqual(core.clickSort(['a:score'], 'score', 'd'), []);
  assert.deepEqual(core.clickSort(['a:price'], 'price'), ['d:price']);
  assert.deepEqual(core.clickSort(['d:price'], 'price'), []);
  assert.deepEqual(core.normalizeSort(['a:price','d:price','x:score',42,'d:score','a:other'], ['price','score']), ['a:price','d:score']);
  assert.deepEqual(core.normalizeSort(null, ['price']), []);
});

test('stack sort keeps nulls last and uses fallback and stable ties', () => {
  const rows=[{id:'a',s:2,p:3},{id:'b',s:2,p:null},{id:'c',s:2,p:1},{id:'d',s:1,p:1},{id:'e',s:2,p:1}];
  const value=(r,k)=>r[k];
  assert.deepEqual(core.stackSort(rows,['d:s','a:p'],value,(a,b)=>b.id.localeCompare(a.id)).map(r=>r.id),['e','c','a','b','d']);
  assert.deepEqual(core.stackSort(rows,['d:p'],value).map(r=>r.id),['a','c','d','e','b']);
  assert.equal(core.compareNullable(undefined,1),1);
});

test('adjacent equal values form runs and choose grouping density', () => {
  const rows=[1,1,2,3,3].map(v=>({v}));
  const runs=core.sortRuns(rows,(r,k)=>r[k],'v');
  assert.deepEqual(runs.map(r=>r.rows.length),[2,1,2]);
  assert.equal(core.sortRunMode(runs),'bands');
  assert.equal(core.sortRunMode(core.sortRuns([{v:1},{v:2}],r=>r.v,'v')),'singletons');
  assert.equal(core.sortRunMode(core.sortRuns(Array(6).fill({v:1}),r=>r.v,'v')),'headings');
});
