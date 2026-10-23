
(() => {
  "use strict";
  // --- data
  let data, currentState, searchTimer, earliestMs = null, dialShown = null;
  const controls = {};
  const PROVIDERS = ["codex", "claude", "opencode"];
  const PROVIDER_NAMES = {codex: "Codex", claude: "Claude", opencode: "OpenCode"};
  const usageProviders = new WeakMap();
  const providerOf = row => typeof row === "string" ? row : row.provider || "codex";
  const providerMatch = (row, state) => !state.src || state.src === "all" || providerOf(row) === state.src;
  function providerCosts(provider) {return data.meta.sources?.[provider]?.costs || data.meta.costs;}
  function costAvailability(rows) {
    const providers = [...new Set(rows.map(providerOf))];
    if (!providers.length) providers.push(...(PROVIDERS.includes(currentState.src) ? [currentState.src] : PROVIDERS.filter(provider => !sourceMissing(provider))));
    const unavailable = providers.filter(provider => !providerCosts(provider).available);
    return {any: providers.some(provider => providerCosts(provider).available), complete: !unavailable.length, unavailable};
  }
  function scopedCostRows(now, state = currentState) {const scoped = scope(data.sessions, state, now); return [...scoped.rows, ...scoped.agents];}
  function availableCostText(value, unpriced, rows) {
    const availability = costAvailability(rows);
    return availability.any && value !== null ? costText(value) + (unpriced ? " + unpriced" : "") + availability.unavailable.map(provider => " · " + provider + " costs unavailable").join("") : "costs unavailable";
  }
  const periods = ["mtd", "qtd", "ytd", "7d", "30d", "90d", "all", "custom"];
  // Calendar periods step by whole months, quarters or years; `o` counts steps back from the current one.
  const calendarMonths = {mtd: 1, qtd: 3, ytd: 12};
  const defaultPeriod = "mtd";
  const heatColors = () => Array.from({length: 5}, (_, n) =>
    getComputedStyle(document.documentElement).getPropertyValue("--heat-" + n).trim());
  // --- time
  const validMs = ms => typeof ms === "number" && Number.isFinite(ms) && Math.abs(ms) <= 8640000000000000;
  function localDayKey(ms) {
    if (!validMs(ms)) return null;
    const d = new Date(ms);
    return String(d.getFullYear()).padStart(4, "0") + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  }
  function localDayStart(ms) {
    if (!validMs(ms)) return null;
    const d = new Date(ms), start = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    start.setFullYear(d.getFullYear());
    return +start;
  }
  function addLocalDays(ms, n) {
    if (!validMs(ms) || !Number.isInteger(n)) return null;
    const d = new Date(ms), next = new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
    if (d.getFullYear() >= 0 && d.getFullYear() < 100) {
      next.setFullYear(d.getFullYear(), d.getMonth(), d.getDate() + n);
    }
    return validMs(+next) ? +next : null;
  }
  const mondayIndex = ms => validMs(ms) ? (new Date(ms).getDay() + 6) % 7 : null;
  const localHour = ms => validMs(ms) ? new Date(ms).getHours() : null;
  function parseDay(value) {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
    const [y, m, d] = value.split("-").map(Number), date = new Date(y, m - 1, d);
    date.setFullYear(y);
    return localDayKey(+date) === value ? +date : null;
  }
  function splitByLocalDay(start, end) {
    if (!validMs(start) || !validMs(end) || end <= start) return [];
    const parts = [];
    for (let cursor = start; cursor < end;) {
      const next = addLocalDays(localDayStart(cursor), 1);
      if (next === null || next <= cursor) break;
      const stop = Math.min(next, end);
      parts.push({day: localDayKey(cursor), ms: stop - cursor});
      cursor = stop;
    }
    return parts;
  }
  function monthStart(year, month) {
    // setFullYear normalizes month overflow and keeps years 0-99 literal.
    const date = new Date(2000, 0, 1);
    date.setFullYear(year, month, 1);
    return validMs(+date) ? +date : null;
  }
  const periodOffset = state => calendarMonths[state.p] && /^-[1-9]\d{0,3}$/.test(state.o || "") ? Number(state.o) : 0;
  function calendarWindow(period, now, offset) {
    const months = calendarMonths[period], d = new Date(now);
    const first = d.getMonth() - d.getMonth() % months;
    const from = monthStart(d.getFullYear(), first + offset * months), end = monthStart(d.getFullYear(), first + (offset + 1) * months);
    if (from === null || end === null) return null;
    return {from, to: offset ? end : now + 1};
  }
  function periodWindow(period, now, state = {}) {
    if (!validMs(now)) return null;
    period = String(period).toLowerCase();
    const day = localDayStart(now);
    if (period === "all") return {from: -Infinity, to: now + 1};
    if (period === "custom") {
      const from = parseDay(state.from), last = parseDay(state.to);
      return from !== null && last !== null && from <= last ? {from, to: addLocalDays(last, 1)} : null;
    }
    if (calendarMonths[period]) return calendarWindow(period, now, periodOffset({p: period, o: state.o}));
    const days = {"7d": 7, "30d": 30, "90d": 90}[period];
    return days ? {from: addLocalDays(day, 1 - days), to: now + 1} : null;
  }
  function previousWindow(period, window, now, state = {}) {
    period = String(period).toLowerCase();
    if (!window || period === "all" || period === "custom") return null;
    const length = window.to - window.from;
    if (calendarMonths[period]) {
      if (!validMs(now)) return null;
      const offset = periodOffset({p: period, o: state.o}), prior = calendarWindow(period, now, offset - 1);
      // The current period is partial: compare it with the same elapsed span of the prior one.
      return !prior ? null : offset ? prior : {from: prior.from, to: Math.min(prior.from + length, prior.to)};
    }
    return {from: window.from - length, to: window.from};
  }
  const time = {localDayKey, localDayStart, addLocalDays, mondayIndex, localHour, splitByLocalDay, periodWindow, previousWindow};
  // --- state
  const stateKeys = ["v", "p", "o", "from", "to", "a", "h", "src", "q", "day", "how", "ws", "sub", "model", "st", "sort", "s"];
  function normalizeState(raw) {
    const next = {
      v: ["overview", "list", "session"].includes(raw.v) ? raw.v : "overview",
      p: periods.includes(raw.p) ? raw.p : defaultPeriod,
      a: raw.a === "0" ? "0" : "1",
      h: raw.h === "0" ? "0" : "1",
      src: [...PROVIDERS, "all"].includes(raw.src) ? raw.src : "all",
      sort: ["newest", "longest", "subtime", "tokens", "cost"].includes(raw.sort) ? raw.sort : "newest"
    };
    for (const key of ["from", "to", "day"]) if (parseDay(raw[key]) !== null) next[key] = raw[key];
    if (periodOffset({p: next.p, o: raw.o})) next.o = raw.o;
    if (/^[0-6]-(?:[0-9]|1[0-9]|2[0-3])$/.test(raw.how || "")) next.how = raw.how;
    if (["aborted", "interrupted", "abandoned"].includes(raw.st)) next.st = raw.st;
    for (const key of ["q", "ws", "sub", "model", "s"]) {
      if (typeof raw[key] === "string" && raw[key] && !/[\x00-\x1f\x7f]/.test(raw[key])) {
        try { encodeURIComponent(raw[key]); next[key] = raw[key]; } catch (_) { /* unusable Unicode */ }
      }
    }
    if (next.from && next.to && next.from > next.to) { delete next.from; delete next.to; }
    return next;
  }
  function readState() {
    const raw = {}, conflicts = new Set();
    for (const part of location.hash.slice(1).split("&")) {
      const at = part.indexOf("=");
      if (at < 0) continue;
      try {
        const key = decodeURIComponent(part.slice(0, at)), value = decodeURIComponent(part.slice(at + 1));
        if (!stateKeys.includes(key) || conflicts.has(key)) continue;
        if (Object.prototype.hasOwnProperty.call(raw, key) && raw[key] !== value) {
          delete raw[key];
          conflicts.add(key);
        } else raw[key] = value;
      } catch (_) { /* malformed escape is no value evidence */ }
    }
    return normalizeState(raw);
  }
  function writeState(next, {replace = false} = {}) {
    currentState = normalizeState(next);
    const selected = data.sessions.find(row => row.id === currentState.s) || data.subagents[currentState.s];
    if (selected && !providerMatch(selected, currentState)) {
      delete currentState.s;
      if (currentState.v === "session") currentState.v = "list";
    }
    const hash = "#" + stateKeys.filter(key => key in currentState).map(key => key + "=" + encodeURIComponent(currentState[key])).join("&");
    if (hash !== location.hash) history[replace ? "replaceState" : "pushState"](null, "", hash);
    render();
  }
  function act(patch) {
    clearTimeout(searchTimer);
    writeState({...currentState, q: controls.search.value, ...patch});
  }
  // --- filters
  function ownSearch(row, query) {
    const text = [row.title_full || "", ...row.turns.flatMap(turn => turn.requests.map(request => request.text)),
      ...row.session_voice.requests.map(request => request.text)];
    return text.some(value => value.toLowerCase().includes(query));
  }
  function searchMatch(row, state, byId, seen = new Set()) {
    if (seen.has(row.id) || !providerMatch(row, state) || (state.a === "0" && row.archived) || (state.h === "0" && row.history_only)) return false;
    seen.add(row.id);
    const query = (state.q || "").toLowerCase();
    return ownSearch(row, query) || row.children.some(id => byId[id] && searchMatch(byId[id], state, byId, seen));
  }
  const filters = {searchMatch};
  // --- aggregates
  const inWindow = (ms, window) => validMs(ms) && window && ms >= window.from && ms < window.to;
  function descendants(row, byId, state) {
    const rows = [], seen = new Set([row.id]), pending = [...row.children];
    for (let n = 0; n < pending.length; n++) {
      const id = pending[n], child = byId[id];
      if (seen.has(id) || !child) continue;
      seen.add(id);
      if (!providerMatch(child, state) || (state.a === "0" && child.archived) || (state.h === "0" && child.history_only)) continue;
      rows.push(child);
      pending.push(...child.children);
    }
    return rows;
  }
  function windowBuckets(row, window) {
    return row.buckets.filter(bucket => typeof bucket[0] === "number" && inWindow(bucket[0] * 900000, window));
  }
  function ownMatch(row, state, window) {
    if (!window || !providerMatch(row, state) || (state.a === "0" && row.archived) || (state.h === "0" && row.history_only)) return false;
    const buckets = windowBuckets(row, window);
    const span = validMs(row.start_ms) && validMs(row.end_ms) && row.end_ms >= row.start_ms && row.start_ms < window.to && row.end_ms >= window.from;
    if (!span && !buckets.length) return false;
    const turns = row.turns.filter(turn => inWindow(turn.start_ms, window));
    return (!state.q || ownSearch(row, state.q.toLowerCase())) &&
      (!state.ws || row.workspace === state.ws) && (!state.sub || row.subfolder === state.sub) &&
      (!state.model || buckets.some(bucket => bucket[1] === state.model)) &&
      (!state.day || turns.some(turn => localDayKey(turn.start_ms) === state.day)) &&
      (!state.how || turns.some(turn => mondayIndex(turn.start_ms) + "-" + localHour(turn.start_ms) === state.how)) &&
      (!state.st || turns.some(turn => turn.status === state.st));
  }
  function matchSession(session, state, byId) {
    const matchedSubagents = new Set();
    if (!providerMatch(session, state) || (state.a === "0" && session.archived) || (state.h === "0" && session.history_only)) return {match: false, matchedSubagents};
    const window = state._window || periodWindow(state.p || defaultPeriod, data.meta.generated_at_ms, state);
    for (const child of descendants(session, byId, state)) if (ownMatch(child, state, window)) matchedSubagents.add(child.id);
    return {match: ownMatch(session, state, window) || matchedSubagents.size > 0, matchedSubagents};
  }
  filters.matchSession = matchSession;
  function scope(sessions, state, now) {
    const window = state._window || periodWindow(state.p || defaultPeriod, now, state);
    const rows = sessions.filter(row => matchSession(row, {...state, _window: window}, data.subagents).match);
    const agents = new Map();
    for (const row of rows) for (const child of descendants(row, data.subagents, state)) agents.set(child.id, child);
    return {window, rows, agents: [...agents.values()]};
  }
  function turnIntervals(row, window) {
    if (!window) return [];
    return row.turns.filter(turn => ["completed", "aborted", "interrupted", "running"].includes(turn.status) &&
      validMs(turn.start_ms) && validMs(turn.end_ms) && typeof turn.duration_ms === "number" && Number.isFinite(turn.duration_ms) && turn.duration_ms >= 0)
      .map(turn => [Math.max(window.from, turn.start_ms), Math.min(window.to, turn.end_ms)])
      .filter(([start, end]) => end > start);
  }
  function mergedIntervals(parts) {
    const merged = [];
    for (const [start, end] of parts.sort((a, b) => a[0] - b[0] || a[1] - b[1])) {
      const last = merged[merged.length - 1];
      if (last && start <= last[1]) last[1] = Math.max(last[1], end);
      else merged.push([start, end]);
    }
    return merged;
  }
  const activeMs = parts => mergedIntervals(parts).reduce((sum, [start, end]) => sum + end - start, 0);
  function evidenceSum(values, currency = false) {
    const valid = value => typeof value === "number" && Number.isFinite(value) && value >= 0 && (currency || Number.isSafeInteger(value));
    if (!values.every(valid)) return null;
    const sum = values.reduce((total, value) => total + value, 0);
    return valid(sum) ? sum : null;
  }
  // Null is sticky: later valid costs must not repair an overflowing summary.
  const addCost = (total, value) => total === null || value === null ? null : evidenceSum([total, value], true);
  const bucketCosts = buckets => buckets.reduce((total, bucket) => bucket[8] === null ? total : addCost(total, bucket[8]), 0);
  const currencyMargin = (scale, operations) => Math.max(4 * operations * (Number.EPSILON * scale + Number.MIN_VALUE), 1e-9 * scale + 1e-9);
  function provesUsage(selected, total, turn, operations, currency = false) {
    if (evidenceSum([selected, total, turn], currency) === null || turn > total) return false;
    // Buckets have no turn IDs. Conservation proves this particular turn only
    // when the window cannot be filled entirely by all other own usage.
    // Currency subtraction/addition needs a scale- and operation-count guard.
    // Compiler unit-fold depth is absent from the payload, so also require a
    // gap beyond the §5.6 representation tolerance, scaled to all operands.
    // Neither .1 > (.3 - .2) nor accumulated unit-rounding proves inclusion.
    const scale = selected + total + turn;
    const margin = currency ? currencyMargin(scale, operations) : 0;
    return Number.isFinite(margin) && selected - total <= margin && selected - (total - turn) > margin;
  }
  function paidCapacity(usage) {
    if (usage.cost_usd !== null) return evidenceSum([usage.cost_usd], true);
    const total = evidenceSum([usage.input, usage.output]);
    // Null alone is unknown. Conserved wholly-unpriced input/output rules out
    // paid units only with valid cached reads contained in input. This Codex
    // row path passes zero billed cache-write tokens; reasoning is billed only
    // through output (§5.6 and pinned codexResolvedCostUSD).
    return total !== null && evidenceSum([usage.unpriced_tokens, usage.cached_input, usage.cache_write, usage.reasoning]) !== null &&
      usage.unpriced_tokens === total && usage.cached_input <= usage.input ? 0 : null;
  }
  function liveUsage(row, window) {
    const buckets = windowBuckets(row, window), operations = row.buckets.length + row.turns.length + 4;
    const volume = value => evidenceSum([value.input, value.output]);
    const selected = evidenceSum(buckets.flatMap(b => [b[3], b[6]]));
    const unpriced = evidenceSum(buckets.filter(b => b[8] === null).flatMap(b => [b[3], b[6]]));
    const completeCosts = evidenceSum([...row.buckets.map(b => b[8]), ...row.turns.map(t => t.usage.cost_usd), row.outside_usage.cost_usd], true) !== null;
    // Numeric buckets are a lower bound; a null bucket may hide paid units.
    const cost = evidenceSum(buckets.filter(b => b[8] !== null).map(b => b[8]), true);
    const components = [row.outside_usage, ...row.turns.map(turn => turn.usage)];
    const partitioned = ["input", "cached_input", "cache_write", "output", "reasoning", "unpriced_tokens"].every(key =>
      evidenceSum([row.own_usage[key]]) !== null && evidenceSum(components.map(value => value[key])) === row.own_usage[key]);
    let tokens = 0, costs = 0;
    for (const turn of row.turns) if (turn.status === "running") {
      if (provesUsage(selected, volume(row.own_usage), volume(turn.usage), operations)) tokens++;
      const competing = [row.outside_usage, ...row.turns.filter(other => other !== turn).map(other => other.usage)];
      const capacity = evidenceSum(competing.map(paidCapacity), true);
      const capacityKnown = evidenceSum([cost, capacity], true) !== null;
      const targetValid = turn.usage.cost_usd === null || evidenceSum([turn.usage.cost_usd], true) !== null;
      const paid = provesUsage(completeCosts ? cost : null, row.own_usage.cost_usd, turn.usage.cost_usd, operations, true) ||
        // The target's total may itself be unknown: a positive displayed lower
        // bound exceeding ALL known competitors still proves its contribution.
        (row.own_usage.cost_usd === null && partitioned && targetValid && capacityKnown &&
          cost - capacity > currencyMargin(cost + capacity, operations));
      const ownVolume = volume(row.own_usage), turnVolume = volume(turn.usage);
      const validUnpriced = evidenceSum([row.own_usage.unpriced_tokens, turn.usage.unpriced_tokens]) !== null &&
        row.own_usage.unpriced_tokens <= ownVolume && turn.usage.unpriced_tokens <= turnVolume && turn.usage.unpriced_tokens <= row.own_usage.unpriced_tokens;
      // All null-bucket tokens may be paid competitors; subtract only this
      // turn's known unpriced volume from ALL own volume, not own unpriced.
      if (paid || (validUnpriced && provesUsage(unpriced, ownVolume, turn.usage.unpriced_tokens, operations))) costs++;
    }
    return {tokens, costs};
  }
  function kpis(sessions, state, now) {
    const {window, rows, agents} = scope(sessions, state, now);
    const turns = rows.flatMap(row => row.turns.filter(turn => inWindow(turn.start_ms, window)));
    const durations = turns.filter(turn => turn.status !== "abandoned" && typeof turn.duration_ms === "number" && Number.isFinite(turn.duration_ms) && turn.duration_ms >= 0).map(turn => turn.duration_ms);
    const usage = [...rows, ...agents].flatMap(row => windowBuckets(row, window));
    const input = usage.reduce((sum, b) => sum + b[3], 0), cached = usage.reduce((sum, b) => sum + b[4], 0);
    const running = (list, predicate) => list.flatMap(row => row.turns).filter(turn => turn.status === "running" && predicate(turn)).length;
    const contributesTime = turn => turnIntervals({turns: [turn]}, window).length > 0;
    const ownRunning = running(rows, turn => inWindow(turn.start_ms, window) || contributesTime(turn));
    const usageRunning = [...rows, ...agents].map(row => ({...liveUsage(row, window), provider: providerOf(row)}));
    return {sessions: rows.length, active_ms: activeMs(rows.flatMap(row => turnIntervals(row, window))),
      agent_ms: agents.reduce((sum, row) => sum + activeMs(turnIntervals(row, window)), 0), turns: turns.length,
      average_ms: durations.length ? durations.reduce((sum, value) => sum + value, 0) / durations.length : null,
      input, tokens: usage.reduce((sum, b) => sum + b[3] + b[6], 0), cached_share: input ? cached / input : null,
      cost: bucketCosts(usage),
      unpriced: usage.some(b => b[8] === null), aborted: turns.filter(t => t.status === "aborted").length,
      interrupted: turns.filter(t => t.status === "interrupted").length, abandoned: turns.filter(t => t.status === "abandoned").length,
      live: {sessions: ownRunning, active_ms: running(rows, contributesTime), agent_ms: running(agents, contributesTime),
        turns: turns.filter(t => t.status === "running").length, tokens: usageRunning.reduce((sum, value) => sum + value.tokens, 0),
        cost: usageRunning.filter(value => providerCosts(value.provider).available).reduce((sum, value) => sum + value.costs, 0), aborted: 0}};
  }
  function calendar(sessions, state, now) {
    const {window, rows, agents} = scope(sessions, state, now);
    if (!window) return [];
    let first = window.from;
    if (!Number.isFinite(first)) {
      const activity = [...rows, ...agents].flatMap(row => [...row.turns.filter(t => inWindow(t.start_ms, window)).map(t => t.start_ms),
        ...windowBuckets(row, window).map(b => b[0] * 900000)]);
      first = activity.length ? activity.reduce((a, b) => Math.min(a, b)) : now;
      first = addLocalDays(localDayStart(first), -mondayIndex(first));
    }
    const days = new Map();
    for (let day = localDayStart(first); day < window.to; day = addLocalDays(day, 1)) {
      days.set(localDayKey(day), {day: localDayKey(day), sessions: 0, active_ms: 0, tokens: 0, cost: 0, unpriced: false, providers: []});
    }
    for (const row of rows) {
      const starts = new Set(row.turns.filter(t => inWindow(t.start_ms, window)).map(t => localDayKey(t.start_ms)));
      for (const day of starts) if (days.has(day)) days.get(day).sessions++;
    }
    for (const [start, end] of mergedIntervals(rows.flatMap(row => turnIntervals(row, window)))) {
      for (const part of splitByLocalDay(start, end)) if (days.has(part.day)) days.get(part.day).active_ms += part.ms;
    }
    for (const row of [...rows, ...agents]) for (const bucket of windowBuckets(row, window)) {
      const cell = days.get(localDayKey(bucket[0] * 900000));
      if (!cell) continue;
      cell.tokens += bucket[3] + bucket[6];
      if (!cell.providers.includes(providerOf(row))) cell.providers.push(providerOf(row));
      if (bucket[8] === null) cell.unpriced = true;
      else cell.cost = addCost(cell.cost, bucket[8]);
    }
    return [...days.values()];
  }
  function hourWeekday(sessions, state, now) {
    const {window, rows} = scope(sessions, state, now), cells = Array.from({length: 7}, () => Array(24).fill(0));
    for (const row of rows) for (const turn of row.turns) if (inWindow(turn.start_ms, window)) cells[mondayIndex(turn.start_ms)][localHour(turn.start_ms)]++;
    return cells;
  }
  function workspaces(sessions, state, now) {
    const {window, rows, agents} = scope(sessions, state, now), items = new Map();
    for (const row of [...rows, ...agents]) {
      if (!items.has(row.workspace)) items.set(row.workspace, {key: row.workspace, active_ms: 0, tokens: 0});
      items.get(row.workspace).tokens += windowBuckets(row, window).reduce((sum, b) => sum + b[3] + b[6], 0);
    }
    for (const [key, item] of items) item.active_ms = activeMs(rows.filter(row => row.workspace === key).flatMap(row => turnIntervals(row, window)));
    return [...items.values()].sort((a, b) => b.active_ms - a.active_ms || String(a.key).localeCompare(String(b.key)));
  }
  function models(sessions, state, now) {
    const {window, rows, agents} = scope(sessions, state, now), items = new Map();
    for (const row of [...rows, ...agents]) for (const bucket of windowBuckets(row, window)) {
      if (!items.has(bucket[1])) items.set(bucket[1], {model: bucket[1], tokens: 0, cost: 0, unpriced: false, providers: []});
      const item = items.get(bucket[1]);
      if (!item.providers.includes(providerOf(row))) item.providers.push(providerOf(row));
      item.tokens += bucket[3] + bucket[6];
      if (bucket[8] === null) item.unpriced = true;
      else item.cost = addCost(item.cost, bucket[8]);
    }
    return [...items.values()].sort((a, b) => b.tokens - a.tokens || a.model.localeCompare(b.model));
  }
  function notable(sessions, state, now) {
    const days = calendar(sessions, state, now), {rows} = scope(sessions, state, now);
    const bestDay = metric => days.reduce((best, cell) => cell[metric] > (best ? best[metric] : 0) ? cell : best, null);
    let fanout = null, streak = null, run = null;
    for (const row of rows) {
      const count = descendants(row, data.subagents, state).length;
      if (count > (fanout ? fanout.count : 0)) fanout = {id: row.id, count};
    }
    for (const cell of days) {
      if (!cell.sessions) {run = null; continue;}
      run = run ? {...run, to: cell.day, count: run.count + 1} : {from: cell.day, to: cell.day, count: 1};
      if (!streak || run.count > streak.count) streak = run;
    }
    return {busiest: bestDay("sessions"), active: bestDay("active_ms"), fanout, streak};
  }
  const newest = (a, b) => Number(!validMs(a.start_ms)) - Number(!validMs(b.start_ms)) || (b.start_ms || 0) - (a.start_ms || 0) || a.id.localeCompare(b.id);
  function recent(sessions, state, now) {return scope(sessions, state, now).rows.sort(newest).slice(0, 5);}
  const aggregates = {kpis, calendar, hourWeekday, workspaces, models, notable, recent};
  // --- format
  function localStamp(ms) {
    if (!validMs(ms)) return "unknown";
    const d = new Date(ms);
    return localDayKey(ms) + " " + String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
  }
  const format = {localStamp};
  // --- dom
  function el(tag, props, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props || {})) {
      if (key === "text") node.textContent = value;
      else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2).toLowerCase(), value);
      else if (value === null || value === undefined) continue;
      else node.setAttribute(key, value);
    }
    node.append(...children);
    return node;
  }
  // Expanded text taller than the screen gets a collapse control above it.
  const exceedsViewport = node => node.getBoundingClientRect().height > innerHeight;
  // After collapsing, bring an offscreen block's start back into view.
  function returnTo(anchor, control) {
    if (!anchor.isConnected) return;
    control.focus({preventScroll: true});
    const top = anchor.getBoundingClientRect().top;
    if (top < 0 || top >= innerHeight) anchor.scrollIntoView({block: "start"});
  }
  function mountTopbar() {
    controls.sources = ["all", ...PROVIDERS].map(src => {
      const name = src === "all" ? "All" : PROVIDER_NAMES[src];
      const missing = src !== "all" && data.meta.sources?.[src]?.status !== undefined && data.meta.sources[src].status !== "ok";
      return el("button", {type: "button", "data-source": src, text: name + (missing ? " · no data" : ""), onclick: () => act({src})});
    });
    controls.search = el("input", {type: "search", placeholder: "Search titles and requests", "aria-label": "Search titles and requests", oninput: () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => writeState({...currentState, q: controls.search.value}, {replace: true}), 200);
    }});
    // Choosing a period always returns to its current instance; Custom starts from the range on screen.
    controls.periods = periods.map(period => el("button", {type: "button", text: period === "custom" ? "Custom" : period.toUpperCase(), onclick: () => {
      const patch = {p: period, o: undefined}, now = data.meta.generated_at_ms;
      if (period === "custom" && currentState.p !== "custom") {
        const window = periodWindow(currentState.p, now, currentState);
        patch.from = localDayKey(window && Number.isFinite(window.from) ? window.from : earliestMs ?? now);
        patch.to = localDayKey(window ? window.to - 1 : now);
      }
      act(patch);
    }}));
    controls.from = el("input", {type: "date", "aria-label": "From date", onchange: () => act({from: controls.from.value})});
    controls.to = el("input", {type: "date", "aria-label": "To date", onchange: () => act({to: controls.to.value})});
    controls.custom = el("span", {class: "custom-dates"}, controls.from, el("span", {class: "period-note", "aria-hidden": "true", text: "–"}), controls.to);
    controls.label = el("span", {class: "period-label", "data-period-label": "", "aria-live": "polite"});
    controls.prev = el("button", {type: "button", class: "period-step", text: "‹", onclick: () => stepPeriod(-1)});
    controls.next = el("button", {type: "button", class: "period-step", text: "›", onclick: () => stepPeriod(1)});
    controls.dial = el("div", {class: "period-dial", role: "group", "aria-label": "Period range"},
      controls.prev, el("span", {class: "period-view"}, controls.label, controls.custom), controls.next);
    controls.archive = el("button", {type: "button", onclick: () => act({a: currentState.a === "1" ? "0" : "1"})});
    controls.history = el("button", {type: "button", onclick: () => act({h: currentState.h === "1" ? "0" : "1"})});
    controls.breadcrumb = el("nav", {class: "breadcrumb", "aria-label": "Breadcrumb"});
    controls.chips = el("div", {class: "filter-chips"});
    const catalog = data.meta.catalog;
    const priceText = catalog.fetched_at_ms === null ? "catalog unavailable" : "catalog " + catalog.source_host + " " + localStamp(catalog.fetched_at_ms);
    document.getElementById("colophon-topbar").replaceChildren(
      el("div", {class: "topline"}, el("button", {class: "brand", type: "button", text: "COLOPHON", onclick: () => act({v: "overview", s: undefined})}), controls.breadcrumb),
      el("p", {id: "snapshot-meta", text: "data as of " + localStamp(data.meta.generated_at_ms) + " · " + (data.meta.sources ? PROVIDERS.reduce((sum, provider) => sum + (data.meta.sources[provider]?.logs || 0), 0) : data.meta.counts.logs) + " logs" + (data.meta.sources?.opencode ? " · " + data.meta.sources.opencode.databases.filter(db => db.status === "ok").length + " OpenCode databases" : "") + " · " + priceText}),
      el("div", {class: "controls"}, el("div", {class: "periods", role: "group", "aria-label": "Source"}, ...controls.sources), controls.search, el("div", {class: "period-controls"}, controls.dial, el("div", {class: "periods", role: "group", "aria-label": "Period"}, ...controls.periods)), controls.archive, controls.history), controls.chips);
  }
  // --- period dial
  const monthText = (ms, month) => new Date(ms).toLocaleString("en-US", {month});
  const dayText = (ms, withYear) => monthText(ms, "short") + " " + new Date(ms).getDate() + (withYear ? ", " + new Date(ms).getFullYear() : "");
  function rangeText(window) {
    const last = localDayStart(window.to - 1), year = ms => new Date(ms).getFullYear();
    const split = year(window.from) !== year(last), withYear = split || year(last) !== year(data.meta.generated_at_ms);
    if (!split && new Date(window.from).getMonth() === new Date(last).getMonth()) return dayText(window.from, false) + "–" + dayText(last, withYear).replace(/^\S+ /, "");
    return dayText(window.from, split) + " – " + dayText(last, withYear);
  }
  function periodName(period, window, offset) {
    if (!window) return {name: "No dates selected", note: ""};
    const d = new Date(window.from), year = String(d.getFullYear()), note = offset ? "" : "to date";
    if (period === "mtd") return {name: monthText(window.from, "long") + " " + year, note};
    if (period === "qtd") return {name: "Q" + (Math.floor(d.getMonth() / 3) + 1) + " " + year,
      note: note || monthText(window.from, "short") + " – " + monthText(window.to - 1, "short")};
    if (period === "ytd") return {name: year, note};
    if (period === "all") return {name: "All time", note: ""};
    return {name: rangeText(window), note: ""};
  }
  function comparisonText(previous) {
    const period = currentState.p;
    if (!calendarMonths[period]) return "vs prior " + period.toUpperCase();
    return "vs " + (periodOffset(currentState) ? periodName(period, previous, -1).name : rangeText(previous));
  }
  // The patch that moves the period one step, or null when that step would leave the data or pass the snapshot.
  function periodStep(direction, state = currentState) {
    const now = data.meta.generated_at_ms, window = periodWindow(state.p, now, state);
    if (!window || (direction < 0 && (earliestMs === null || window.from <= earliestMs))) return null;
    if (calendarMonths[state.p]) {
      const offset = periodOffset(state) + direction;
      return offset > 0 ? null : {o: offset ? String(offset) : undefined};
    }
    if (state.p !== "custom" || (direction > 0 && state.to >= localDayKey(now))) return null;
    const from = parseDay(state.from), to = parseDay(state.to), span = Math.round((to - from) / 86400000) + 1;
    return {from: localDayKey(addLocalDays(from, direction * span)), to: localDayKey(addLocalDays(to, direction * span))};
  }
  function stepPeriod(direction) {
    const patch = periodStep(direction);
    if (patch) act(patch);
  }
  function renderDial() {
    const period = currentState.p, custom = period === "custom", unit = {mtd: "month", qtd: "quarter", ytd: "year", custom: "range"}[period] || "period";
    const window = periodWindow(period, data.meta.generated_at_ms, currentState), {name, note} = periodName(period, window, periodOffset(currentState));
    controls.label.hidden = custom;
    controls.custom.hidden = !custom;
    controls.label.replaceChildren(el("span", {class: "period-name", text: name}), ...(note ? [el("span", {class: "period-note", text: note})] : []));
    for (const [button, direction, word, key] of [[controls.prev, -1, "Previous", "["], [controls.next, 1, "Next", "]"]]) {
      button.disabled = !periodStep(direction);
      button.setAttribute("aria-label", word + " " + unit);
      button.title = word + " " + unit + " (" + key + ")";
    }
    // Slide the new period in from the side it lies on; a jump of several periods travels farther.
    const before = dialShown;
    dialShown = window && {period, from: window.from, span: window.to - window.from};
    if (!before || !dialShown || before.period !== period || before.from === dialShown.from) return;
    const shift = dialShown.from - before.from;
    controls.dial.removeAttribute("data-motion");
    void controls.dial.offsetWidth;
    controls.dial.dataset.motion = (shift < 0 ? "back" : "forward") + (Math.abs(shift) > Math.max(before.span, dialShown.span) * 1.5 ? "-far" : "");
  }
  function renderTopbar() {
    document.documentElement.dataset.source = currentState.src;
    controls.sources.forEach(button => button.setAttribute("aria-pressed", String(button.dataset.source === currentState.src)));
    controls.search.value = currentState.q || "";
    controls.periods.forEach((button, index) => button.setAttribute("aria-pressed", String(periods[index] === currentState.p)));
    renderDial();
    controls.from.value = currentState.from || "";
    controls.to.value = currentState.to || "";
    controls.archive.textContent = "archived: " + (currentState.a === "1" ? "shown" : "hidden");
    controls.archive.setAttribute("aria-pressed", String(currentState.a === "1"));
    controls.history.textContent = "history only: " + (currentState.h === "1" ? "shown" : "hidden");
    controls.history.setAttribute("aria-pressed", String(currentState.h === "1"));
    controls.breadcrumb.replaceChildren(el("button", {type: "button", text: "overview", onclick: () => act({v: "overview", s: undefined})}),
      el("span", {text: "/"}), el("button", {type: "button", text: "sessions", onclick: () => act({v: "list", s: undefined})}));
    if (currentState.v === "session") controls.breadcrumb.append(el("span", {text: "/ session"}));
    const labels = {day: "day", how: "weekday/hour", ws: "workspace", sub: "subfolder", model: "model", st: "status"};
    controls.chips.replaceChildren(...Object.entries(labels).filter(([key]) => currentState[key]).map(([key, label]) =>
      el("button", {class: "fchip", type: "button", text: label + ": " + currentState[key] + " ×", "aria-label": "Remove " + label + " filter", onclick: () => act({[key]: undefined})})));
  }
  const lineDiagnosticCategories = new Set(["malformed_lines", "truncated_lines", "recovered_lines"]);
  const countMapDiagnostics = new Set(["unknown_record_types", "claude_unknown_record_types", "opencode_unknown_message_types", "opencode_unknown_content_types", "opencode_requests_without_usage"]);
  function diagnosticCount(key, value) {
    if (lineDiagnosticCategories.has(key)) return value.total;
    if (countMapDiagnostics.has(key)) return Object.values(value).reduce((sum, count) => sum + count, 0);
    if (key === "opencode_rollup_residuals") return Object.keys(value).length;
    if (Array.isArray(value)) return value.length;
    if (typeof value === "number") return value;
    if (typeof value === "boolean") return Number(value);
    return 0;
  }
  function diagnosticItems(key, value) {
    if (lineDiagnosticCategories.has(key)) return value.files;
    if (countMapDiagnostics.has(key)) return Object.entries(value).map(([type, count]) => type + ": " + count);
    if (key === "opencode_rollup_residuals") return Object.values(value);
    return Array.isArray(value) ? value : [value];
  }
  function diagnosticText(value) {
    if (typeof value === "string") return value;
    if (Array.isArray(value)) return value.map(diagnosticText).join(", ");
    if (value && typeof value === "object") return Object.entries(value).map(([key, entry]) => key + ": " + diagnosticText(entry)).join(" · ");
    return String(value);
  }
  const openFooterPanels = new Set();
  function footerPanel(key, props, ...children) {
    const summary = children[0];
    const row = el("details", props, ...children);
    row.open = openFooterPanels.has(key);
    let wasOpen = row.open;
    row.addEventListener("toggle", () => {
      if (!row.isConnected) return;
      if (row.open) openFooterPanels.add(key);
      else openFooterPanels.delete(key);
      if (wasOpen && !row.open) returnTo(row, summary);
      wasOpen = row.open;
    });
    row.append(el("button", {type: "button", class: "followup-toggle", "data-details-close": "", text: "hide", onclick: () => {
      openFooterPanels.delete(key);
      row.open = false;
      wasOpen = false;
      returnTo(row, summary);
    }}));
    return row;
  }
  function renderFooter() {
    const footer = document.getElementById("colophon-footer");
    for (const row of footer.querySelectorAll("details")) {
      const key = row.dataset.diagnostic || "opencode_databases";
      if (row.open) openFooterPanels.add(key);
      else openFooterPanels.delete(key);
    }
    const diagnostic = data.diagnostics;
    const rows = Object.entries(diagnostic).filter(([key, value]) => key !== "page_size_bytes" && diagnosticCount(key, value) > 0).map(([key, value]) => {
      const items = diagnosticItems(key, value);
      const row = el("div", {},
        el("summary", {text: key.replace(/_/g, " ") + " · " + diagnosticCount(key, value)}),
        el("ul", {}, ...items.map(item => el("li", {text: diagnosticText(item)}))));
      if (key === "unknown_record_types") row.append(el("p", {text: "Codex's log format may have changed"}));
      if (key === "claude_unknown_record_types") row.append(el("p", {text: "Claude's log format may have changed"}));
      const explanations = {
        opencode_schema_errors: "OpenCode database schema is unsupported; these databases were skipped.",
        opencode_untested_schema: "OpenCode schema is newer than the tested version; structural checks passed, but the format is untested.",
        opencode_unknown_message_types: "OpenCode's message format may have changed; unknown messages are not interpreted.",
        opencode_unknown_content_types: "OpenCode's content format may have changed; unknown parts are not interpreted.",
        opencode_requests_without_usage: "Requests without usable token usage, including explicit zero usage. No tokens are inferred from session totals.",
        opencode_cost_without_tokens: "Recorded cost is retained without inventing tokens or a model for these requests.",
        opencode_rollup_residuals: "Positive session totals remaining after message usage. Session-start dating is a display convention; it does not establish title, compaction or revert ownership or an event date. Null cost remains unknown.",
        opencode_rollup_shortfalls: "Message usage exceeds session totals. Usage is preserved, never subtracted; session-start dating is a display convention."
      };
      if (explanations[key]) row.append(el("p", {text: explanations[key]}));
      if (key === "untimed_usage") row.append(el("p", {text: "priced at current rates: usage has no timestamp"}));
      if (key === "page_size_over_limit") row.append(el("p", {text: "page size: " + diagnostic.page_size_bytes + " bytes"}));
      return footerPanel(key, {"data-diagnostic": key}, ...row.childNodes);
    });
    const databases = data.meta.sources?.opencode?.databases || [];
    const overflow = costAggregateFailures();
    footer.replaceChildren(el("p", {"data-version": "", text: "colophon " + data.meta.version}), el("p", {text: "API-equivalent estimate (not billed) · OpenCode catalog estimates (not invoices)"}),
      ...(currentState.src === "all" ? PROVIDERS.filter(provider => sourceMissing(provider)).map(provider => el("p", {text: sourceAbsence(provider)})) : []),
      ...tokenBoundaryNote(),
      ...(databases.length ? [footerPanel("opencode_databases", {"data-opencode-databases": ""}, el("summary", {text: "OpenCode database details · " + databases.length}), el("ul", {}, ...databases.map(db => el("li", {text: diagnosticText(db)}))))] : []),
      ...(overflow.length ? [el("p", {"data-cost-aggregate": "", text: "cost aggregate unavailable: " + overflow.join("; ") + ". Finite costs exceed the supported sum; valid individual costs are preserved."})] : []),
      ...(rows.length ? [el("h2", {class: "section-label", text: "// diagnostics"}), ...rows] : []));
  }
  function tokenBoundaryNote() {
    const boundary = data.meta.sources?.claude?.token_data_from_ms;
    if (!["all", "claude"].includes(currentState.src) || !validMs(boundary)) return [];
    const days = calendar(data.sessions, currentState, data.meta.generated_at_ms);
    return days.length && boundary > parseDay(days[0].day) ? [el("p", {"data-token-boundary": "", text: "Claude token data starts " + localStamp(boundary)})] : [];
  }
  const sourceMissing = provider => data.meta.sources?.[provider] && data.meta.sources[provider].status !== "ok";
  function sourceAbsence(provider) {
    const source = data.meta.sources?.[provider];
    if (source?.status === "disabled") return PROVIDER_NAMES[provider] + " disabled by --no-" + provider;
    if (provider === "opencode") {
      const databases = source?.databases || [];
      if (["unsupported", "unreadable"].includes(source?.status)) return "OpenCode " + source.status + ": " + databases.filter(db => db.reason).map(db => db.path + ": " + db.reason).join(" · ");
      return "No OpenCode data found. Checked " + [...databases.map(db => db.path), source?.data_dir].filter(Boolean).join(", ");
    }
    if (provider === "claude") return source?.status === "disabled" ? "Claude disabled by --no-claude" : "No Claude data found. Checked " + [...(source?.roots || []), source?.history_path].filter(Boolean).join(", ");
    return "No Codex sessions found in " + (source?.home || data.meta.codex_home);
  }
  // --- views/overview
  let calendarMetric = "sessions", workspaceMetric = "active_ms", expandedWorkspaces = false;
  const countText = value => new Intl.NumberFormat(undefined, {maximumFractionDigits: 1, notation: value >= 10000 ? "compact" : "standard"}).format(value);
  const durationText = value => value === null ? "unknown" : value >= 3600000 ? (value / 3600000).toFixed(1) + "h" : value >= 60000 ? (value / 60000).toFixed(1) + "m" : (value / 1000).toFixed(1) + "s";
  const costText = value => quantity(value) ? "$" + value.toFixed(2) : "costs unavailable";
  function costAggregateFailures() {
    const now = data.meta.generated_at_ms, failures = [];
    const check = (state, context) => {
      const {window, rows, agents} = scope(data.sessions, state, now), sums = new Map();
      for (const row of [...rows, ...agents]) for (const bucket of windowBuckets(row, window)) {
        if (bucket[8] === null) continue;
        for (const key of ["total", "day " + localDayKey(bucket[0] * 900000), "model " + bucket[1]]) {
          sums.set(key, addCost(sums.has(key) ? sums.get(key) : 0, bucket[8]));
        }
      }
      for (const [key, value] of sums) if (value === null) failures.push(context + " " + key);
    };
    check(currentState, currentState.src === "all" ? "all providers" : PROVIDER_NAMES[currentState.src]);
    if (currentState.src === "all") for (const src of PROVIDERS) check({...currentState, src}, PROVIDER_NAMES[src]);
    if (currentState.s) {
      const row = data.sessions.find(row => row.id === currentState.s) || data.subagents[currentState.s];
      if (row && evidenceSum([row, ...descendants(row, data.subagents, currentState)].map(item => item.own_usage.cost_usd).filter(value => value !== null), true) === null) failures.push("reader " + row.id);
    }
    return failures;
  }
  const metricText = (key, value) => ["active_ms", "agent_ms"].includes(key) ? durationText(value) : key === "cost" ? costText(value) : countText(value);
  function drill(patch) {act({v: "list", s: undefined, ...patch});}
  function panel(name, ...children) {return el("section", {class: "overview-panel"}, el("h2", {class: "section-label", text: "// " + name}), ...children);}
  function levels(values) {
    const positive = values.filter(value => value > 0).sort((a, b) => a - b);
    const cuts = [.25, .5, .75].map(q => positive[Math.ceil(positive.length * q) - 1]);
    return values.map(value => value <= 0 ? 0 : 1 + cuts.filter(cut => value > cut).length);
  }
  function renderKpis(now) {
    const totals = kpis(data.sessions, currentState, now), window = periodWindow(currentState.p, now, currentState);
    const shares = Object.fromEntries(PROVIDERS.map(src => [src, kpis(data.sessions, {...currentState, src}, now)]));
    const previous = previousWindow(currentState.p, window, now, currentState);
    const prior = previous ? kpis(data.sessions, {...currentState, _window: previous}, now) : null;
    const labels = {sessions: "sessions", active_ms: "your active time", agent_ms: "agent time", turns: "turns", tokens: "tokens", cost: "estimated cost", aborted: "aborted turns"};
    const sorts = {sessions: "newest", active_ms: "longest", agent_ms: "subtime", turns: "newest", tokens: "tokens", cost: "cost", aborted: "newest"};
    return el("div", {class: "kpis"}, ...Object.entries(labels).map(([key, label]) => {
      const value = key === "cost" ? availableCostText(totals[key], totals.unpriced, scopedCostRows(now)) : metricText(key, totals[key]);
      const open = () => drill({sort: sorts[key], ...(key === "aborted" ? {st: "aborted"} : {})});
      const tile = el("article", {class: "kpi" + (key === "aborted" ? " warning" : ""), "data-kpi": key,
        onclick: event => {if (!event.target.closest("button")) open();}},
        el("button", {type: "button", class: "kpi-main", onclick: () => drill({sort: sorts[key], ...(key === "aborted" ? {st: "aborted"} : {})})},
          el("span", {class: "kpi-label", text: label}), el("span", {class: "kpi-value", "data-value": totals[key], text: value})));
      if (key === "cost" && value.includes(" · ")) {
        const [amount, ...notes] = value.split(" · ");
        tile.querySelector(".kpi-value").replaceChildren(el("span", {text: amount}), el("span", {class: "cost-note", text: " · " + notes.join(" · ")}));
      }
      const providers = currentState.src === "all" ? PROVIDERS : [currentState.src];
      // Scale before summing shares: individually finite costs may overflow their sum.
      const maximum = Math.max(0, ...providers.map(provider => shares[provider][key] || 0));
      const shareTotal = maximum ? providers.reduce((sum, provider) => sum + (shares[provider][key] || 0) / maximum, 0) : 0;
      tile.append(el("div", {class: "provider-shares", "aria-label": "Provider share"}, ...providers.map(provider =>
        el("span", {"data-provider": provider, "data-share": shares[provider][key], title: PROVIDER_NAMES[provider] + ": " + metricText(key, shares[provider][key]), style: "width:" + (shareTotal ? (shares[provider][key] || 0) / maximum / shareTotal * 100 : 0) + "%"}))));
      if (key === "turns") tile.append(el("p", {class: "kpi-sub", text: "avg " + durationText(totals.average_ms)}));
      if (key === "tokens") tile.append(el("p", {class: "kpi-sub", text: totals.cached_share === null ? "cached input: unknown" : (totals.cached_share * 100).toFixed(1) + "% cached input"}));
      if (key === "cost") tile.append(el("p", {class: "kpi-sub", text: "API-equivalent estimate (not billed)"}));
      if (key === "aborted") tile.append(el("div", {class: "kpi-sub"},
        el("button", {type: "button", class: "status-link", "data-status": "interrupted", text: totals.interrupted + " interrupted", onclick: () => drill({st: "interrupted", sort: "newest"})}),
        el("span", {text: " · "}), el("button", {type: "button", class: "status-link", "data-status": "abandoned", text: totals.abandoned + " abandoned", onclick: () => drill({st: "abandoned", sort: "newest"})})));
      if (totals.live[key]) tile.append(el("p", {class: "live", text: "LIVE · includes " + totals.live[key] + " running"}));
      if (prior && (key !== "cost" || (totals.cost !== null && prior.cost !== null && costAvailability(scopedCostRows(now)).complete && costAvailability(scopedCostRows(now, {...currentState, _window: previous})).complete))) {
        const delta = totals[key] - prior[key];
        tile.append(el("p", {class: "kpi-delta", "data-value": delta, text: (delta >= 0 ? "▲ " : "▼ ") + metricText(key, Math.abs(delta)) + " " + comparisonText(previous)}));
      }
      return tile;
    }));
  }
  function renderCalendar(now) {
    const days = calendar(data.sessions, currentState, now), ramp = levels(days.map(day => day[calendarMetric]));
    const byProvider = Object.fromEntries(PROVIDERS.map(src => [src, new Map(calendar(data.sessions, {...currentState, src}, now).map(day => [day.day, day]))]));
    const toggle = el("div", {class: "metric-toggle"}, ...[["sessions", "sessions"], ["active_ms", "active time"], ["tokens", "tokens"], ["cost", "cost"]].map(([key, label]) =>
      el("button", {type: "button", text: label, "aria-label": "Calendar " + label, "aria-pressed": key === calendarMetric, onclick: () => {calendarMetric = key; render();}})));
    const grid = el("div", {class: "calendar-grid"});
    const offset = days.length ? mondayIndex(parseDay(days[0].day)) : 0;
    for (let n = 0; n < offset; n++) grid.append(el("span", {class: "heat-cell blank"}));
    days.forEach((day, n) => {
      const value = calendarMetric === "cost" ? availableCostText(day.cost, day.unpriced, day.providers) : metricText(calendarMetric, day[calendarMetric]);
      const provider = currentState.src === "all" ? PROVIDERS.reduce((best, src) => (byProvider[src].get(day.day)?.[calendarMetric] || 0) > (byProvider[best].get(day.day)?.[calendarMetric] || 0) ? src : best, PROVIDERS[0]) : currentState.src;
      grid.append(el("button", {type: "button", class: "heat-cell", "data-day": day.day, "data-value": day[calendarMetric], "data-level": ramp[n],
        "data-provider": provider,
        title: day.day + " · " + value, "aria-label": day.day + " · " + value, onclick: () => drill({day: day.day})}));
    });
    const viewport = el("div", {class: "calendar-viewport"}, grid);
    const result = panel("calendar", el("div", {class: "panel-head"}, toggle), viewport,
      el("div", {class: "heat-legend"}, el("span", {text: days.length ? days[0].day + " — " + days[days.length - 1].day : "No activity"}),
        el("span", {text: "less"}), ...Array.from({length: 5}, (_, n) => el("span", {class: "heat-cell", "data-level": n})), el("span", {text: "more"})));
    if (calendarMetric === "cost") result.append(el("p", {class: "panel-meta", text: "API-equivalent estimate (not billed)"}));
    return result;
  }
  function fitCalendar() {
    const viewport = document.querySelector(".calendar-viewport"), grid = document.querySelector(".calendar-grid");
    if (!viewport || !grid) return;
    const weeks = Math.ceil(grid.children.length / 7), width = viewport.clientWidth;
    const size = Math.max(9, Math.min(13, weeks ? (width + 3) / weeks - 3 : 13));
    grid.style.setProperty("--cell-size", size + "px");
    if (weeks * (size + 3) - 3 > width) {
      viewport.setAttribute("data-scroll-region", "calendar");
      viewport.scrollLeft = viewport.scrollWidth;
    } else viewport.removeAttribute("data-scroll-region");
  }
  function renderHours(now) {
    const cells = hourWeekday(data.sessions, currentState, now), ramp = levels(cells.flat()), grid = el("div", {class: "hour-grid"});
    grid.append(el("span", {class: "axis"}));
    for (let hour = 0; hour < 24; hour++) grid.append(el("span", {class: "axis", text: hour % 3 === 0 ? hour : ""}));
    ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].forEach((day, index) => {
      grid.append(el("span", {class: "axis", text: day}));
      cells[index].forEach((value, hour) => grid.append(el("button", {class: "heat-cell", type: "button", "data-how": index + "-" + hour,
        "data-level": ramp[index * 24 + hour], title: day + " " + hour + ":00 · " + value + " turns", "aria-label": day + " " + hour + ":00 · " + value + " turns",
        onclick: () => drill({how: index + "-" + hour})})));
    });
    return panel("hour × weekday", grid);
  }
  const WORKSPACE_PREVIEW = 6;
  const workspaceName = key => (data.workspaces[key] || {}).name || key || "unknown workspace";
  function renderWorkspaces(now) {
    const rows = workspaces(data.sessions, currentState, now).sort((a, b) => b[workspaceMetric] - a[workspaceMetric] || String(a.key).localeCompare(String(b.key)));
    const byProvider = Object.fromEntries(PROVIDERS.map(src => [src, new Map(workspaces(data.sessions, {...currentState, src}, now).map(row => [row.key, row]))]));
    const maximum = rows.length ? rows[0][workspaceMetric] : 0;
    const setExpanded = expanded => {
      expandedWorkspaces = expanded;
      render();
      const anchor = document.querySelector("[data-workspaces]");
      const control = anchor.querySelector("[data-workspace-scope][aria-pressed='true']");
      if (expanded) control.focus({preventScroll: true});
      else returnTo(anchor, control);
    };
    const metrics = el("div", {class: "metric-toggle"}, ...[["active_ms", "time"], ["tokens", "tokens"]].map(([key, label]) =>
      el("button", {type: "button", text: label, "aria-label": "Workspaces " + label, "aria-pressed": workspaceMetric === key, onclick: () => {workspaceMetric = key; render();}})));
    const head = el("div", {class: "panel-head"}, metrics);
    if (rows.length > WORKSPACE_PREVIEW) head.append(el("div", {class: "metric-toggle"}, ...[[false, "top " + WORKSPACE_PREVIEW], [true, "all " + rows.length]].map(([expanded, label]) =>
      el("button", {type: "button", text: label, "data-workspace-scope": "", "aria-label": "Workspaces " + label, "aria-pressed": expandedWorkspaces === expanded, onclick: () => setExpanded(expanded)}))));
    const result = panel("workspaces", head,
      ...rows.slice(0, expandedWorkspaces ? rows.length : WORKSPACE_PREVIEW).map(row => el("button", {type: "button", class: "bar-row", "data-workspace": row.key, title: workspaceName(row.key), onclick: () => drill({ws: row.key})},
        el("span", {class: "bar-label", text: workspaceName(row.key), title: workspaceName(row.key)}),
        el("span", {class: "bar-track"}, ...workspaceFills(row, maximum, byProvider)),
        el("span", {class: "bar-number", "data-value": row[workspaceMetric], text: metricText(workspaceMetric, row[workspaceMetric])}))));
    result.setAttribute("data-workspaces", "");
    if (rows.length > WORKSPACE_PREVIEW) result.append(el("button", {class: "expand-workspaces", type: "button", text: expandedWorkspaces ? "show top " + WORKSPACE_PREVIEW : "+ " + (rows.length - WORKSPACE_PREVIEW) + " more", onclick: () => setExpanded(!expandedWorkspaces)}));
    return result;
  }
  function workspaceFills(row, maximum, byProvider) {
    const providers = currentState.src === "all" ? PROVIDERS : [currentState.src];
    const total = providers.reduce((sum, provider) => sum + (byProvider[provider].get(row.key)?.[workspaceMetric] || 0), 0);
    return providers.map(provider => {
      const value = byProvider[provider].get(row.key)?.[workspaceMetric] || 0;
      return el("span", {class: "bar-fill", "data-provider": provider, title: provider + ": " + metricText(workspaceMetric, value), style: "width:" + (maximum && total ? row[workspaceMetric] / maximum * value / total * 100 : 0) + "%"});
    });
  }
  function rateTooltip(model, now) {
    const {window, rows, agents} = scope(data.sessions, currentState, now), refs = new Map();
    const matching = [...rows, ...agents].filter(row => windowBuckets(row, window).some(bucket => bucket[1] === model));
    if (!costAvailability(matching).any) return "costs unavailable";
    let unpriced = false, unknown = false, recordedEstimate = false, rateBased = false;
    for (const row of [...rows, ...agents]) {
      const buckets = windowBuckets(row, window).filter(bucket => bucket[1] === model);
      if (!buckets.length) continue;
      unpriced ||= buckets.some(bucket => bucket[8] === null);
      if (providerOf(row) === "opencode") {recordedEstimate = true; continue;}
      rateBased = true;
      const recorded = row.own_usage.priced_by;
      if (!recorded.length) unknown = true;
      for (const ref of recorded) {
        const [key, index, role] = ref, pricing = data.models[key];
        const period = pricing && Number.isInteger(index) && index >= 0 ? pricing.periods[index] : null;
        if (!period || !["rates", "priority", "fast"].includes(role) || (period.effective_from_ms !== null && !validMs(period.effective_from_ms))) {unknown = true; continue;}
        const override = /^catalog:([^|]+)\|([^|]+)$/.exec(key);
        const label = override ? override[1] + " (catalog rate used for priority turns of " + override[2] + ")\n" : "";
        const effective = period.effective_from_ms === null ? (period.source === "curated" ? "initial" : "unknown") : new Date(period.effective_from_ms).toISOString();
        refs.set(JSON.stringify(ref), label + key + " · " + role + " · effective_from: " + effective + " · source: " + period.source);
      }
    }
    return [...(rateBased ? ["Recorded rate periods in matching sessions (all dates)"] : []), ...(recordedEstimate ? ["OpenCode catalog estimate (not an invoice; recorded by OpenCode)"] : []), ...refs.values(),
      ...(unknown || (rateBased && !refs.size) ? ["rate period unknown"] : []), ...(unpriced ? ["unpriced"] : []), ...costAvailability(matching).unavailable.map(provider => provider + " costs unavailable")].join("\n");
  }
  function renderModels(now) {
    return panel("models", ...models(data.sessions, currentState, now).map(row => el("button", {class: "model-row", type: "button", "data-provider": row.providers.length === 1 ? row.providers[0] : "all", "data-model": row.model, title: rateTooltip(row.model, now), onclick: () => drill({model: row.model})},
      el("span", {class: "model-name", text: row.model, title: row.model}), el("span", {text: countText(row.tokens)}),
      el("span", {class: row.unpriced ? "warning" : "", text: availableCostText(row.cost, row.unpriced, row.providers)}))),
      el("p", {class: "panel-meta", text: "API-equivalent estimate (not billed)"}));
  }
  function renderNotable(now) {
    const items = notable(data.sessions, currentState, now);
    const entry = (key, label, text, patch) => el("button", {class: "notable-row", type: "button", "data-notable": key, onclick: () => drill(patch)},
      el("span", {text: label}), el("span", {class: "notable-value", text}));
    return panel("notable",
      ...(items.busiest ? [entry("busiest", "busiest day", items.busiest.day + " · " + items.busiest.sessions + " sessions", {day: items.busiest.day})] : []),
      ...(items.active ? [entry("active", "longest active day", items.active.day + " · " + durationText(items.active.active_ms), {day: items.active.day, sort: "longest"})] : []),
      ...(items.fanout ? [entry("fanout", "biggest subagent fan-out", items.fanout.count + " subagents", {v: "session", s: items.fanout.id})] : []),
      ...(items.streak ? [entry("streak", "longest streak", items.streak.count + " days · " + items.streak.from + " — " + items.streak.to, {p: "custom", from: items.streak.from, to: items.streak.to, day: undefined})] : []));
  }
  function renderRecent(now) {
    const result = panel("recent sessions");
    result.classList.add("recent-panel");
    const list = el("div", {"data-recent": ""});
    for (const row of recent(data.sessions, currentState, now)) {
      const own = activeMs(turnIntervals(row, periodWindow(currentState.p, now, currentState))), agents = descendants(row, data.subagents, currentState).length;
      list.append(el("div", {class: "recent-row", "data-session-id": row.id, "data-provider": providerOf(row),
        onclick: event => {if (!event.target.closest("button")) act({v: "session", s: row.id});}},
        el("span", {class: "recent-time", text: validMs(row.start_ms) ? localStamp(row.start_ms).slice(5) : "unknown"}),
        el("button", {class: "session-title", type: "button", text: row.title + (row.archived ? " · " + archiveLabel(row) : "") + (row.history_only ? " · HISTORY ONLY" : ""), title: row.title_full, onclick: () => act({v: "session", s: row.id})}),
        el("span", {class: "recent-workspace", text: workspaceName(row.workspace), title: workspaceName(row.workspace)}), el("span", {class: "recent-metrics", text: durationText(own) + " · " + agents + " subagents", title: durationText(own) + " · " + agents + " subagents"})));
    }
    result.append(list, el("button", {type: "button", class: "view-all", "data-view-all": "", text: "view all " + scope(data.sessions, currentState, now).rows.length + " →", onclick: () => drill({sort: "newest"})}));
    return result;
  }
  function renderOverview() {
    const now = data.meta.generated_at_ms;
    return [renderKpis(now), el("div", {class: "overview-grid"}, renderCalendar(now), renderWorkspaces(now), renderHours(now), renderModels(now), renderNotable(now), renderRecent(now))];
  }
  // --- views/list
  const wholeWindow = {from: -Infinity, to: Infinity};
  const quantity = value => typeof value === "number" && Number.isFinite(value) && value >= 0;
  const usageTokens = usage => evidenceSum([usage.input, usage.output]);
  const tokenText = usage => {const tokens = usageTokens(usage); return tokens === null ? "unknown" : countText(tokens);};
  const workspaceLine = row => workspaceName(row.workspace) + (row.subfolder ? " › " + row.subfolder : "");
  const timeOnly = ms => validMs(ms) ? localStamp(ms).slice(-5) : "unknown";
  function flagsLine(row) {
    return el("div", {class: "row-flags"}, ...(row.history_only ? [el("span", {class: "tag", text: "HISTORY ONLY"})] : []), ...(row.archived ? [el("span", {class: "tag", text: archiveLabel(row)})] : []),
      ...row.flags.map(flag => el("span", {class: flag === "live" ? "live" : "warning", text: flag === "live" ? "LIVE" : flag.replace(/_/g, " ")})));
  }
  const archiveLabel = row => row.archive_reason === "project" ? "ARCHIVED (PROJECT)" : "ARCHIVED";
  function listFigures(row) {
    const window = periodWindow(currentState.p, data.meta.generated_at_ms, currentState), children = descendants(row, data.subagents, currentState);
    const buckets = [row, ...children].flatMap(item => windowBuckets(item, window));
    return {active: activeMs(turnIntervals(row, window)), agents: children.length,
      subtime: children.reduce((sum, child) => sum + activeMs(turnIntervals(child, window)), 0),
      tokens: buckets.reduce((sum, bucket) => sum + bucket[3] + bucket[6], 0),
      cost: costAvailability([row, ...children]).any ? bucketCosts(buckets) : null,
      providers: [row, ...children].map(providerOf),
      unpriced: buckets.some(bucket => bucket[8] === null)};
  }
  // The dragged list width survives rerenders and reloads; storage may be unavailable.
  // RIGHT_MIN is the room kept for the splitter, its gaps and the reader.
  const LIST_WIDTH_KEY = "colophon.sessionListWidth", LIST_MIN = 300, RIGHT_MIN = 360;
  let listWidth = (() => {
    try { const value = Number(localStorage.getItem(LIST_WIDTH_KEY)); return Number.isFinite(value) && value > 0 ? value : null; } catch { return null; }
  })();
  function applyListWidth(layout) {
    if (listWidth) layout.style.setProperty("--list-width", "clamp(" + LIST_MIN + "px, " + Math.round(listWidth) + "px, calc(100% - " + RIGHT_MIN + "px))");
    else layout.style.removeProperty("--list-width");
  }
  function saveListWidth() {
    try { if (listWidth) localStorage.setItem(LIST_WIDTH_KEY, String(Math.round(listWidth))); else localStorage.removeItem(LIST_WIDTH_KEY); } catch {}
  }
  function renderSplitter() {
    const splitter = el("div", {class: "list-splitter", role: "separator", tabindex: "0", "aria-orientation": "vertical",
      "aria-label": "Resize session list", title: "Drag to resize · double-click to reset"});
    const layoutOf = () => splitter.parentElement;
    const listOf = () => layoutOf().querySelector(".session-list");
    const resize = width => {
      const bounds = layoutOf().getBoundingClientRect();
      listWidth = Math.max(LIST_MIN, Math.min(width, bounds.width - RIGHT_MIN));
      applyListWidth(layoutOf());
      splitter.setAttribute("aria-valuenow", Math.round(listOf().getBoundingClientRect().width));
      fitReader();
    };
    // The list edge follows the pointer from where it grabbed the splitter.
    let grab = 0;
    splitter.addEventListener("pointerdown", event => {
      event.preventDefault();
      grab = event.clientX - listOf().getBoundingClientRect().right;
      splitter.setPointerCapture(event.pointerId);
      splitter.classList.add("dragging");
    });
    splitter.addEventListener("pointermove", event => {
      if (splitter.hasPointerCapture(event.pointerId)) resize(event.clientX - grab - layoutOf().getBoundingClientRect().left);
    });
    const finish = event => {
      if (!splitter.hasPointerCapture(event.pointerId)) return;
      splitter.releasePointerCapture(event.pointerId);
      splitter.classList.remove("dragging");
      saveListWidth();
    };
    splitter.addEventListener("pointerup", finish);
    splitter.addEventListener("pointercancel", finish);
    splitter.addEventListener("dblclick", () => {listWidth = null; applyListWidth(layoutOf()); saveListWidth(); fitReader();});
    splitter.addEventListener("keydown", event => {
      const step = event.shiftKey ? 96 : 24, current = listOf().getBoundingClientRect().width;
      if (event.key === "ArrowLeft") resize(current - step);
      else if (event.key === "ArrowRight") resize(current + step);
      else return;
      event.preventDefault();
      saveListWidth();
    });
    return splitter;
  }
  function renderSessionList(rows) {
    const figures = new Map(rows.map(row => [row.id, listFigures(row)]));
    const newest = (a, b) => (validMs(b.start_ms) ? b.start_ms : -Infinity) - (validMs(a.start_ms) ? a.start_ms : -Infinity) || a.id.localeCompare(b.id);
    const ranked = [...rows].sort((a, b) => {
      const key = {longest: "active", subtime: "subtime", tokens: "tokens", cost: "cost"}[currentState.sort];
      return key ? (figures.get(b.id)[key] ?? -Infinity) - (figures.get(a.id)[key] ?? -Infinity) || newest(a, b) : newest(a, b);
    });
    const result = el("section", {class: "session-list", "data-session-list": ""},
      el("div", {class: "list-sort", "aria-label": "Sort sessions"}, ...[["newest", "newest"], ["longest", "longest"], ["subtime", "subagent time"], ["tokens", "tokens"], ["cost", "cost"]].map(([key, text]) =>
        el("button", {type: "button", text, "aria-pressed": currentState.sort === key, onclick: () => act({sort: key})}))));
    let previousDay;
    for (const row of ranked) {
      const day = localDayKey(row.start_ms), figuresForRow = figures.get(row.id);
      if (currentState.sort === "newest" && day !== previousDay) {
        const date = validMs(row.start_ms) ? new Date(row.start_ms) : null;
        const label = date ? ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"][date.getDay()] + " " +
          ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"][date.getMonth()] + " " + date.getDate() : "UNKNOWN DAY";
        result.append(el("h3", {class: "day-header", "data-day-header": day || "unknown", text: label}));
        previousDay = day;
      }
      const open = () => act({v: "session", s: row.id});
      const figuresText = currentState.sort === "tokens" ? countText(figuresForRow.tokens) + " tokens" : currentState.sort === "cost" ?
        (figuresForRow.cost === null ? "costs unavailable" : availableCostText(figuresForRow.cost, figuresForRow.unpriced, figuresForRow.providers)) :
        currentState.sort === "subtime" ? durationText(figuresForRow.subtime) + " agent" : null;
      result.append(el("div", {class: "list-row" + (row.id === currentState.s ? " selected" : ""), "data-list-row": "", "data-session-id": row.id, "data-provider": providerOf(row),
        role: "button", tabindex: "0", "aria-label": "Open session " + row.title,
        onkeydown: event => {if (event.target === event.currentTarget && ["Enter", " "].includes(event.key)) {event.preventDefault(); open();}},
        onclick: event => {if (!event.target.closest("button")) open();}},
        el("span", {class: "list-time", text: timeOnly(row.start_ms)}),
        el("div", {class: "list-main"}, el("button", {type: "button", class: "session-title", title: row.title_full, text: row.title, onclick: open}),
          el("p", {class: "list-workspace", text: workspaceLine(row), title: workspaceLine(row)}), flagsLine(row)),
        el("div", {class: "list-metrics", "data-active-ms": figuresForRow.active, "data-tokens": figuresForRow.tokens, "data-cost": figuresForRow.cost,
          title: currentState.sort === "cost" ? "API-equivalent estimate (not billed)" : undefined},
          el("span", {text: durationText(figuresForRow.active)}), el("span", {class: "list-subcount", text: figuresForRow.agents + " sub"}),
          ...(figuresText ? [el("span", {text: figuresText})] : []))));
    }
    if (!ranked.length) result.append(el("p", {class: "empty-state", text: "No sessions match the active filters"}));
    return result;
  }
  // --- views/reader
  const shellArgument = value => "'" + value.replace(/'/g, "'\\''") + "'";
  function ownActive(row) {
    if (row.flags.includes("history_unresolved")) return null;
    const eligible = row.turns.filter(turn => ["completed", "aborted", "interrupted", "running"].includes(turn.status));
    if (eligible.some(turn => !validMs(turn.start_ms) || !validMs(turn.end_ms) || turn.end_ms < turn.start_ms || !quantity(turn.duration_ms))) return null;
    return activeMs(turnIntervals(row, wholeWindow));
  }
  function readerUsage(rows) {
    const tokens = rows.map(row => usageTokens(row.own_usage)), costs = rows.map(row => row.own_usage.cost_usd);
    return {tokens: evidenceSum(tokens), cost: evidenceSum(costs, true),
      cost_overflow: evidenceSum(costs.filter(value => value !== null), true) === null,
      unpriced: rows.some(row => row.own_usage.unpriced_tokens > 0)};
  }
  function usageCostText(usage, provider = usageProviders.get(usage) || "codex") {
    if (!providerCosts(provider).available || usage.cost_overflow) return "costs unavailable";
    return (quantity(usage.cost_usd) ? costText(usage.cost_usd) : "unknown") + (usage.unpriced_tokens > 0 ? " + unpriced" : "");
  }
  function usageRateTooltip(usages) {
    const availability = costAvailability(usages.map(usage => usageProviders.get(usage) || "codex"));
    if (!availability.any) return "costs unavailable · API-equivalent estimate (not billed)";
    const refs = new Map();
    let unknown = false, recordedEstimate = false, rateBased = false;
    for (const usage of usages) {
      if (usageProviders.get(usage) === "opencode") {recordedEstimate = true; continue;}
      rateBased = true;
      if (usageTokens(usage) > 0 && !usage.priced_by.length) unknown = true;
      for (const ref of usage.priced_by) {
        const [key, index, role] = ref, pricing = data.models[key];
        const period = pricing && Number.isInteger(index) && index >= 0 ? pricing.periods[index] : null;
        if (!period || !["rates", "priority", "fast"].includes(role) || (period.effective_from_ms !== null && !validMs(period.effective_from_ms))) {unknown = true; continue;}
        const effective = period.effective_from_ms === null ? (period.source === "curated" ? "initial" : "unknown") : new Date(period.effective_from_ms).toISOString();
        const override = /^catalog:([^|]+)\|([^|]+)$/.exec(key);
        refs.set(JSON.stringify(ref), (override ? override[1] + " (catalog rate used for priority turns of " + override[2] + ")\n" : "") + key + " · " + role + " · effective_from: " + effective + " · source: " + period.source);
      }
    }
    return ["API-equivalent estimate (not billed)", ...(recordedEstimate ? ["OpenCode catalog estimate (not an invoice; recorded by OpenCode)"] : []), ...refs.values(), ...(unknown || (rateBased && !refs.size) ? ["rate period unknown"] : []), ...(usages.some(usage => usage.unpriced_tokens > 0 || usage.cost_usd === null) ? ["unpriced"] : []), ...availability.unavailable.map(provider => provider + " costs unavailable")].join("\n");
  }
  function expandableText(text) {
    const paragraph = el("p", {class: "long-text", "data-long-text": "", text, title: text});
    const toggle = () => {
      const expanded = paragraph.classList.toggle("expanded");
      button.textContent = expanded ? "show less" : "show more";
      button.setAttribute("aria-expanded", String(expanded));
      top.hidden = !expanded || !exceedsViewport(paragraph);
      if (!expanded) returnTo(wrap, button);
    };
    const top = el("button", {type: "button", class: "text-expander", "data-text-collapse-top": "", hidden: "", text: "show less", onclick: toggle});
    const button = el("button", {type: "button", class: "text-expander", "data-text-toggle": "", text: "show more", "aria-expanded": "false", onclick: toggle});
    const wrap = el("div", {"data-expandable-text": ""}, top, paragraph, button);
    return wrap;
  }
  function renderRequest(request) {
    const tags = [];
    if (request.kind === "command") tags.push("command");
    if (request.kind === "voice") tags.push("voice request");
    if (request.kind === "answer") tags.push("answer");
    if (request.images) tags.push("+ " + request.images + " images");
    if (request.time_unreliable) tags.push("uncertain timing");
    return el("div", {class: "request", "data-request": ""}, ...(tags.length ? [el("div", {class: "request-meta", text: tags.join(" · ")})] : []), expandableText(request.text));
  }
  function renderTools(tools) {
    const chips = [];
    for (const [key, label] of [["shell", "shell"], ["file_edits", "file edits"], ["web", "web"], ["image", "image"]]) {
      if (tools[key]) chips.push(el("span", {class: "tool-chip", text: label + " " + tools[key]}));
    }
    if (tools.shell_failed) chips.push(el("span", {class: "tool-chip warning", "data-tool-failure": "", text: tools.shell_failed + " failed"}));
    for (const [name, count] of [...Object.entries(tools.mcp), ...Object.entries(tools.other)]) if (count) chips.push(el("span", {class: "tool-chip", text: name + " " + count}));
    return el("div", {class: "tool-chips", "data-tools": ""}, ...(chips.length ? chips : [el("span", {class: "reader-meta", text: "none recorded"})]));
  }
  function renderAnswer(answer) {
    return el("div", {}, ...(answer.voice ? [el("span", {class: "request-meta", text: "voice reply"})] : []), expandableText(answer.text));
  }
  function renderSubagentRow(child, matched, interaction = false) {
    const mini = el("div", {class: "mini-card", "data-mini-card": "", hidden: ""},
      el("p", {class: "reader-meta", text: localStamp(child.start_ms) + " — " + localStamp(child.end_ms) + " · active " + durationText(ownActive(child))}),
      renderTools(child.tools), el("p", {class: "reader-meta", text: tokenText(child.own_usage) + " tokens · " + usageCostText(child.own_usage), title: usageRateTooltip([child.own_usage])}));
    const answers = child.turns.map(turn => turn.final_answer).filter(Boolean);
    if (answers.length) mini.append(el("h4", {class: "section-label", text: "// final answer"}), renderAnswer(answers[answers.length - 1]));
    const marker = el("span", {text: "▸", "aria-hidden": "true"});
    const button = el("button", {type: "button", class: "subagent-toggle", "aria-label": "Expand " + child.label, "aria-expanded": "false",
      text: (interaction ? "also used: " : "") + child.label + (child.nickname ? " · " + child.nickname : ""), onclick: () => {
        mini.hidden = !mini.hidden; marker.textContent = mini.hidden ? "▸" : "▾";
        button.setAttribute("aria-expanded", String(!mini.hidden)); fitReader();
      }});
    return el("div", {class: "subagent-row" + (matched.has(child.id) ? " matched" : ""), "data-subagent-id": child.id}, marker,
      el("div", {}, button, ...(child.forked ? [el("span", {class: "tag", text: "forked"})] : [])),
      el("span", {class: "subagent-metrics", text: timeOnly(child.start_ms) + " · " + durationText(ownActive(child)) + " · " + tokenText(child.own_usage) + " tokens"}), mini);
  }
  function renderTurn(turn, matched, visibleChildren) {
    const before = turn.requests.filter(request => request.before_turn), requests = turn.requests.filter(request => !request.before_turn);
    const asked = el("section", {class: "turn-section"}, el("h3", {class: "section-label", text: "YOU ASKED · " + requests.length}));
    if (before.length) asked.append(el("div", {class: "before-turn", "data-before-turn": ""}, el("span", {class: "request-meta", text: "before this turn"}), ...before.map(renderRequest)));
    asked.append(...requests.slice(0, 2).map(renderRequest));
    if (requests.length > 2) {
      const extra = el("div", {hidden: ""}, ...requests.slice(2).map(renderRequest));
      const collapsedLabel = "+ " + (requests.length - 2) + " follow-ups sent while it worked", expandedLabel = "hide " + (requests.length - 2) + " follow-ups";
      const toggleState = () => {
        extra.hidden = !extra.hidden;
        toggle.textContent = extra.hidden ? collapsedLabel : expandedLabel;
        toggle.setAttribute("aria-expanded", String(!extra.hidden)); fitReader();
        if (extra.hidden) returnTo(toggle, toggle);
      };
      const toggle = el("button", {type: "button", class: "followup-toggle", text: collapsedLabel, "aria-expanded": "false", onclick: toggleState});
      extra.append(el("button", {type: "button", class: "followup-toggle", "data-followup-collapse": "", text: expandedLabel, onclick: toggleState}));
      asked.append(toggle, extra);
    }
    const card = el("article", {class: "turn-card", "data-turn-card": turn.id},
      el("div", {class: "turn-header", "data-turn-header": ""}, el("span", {class: "turn-number", text: "turn " + turn.n}),
        el("span", {text: timeOnly(turn.start_ms) + " — " + timeOnly(turn.end_ms)}), el("span", {text: durationText(quantity(turn.duration_ms) ? turn.duration_ms : null)}),
        el("span", {text: "first token " + durationText(quantity(turn.ttft_ms) ? turn.ttft_ms : null)}),
        el("span", {text: tokenText(turn.usage) + " tokens"}),
        el("span", {"data-turn-cost": "", text: usageCostText(turn.usage), title: usageRateTooltip([turn.usage])}),
        el("span", {class: turn.status === "running" ? "live" : turn.status === "completed" ? "" : "warning", text: turn.status}),
        ...turn.flags.map(flag => el("span", {class: flag === "live" ? "live" : "warning", text: flag.replace(/_/g, " ")}))), asked,
      el("section", {class: "turn-section"}, el("h3", {class: "section-label", text: "IT USED"}), renderTools(turn.tools)));
    const spawned = [...new Set(turn.spawned)].filter(id => visibleChildren.has(id)), used = [...new Set(turn.used)].filter(id => visibleChildren.has(id) && !spawned.includes(id));
    if (spawned.length || used.length) card.append(el("section", {class: "turn-section"}, el("h3", {class: "section-label", text: "SUBAGENTS · " + spawned.length}),
      ...spawned.map(id => renderSubagentRow(visibleChildren.get(id), matched)), ...used.map(id => renderSubagentRow(visibleChildren.get(id), matched, true))));
    if (turn.final_answer) card.append(el("section", {class: "turn-section"}, el("h3", {class: "section-label", text: "FINAL ANSWER"}), renderAnswer(turn.final_answer)));
    return card;
  }
  function renderTimeline(row, children, matched) {
    const timeline = el("section", {class: "mini-timeline", "data-timeline": "", "aria-label": "Session timeline"});
    if (!validMs(row.start_ms) || !validMs(row.end_ms) || row.end_ms < row.start_ms) {
      timeline.append(el("p", {class: "reader-meta", text: "timeline unavailable: unknown session span"})); return timeline;
    }
    const span = row.end_ms - row.start_ms, positioned = new Set(row.turns.flatMap(turn => [...turn.spawned, ...turn.used]));
    const labels = el("div", {class: "timeline-labels"});
    const lane = (blocks, child = null) => {
      const track = el("div", {class: "timeline-track"}, el("span", {class: "timeline-idle", ...(child ? {} : {"data-timeline-idle": ""})}));
      let hasBlock = false;
      for (const item of blocks) {
        if (!validMs(item.start_ms) || !validMs(item.end_ms) || item.end_ms < item.start_ms || item.end_ms < row.start_ms || item.start_ms > row.end_ms) continue;
        const left = span ? (Math.max(row.start_ms, item.start_ms) - row.start_ms) / span * 100 : 0;
        const width = span ? (Math.min(row.end_ms, item.end_ms) - Math.max(row.start_ms, item.start_ms)) / span * 100 : 0;
        const label = child ? child.label + (child.forked ? " · forked" : "") : "turn " + item.n;
        const block = el("span", {class: "timeline-block" + (child ? " sub" : "") + (child && child.link_method === "inferred" ? " inferred" : ""),
          title: label + " · " + localStamp(item.start_ms) + " — " + localStamp(item.end_ms), style: "left:" + left + "%;width:" + width + "%",
          ...(child ? {"data-timeline-subagent": child.id} : {"data-timeline-turn": item.id})});
        track.append(block);
        hasBlock = true;
        const text = el("span", {class: "timeline-label", "data-timeline-label": "", "data-label-kind": child ? "subagent" : "turn", "data-left": left, title: label},
          el("span", {text: child ? child.label : label}), ...(child && child.forked ? [el("span", {class: "tag", text: "forked"})] : []));
        text._block = block;
        labels.append(text);
      }
      const result = el("div", {class: "timeline-lane" + (child && matched.has(child.id) ? " matched" : ""), "data-timeline-lane": child ? child.id : row.id,
        ...(child && !positioned.has(child.id) ? {"data-subagent-id": child.id} : {})}, track);
      if (child && !hasBlock) result.setAttribute("title", child.label + " · timing unknown or outside session span");
      return result;
    };
    timeline.append(lane(row.turns), ...children.map(child => lane([child], child)), labels,
      el("div", {class: "timeline-ticks"}, ...Array.from({length: 5}, (_, index) => el("span", {"data-timeline-tick": "", style: "left:" + index * 25 + "%", text: timeOnly(row.start_ms + span * index / 4)}))));
    return timeline;
  }
  function fitReader() {
    for (const labels of document.querySelectorAll(".timeline-labels")) {
      const occupied = [[], []], width = labels.getBoundingClientRect().width;
      for (const label of labels.querySelectorAll("[data-timeline-label]")) {
        label.hidden = false; label.removeAttribute("data-timeline-label-row");
        label._block.removeAttribute("data-tooltip-only");
        const labelWidth = label.getBoundingClientRect().width, left = Math.max(0, Math.min(width - labelWidth, Number(label.dataset.left) * width / 100));
        let placed = false;
        for (let line = 0; line < 2; line++) {
          if (labelWidth > width || occupied[line].some(([a, b]) => left < b + 4 && left + labelWidth + 4 > a)) continue;
          label.style.left = left + "px"; label.style.top = line * 10 + "px";
          label.setAttribute("data-timeline-label-row", line); occupied[line].push([left, left + labelWidth]); placed = true; break;
        }
        if (!placed) {label.hidden = true; label._block.setAttribute("data-tooltip-only", "");}
      }
    }
    for (const wrap of document.querySelectorAll("[data-expandable-text]")) {
      const paragraph = wrap.querySelector("[data-long-text]"), button = wrap.querySelector("[data-text-toggle]");
      if (paragraph.getBoundingClientRect().width) {
        const expanded = paragraph.classList.contains("expanded");
        button.hidden = !expanded && paragraph.scrollHeight <= paragraph.clientHeight + 1;
        wrap.querySelector("[data-text-collapse-top]").hidden = !expanded || !exceedsViewport(paragraph);
      }
    }
  }
  function renderReader(row) {
    const children = descendants(row, data.subagents, currentState), visibleChildren = new Map(children.map(child => [child.id, child]));
    const matched = matchSession(row, currentState, data.subagents).matchedSubagents;
    const full = readerUsage([row, ...children]), own = readerUsage([row]), agent = readerUsage(children), unresolved = row.flags.includes("history_unresolved");
    const reader = el("section", {class: "reader", "data-reader": row.id, "data-provider": providerOf(row)}, el("button", {type: "button", class: "reader-back", text: "← sessions", onclick: () => act({v: "list", s: undefined})}));
    const title = el("button", {type: "button", class: "collapsed-title", title: row.title_full, "aria-label": "Expand full title", "aria-expanded": "false", text: row.title, onclick: () => {
      const expanded = title.getAttribute("aria-expanded") !== "true";
      title.className = expanded ? "expanded-title" : "collapsed-title"; title.textContent = expanded ? row.title_full : row.title; title.setAttribute("aria-expanded", String(expanded));
    }});
    const header = el("div", {class: "reader-header", "data-reader-header": ""}, el("h1", {class: "reader-title"}, title),
      el("p", {class: "reader-meta reader-workspace", text: workspaceLine(row)}),
      el("p", {class: "reader-meta", text: (row.branch || "branch unknown") + " · " + (row.originator || "originator unknown")}),
      el("p", {class: "reader-meta", "data-time-range": "", text: localStamp(row.start_ms) + " — " + localStamp(row.end_ms),
        title: quantity(row.user_span_ms) ? "user-request span: " + durationText(row.user_span_ms) : undefined}),
      el("p", {class: "reader-meta", text: row.id.slice(0, 8) + "…" + row.id.slice(-8), title: row.id}), flagsLine(row));
    if (row.forked_from) {
      const parents = [...data.sessions, ...Object.values(data.subagents)].filter(parent => parent.id === row.forked_from);
      const titles = new Set(parents.filter(parent => typeof parent.title === "string" && parent.title.trim()).map(parent => parent.title));
      const parentTitle = titles.size === 1 ? titles.values().next().value : row.forked_from;
      header.append(el("button", {type: "button", class: "fork-link", text: "forked from " + parentTitle, onclick: () => act({v: "session", s: row.forked_from})}));
    }
    const copyArea = el("div", {class: "copy-status", "aria-live": "polite"});
    const copy = async text => {
      try {
        if (!navigator.clipboard || typeof navigator.clipboard.writeText !== "function") throw new Error("Clipboard unavailable");
        await navigator.clipboard.writeText(text); copyArea.replaceChildren(el("span", {text: "copied"})); copyArea.removeAttribute("data-copy-fallback");
      } catch (_) {
        const field = el("input", {type: "text", readonly: "", value: text, "aria-label": "Text to copy"});
        copyArea.setAttribute("data-copy-fallback", ""); copyArea.replaceChildren(field, el("span", {text: "press ⌘C"})); field.focus(); field.select();
      }
    };
    const lifecycle = row.archived ? "archived" : "live";
    const isSubagent = !row.kind || row.kind === "subagent" || row.kind === "orphan";
    const supports = action => action && action[lifecycle] && (!isSubagent || action.subagent);
    const claude = providerOf(row) === "claude";
    const codex = providerOf(row) === "codex";
    const capable = action => !row.capabilities || row.capabilities[action] === true;
    const usablePath = value => typeof value === "string" && value.startsWith("/") && !/[\x00-\x1f\x7f]/.test(value);
    const canContinue = capable("continue_in_cli") && (claude ? supports(data.meta.links.claude_continue_in_cli) && usablePath(row.cwd) && usablePath(row.resume_config_dir) &&
      !row.history_only && !row.flags.includes("transcript_deleted") : codex && supports(data.meta.links.continue_in_cli));
    // Claude CLI searches from cwd; CLAUDE_CONFIG_DIR chooses its session store.
    // https://code.claude.com/docs/en/cli-reference (--resume)
    // https://code.claude.com/docs/en/settings (CLAUDE_CONFIG_DIR)
    const continuation = () => claude ? "cd " + shellArgument(row.cwd) + " && CLAUDE_CONFIG_DIR=" + shellArgument(row.resume_config_dir) + " claude --resume " + shellArgument(row.id) : "codex resume " + row.id;
    header.append(el("div", {class: "reader-buttons"},
      ...(codex && capable("open_in_codex") && supports(data.meta.links.open_in_codex) ? [el("a", {href: "codex://threads/" + row.id, text: "Open in Codex",
        onkeydown: event => {if (event.key === " ") {event.preventDefault(); event.currentTarget.click();}}})] : []),
      ...(canContinue ? [el("button", {type: "button", text: "Copy Continue in CLI — continues this session", onclick: () => copy(continuation())})] : []),
      ...(capable("copy_session_id") ? [el("button", {type: "button", text: "Copy session ID", onclick: () => copy(row.id)})] : []),
      ...((codex || claude) && capable("copy_log_path") && !row.history_only && !row.flags.includes("transcript_deleted") ? [el("button", {type: "button", text: "Copy log path", onclick: () => copy(row.log_path)})] : [])), copyArea);
    const stat = (key, label, value, text, sub, tooltip) => el("div", {class: "reader-stat", "data-reader-stat": key, title: tooltip},
      el("span", {class: "kpi-label", text: label}), el("div", {class: "reader-stat-value", "data-value": value, text}), el("div", {class: "reader-stat-sub", text: sub}));
    const span = validMs(row.start_ms) && validMs(row.end_ms) && row.end_ms >= row.start_ms ? row.end_ms - row.start_ms : null;
    const agentActive = children.map(ownActive), agentMs = agentActive.every(quantity) ? agentActive.reduce((a, b) => a + b, 0) : null;
    reader.append(header, el("div", {class: "reader-stats"},
      stat("active", "active time", ownActive(row), unresolved ? "withheld" : durationText(ownActive(row)), "yours"),
      stat("span", "span", span, unresolved ? "withheld" : durationText(span), "idle " + durationText(quantity(row.idle_ms) ? row.idle_ms : null)),
      stat("turns", "turns", unresolved ? null : row.turns.length, unresolved ? "withheld" : countText(row.turns.length), "your turns"),
      stat("subagents", "subagents", children.length, countText(children.length), durationText(agentMs) + " agent time"),
      stat("tokens", "tokens", full.tokens, full.tokens === null ? "unknown" : countText(full.tokens), "total (yours + subagents) · " + (own.tokens === null ? "unknown" : countText(own.tokens)) + " yours + " + (agent.tokens === null ? "unknown" : countText(agent.tokens)) + " subagents"),
      stat("cost", "estimated cost", full.cost, usageCostText({cost_usd: full.cost, cost_overflow: full.cost_overflow, unpriced_tokens: full.unpriced ? 1 : 0}, providerOf(row)),
        "total (yours + subagents) · API-equivalent estimate (not billed) · " + usageCostText(row.own_usage) + " yours + " + usageCostText({cost_usd: agent.cost, cost_overflow: agent.cost_overflow, unpriced_tokens: agent.unpriced ? 1 : 0}, providerOf(row)) + " subagents", usageRateTooltip([row, ...children].map(item => item.own_usage)))));
    if (unresolved) reader.append(el("p", {class: "reader-note", text: "history boundary unresolved — turn metrics withheld"}));
    else reader.append(renderTimeline(row, children, matched), ...row.turns.map(turn => renderTurn(turn, matched, visibleChildren)));
    if (Object.entries(row.outside_usage).some(([key, value]) => !["cost_usd", "priced_by"].includes(key) && quantity(value) && value > 0)) reader.append(el("p", {
      class: "outside-usage", "data-outside-usage": "", text: "tokens outside displayed turns: " + tokenText(row.outside_usage), title: usageRateTooltip([row.outside_usage])}));
    return reader;
  }
  function render() {
    renderTopbar();
    renderFooter();
    const rows = scope(data.sessions, currentState, data.meta.generated_at_ms).rows;
    const app = document.getElementById("colophon-app");
    if (currentState.src !== "all" && sourceMissing(currentState.src)) {
      app.replaceChildren(el("p", {class: "empty-state", text: sourceAbsence(currentState.src)}));
    } else if (!data.sessions.length) {
      app.replaceChildren(el("p", {class: "empty-state", text: "No sessions found"}));
    } else if (currentState.v === "overview") {
      app.replaceChildren(...renderOverview());
      fitCalendar();
    } else {
      const selected = currentState.v === "session" && currentState.s ? rows.find(row => row.id === currentState.s) || data.subagents[currentState.s] : null;
      const visible = selected && providerMatch(selected, currentState) && !(currentState.a === "0" && selected.archived) && !(currentState.h === "0" && selected.history_only);
      const layout = el("div", {class: "session-layout" + (visible ? " has-reader" : "")}, renderSessionList(rows), ...(visible ? [renderSplitter(), renderReader(selected)] : []));
      if (visible) applyListWidth(layout);
      app.replaceChildren(el("h2", {class: "section-label", text: "// sessions"}), layout);
      fitReader();
      document.fonts.ready.then(fitReader);
    }
  }
  // --- boot
  document.addEventListener("DOMContentLoaded", () => {
    data = JSON.parse(document.getElementById("colophon-data").textContent);
    for (const row of [...data.sessions, ...Object.values(data.subagents)]) {
      for (const usage of [row.own_usage, row.outside_usage, ...row.turns.map(turn => turn.usage)]) if (usage) usageProviders.set(usage, providerOf(row));
    }
    earliestMs = [...data.sessions, ...Object.values(data.subagents)].map(row => row.start_ms).filter(validMs).reduce((min, ms) => min === null || ms < min ? ms : min, null);
    for (const weight of [300, 400, 500]) document.fonts.load(weight + " 12px 'Martian Mono'");
    mountTopbar();
    const restore = () => {
      clearTimeout(searchTimer);
      writeState(readState(), {replace: true});
    };
    window.addEventListener("popstate", restore);
    window.addEventListener("hashchange", restore);
    document.addEventListener("keydown", event => {
      if (!["[", "]"].includes(event.key) || event.metaKey || event.ctrlKey || event.altKey || (event.target instanceof Element && event.target.closest("input, textarea, select, [contenteditable]"))) return;
      event.preventDefault();
      stepPeriod(event.key === "[" ? -1 : 1);
    });
    window.addEventListener("resize", () => {fitCalendar(); fitReader();});
    window.__colophonTest = {time, filters, aggregates, format, levels, state: {readState, writeState}, heatColors};
    restore();
  });
})();
