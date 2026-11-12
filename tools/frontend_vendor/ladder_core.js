(function () {
"use strict";
var FLOAT_NOISE = 1e9;

function wholePoints(raw) {
  return Math.floor((Math.round(raw * 10) + 5) / 10);
}

function priced(row) {
  return row.cost !== null && row.cost !== undefined;
}

function dominates(b, a) {
  return b.score >= a.score && b.cost <= a.cost && (b.score > a.score || b.cost < a.cost);
}

function compareText(a, b) {
  return a < b ? -1 : a > b ? 1 : 0;
}

function frontier(rows) {
  var candidates = rows.filter(priced);
  return candidates.filter(function (row) {
    return !candidates.some(function (other) { return dominates(other, row); });
  }).sort(function (a, b) {
    return (a.cost - b.cost) || (a.score - b.score) || compareText(a.label, b.label);
  });
}

function makeStep(from, to, direction) {
  var points = to.score - from.score;
  var cost = priced(from) && priced(to)
    ? Math.round((to.cost - from.cost) * FLOAT_NOISE) / FLOAT_NOISE : null;
  var perPoint = null;
  var note = null;
  if (direction === "up") {
    if (points > 0) {
      if (cost !== null) {
        if (cost > 0) perPoint = cost / points; else note = "costs no more";
      }
    } else if (points === 0) note = "no gain";
    else note = "scores lower";
  } else {
    if (points < 0) {
      if (cost !== null) {
        if (cost < 0) perPoint = cost / points; else note = "saves nothing";
      }
    } else if (points === 0) note = "no loss";
    else note = "scores higher";
  }
  return { to: to, points: points, cost: cost, perPoint: perPoint, note: note };
}

function paretoRows(rows) {
  var list = rows.filter(priced).map(function (row) { return Object.assign({}, row); });
  list.sort(function (a, b) {
    return (a.cost - b.cost) || (b.score - a.score) || compareText(a.label, b.label);
  });
  var edge = frontier(list);
  var onEdge = new Set(edge);
  // frontier() returns the same objects it was given, so membership is by identity
  list.forEach(function (row) {
    row.up = null;
    row.down = null;
    if (onEdge.has(row)) {
      row.status = "frontier";
      row.by = null;
      var at = edge.indexOf(row);
      if (at < edge.length - 1) row.up = makeStep(row, edge[at + 1], "up");
      if (at > 0) row.down = makeStep(row, edge[at - 1], "down");
      return;
    }
    row.status = "dominated";
    var beaters = edge.filter(function (other) {
      return other.score >= row.score && other.cost <= row.cost;
    }).sort(function (a, b) {
      return (b.score - a.score) || (a.cost - b.cost) || compareText(a.label, b.label);
    });
    row.by = beaters[0] || null;
  });
  return list;
}

function pathValue(row, key) {
  var value = row;
  var parts = key.split(".");
  for (var i = 0; i < parts.length; i += 1) {
    if (value === null || value === undefined) return null;
    value = value[parts[i]];
  }
  return value === undefined ? null : value;
}

function compareValues(a, b) {
  return typeof a === "string" || typeof b === "string" ? compareText(String(a), String(b)) : a - b;
}

function dataAge(lastCheckedIso, nowMs, maxAgeHours) {
  var then = Date.parse(lastCheckedIso);
  if (isNaN(then)) return { text: "Data age is unknown", stale: true };
  var hours = Math.max(0, (nowMs - then) / 3.6e6);
  var text;
  if (hours < 1) text = "Data is less than an hour old";
  else if (hours < 2) text = "Data is 1 hour old";
  else if (hours < 48) text = "Data is " + Math.floor(hours) + " hours old";
  else text = "Data is " + Math.floor(hours / 24) + " days old";
  return { text: text, stale: hours > maxAgeHours };
}

function linearTicks(lo, hi) {
  const span = hi - lo;
  const step = span > 60 ? 20 : span > 30 ? 10 : span > 12 ? 5 : span > 5 ? 2 : 1;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) out.push(v);
  return out;
}

function logTicks(lo, hi) {
  const out = [];
  for (let e = Math.floor(Math.log10(lo)); e <= Math.ceil(Math.log10(hi)); e += 1) {
    [1, 2, 5].forEach((m) => {
      const v = Number((m * Math.pow(10, e)).toPrecision(3));
      if (v >= lo && v <= hi) out.push(v);
    });
  }
  return out;
}

var api = { FLOAT_NOISE: FLOAT_NOISE, wholePoints: wholePoints, priced: priced, dominates: dominates, compareText: compareText, frontier: frontier, makeStep: makeStep, paretoRows: paretoRows, pathValue: pathValue, compareValues: compareValues, dataAge: dataAge, linearTicks: linearTicks, logTicks: logTicks };
if (typeof module !== "undefined") module.exports = api; else window.ladderCore = api;
}());
