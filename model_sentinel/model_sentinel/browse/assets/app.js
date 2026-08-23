(() => {
  "use strict";
  const {h, render} = preact;
  const {useState, useEffect, useMemo, useRef, useCallback} = preactHooks;
  const html = htm.bind(h);
  const THEME_KEY = "model_sentinel.browse.theme";
  const THEMES = ["system", "light", "dark"];
  const VIEWS = ["activity", "models", "catalog"];
  const ASPECT_LIMIT = 12;
  const CATALOG_PAGE_SIZE = 50;
  const LIST_KEYS = new Set(["providers", "models", "categories", "kinds", "pins", "aspects", "cols"]);
  const HASH_KEYS = ["view", "providers", "from", "to", "detail", "models", "categories", "kinds", "pins", "aspects", "asof", "compare", "cols", "q", "sort", "dir"];

  function decode(value) {
    try { return decodeURIComponent(value); } catch (error) { return value; }
  }

  const hashState = {
    read() {
      const result = {};
      const source = location.hash.replace(/^#/, "");
      for (const pair of source.split("&")) {
        if (!pair) continue;
        const split = pair.indexOf("=");
        const key = decode(split < 0 ? pair : pair.slice(0, split));
        if (!HASH_KEYS.includes(key)) continue;
        const raw = split < 0 ? "" : pair.slice(split + 1);
        result[key] = LIST_KEYS.has(key) ? raw.split(",").filter(Boolean).map(decode) : decode(raw);
      }
      return result;
    },
    write(partial, replace = false) {
      const next = {...this.read(), ...partial};
      const pairs = [];
      for (const key of HASH_KEYS) {
        const value = next[key];
        if (value == null || value === "" || Array.isArray(value) && !value.length) continue;
        const encoded = Array.isArray(value)
          ? value.map(item => encodeURIComponent(String(item))).join(",")
          : encodeURIComponent(String(value));
        pairs.push(`${encodeURIComponent(key)}=${encoded}`);
      }
      const target = pairs.length ? `#${pairs.join("&")}` : "";
      if (target === location.hash) return;
      if (replace) history.replaceState(history.state, "", target || `${location.pathname}${location.search}`);
      else location.hash = target;
    }
  };

  class ApiError extends Error {
    constructor(message) { super(message); this.name = "ApiError"; }
  }

  const api = {
    async get(path, params = {}, signal) {
      const query = Object.entries(params).flatMap(([key, value]) => {
        if (value == null || value === "" || Array.isArray(value) && !value.length) return [];
        return [`${encodeURIComponent(key)}=${encodeURIComponent(Array.isArray(value) ? value.join(",") : String(value))}`];
      });
      let response;
      try {
        response = await fetch(`${path}${query.length ? `?${query.join("&")}` : ""}`, {signal, headers: {Accept: "application/json"}});
      } catch (error) {
        if (error.name === "AbortError") throw error;
        throw new ApiError("Could not reach the local Model Sentinel server.");
      }
      let payload;
      try { payload = await response.json(); }
      catch (error) { throw new ApiError("The local server returned an invalid response."); }
      if (!response.ok) throw new ApiError(payload && payload.error ? payload.error : `Request failed (${response.status}).`);
      return payload;
    }
  };

  function useHashState() {
    const [state, setState] = useState(hashState.read);
    useEffect(() => {
      const update = () => setState(hashState.read());
      addEventListener("hashchange", update);
      return () => removeEventListener("hashchange", update);
    }, []);
    const write = useCallback(value => hashState.write(value), []);
    const replaceState = useCallback(value => {
      hashState.write(value, true);
      setState(hashState.read());
    }, []);
    return [state, write, replaceState];
  }

  function useApi(path, params, enabled = true) {
    const [state, setState] = useState({data: null, loading: enabled, error: null});
    const [revision, setRevision] = useState(0);
    const key = JSON.stringify([path, params, enabled, revision]);
    useEffect(() => {
      if (!enabled) { setState(current => ({...current, loading: false, error: null})); return; }
      const controller = new AbortController();
      setState(current => ({...current, loading: true, error: null}));
      api.get(path, params, controller.signal).then(
        data => setState({data, loading: false, error: null}),
        error => error.name !== "AbortError" && setState(current => ({...current, loading: false, error}))
      );
      return () => controller.abort();
    }, [key]);
    return {...state, reload: useCallback(() => setRevision(value => value + 1), [])};
  }

  function activityEntryId(entry) {
    const ids = entry.change_ids || [];
    return [entry.date, entry.provider_id, entry.kind, entry.model_id || "", ids.join(".")].join("|");
  }

  function mergeActivityPages(current, incoming, page) {
    if (page === 1 || !current) return incoming;
    const entries = [], seen = new Set();
    for (const entry of [...current.entries, ...incoming.entries]) {
      const identity = activityEntryId(entry);
      if (!seen.has(identity)) { seen.add(identity); entries.push(entry); }
    }
    return {...incoming, entries};
  }

  function usePagedApi(path, params, enabled = true) {
    const requestKey = JSON.stringify([path, params, enabled]);
    const [cursor, setCursor] = useState({key: requestKey, page: 1});
    const [state, setState] = useState({data: null, key: null, loading: enabled, error: null});
    const [revision, setRevision] = useState(0);
    const inFlight = useRef(null);
    const page = cursor.key === requestKey ? cursor.page : 1;
    const key = JSON.stringify([requestKey, page, revision]);
    useEffect(() => {
      if (cursor.key !== requestKey) setCursor({key: requestKey, page: 1});
      if (!enabled) { inFlight.current = null; setState(current => ({...current, loading: false, error: null})); return; }
      const controller = new AbortController();
      inFlight.current = key;
      setState(current => ({...current, loading: true, error: null}));
      api.get(path, {...params, page}, controller.signal).then(
        data => setState(current => ({data: mergeActivityPages(current.data, data, page), key: requestKey, loading: false, error: null})),
        error => error.name !== "AbortError" && setState(current => ({...current, loading: false, error}))
      ).finally(() => { if (inFlight.current === key) inFlight.current = null; });
      return () => controller.abort();
    }, [key]);
    const loaded = state.data && state.data.entries ? state.data.entries.length : 0;
    const fresh = state.key === requestKey;
    const loading = Boolean(enabled && (state.loading || !fresh));
    const hasMore = Boolean(fresh && state.data && loaded < state.data.total);
    const loadMore = useCallback(() => {
      if (inFlight.current || state.loading || state.key !== requestKey || !state.data) return;
      if (state.data.entries.length >= state.data.total) return;
      inFlight.current = "paging";
      setCursor({key: requestKey, page: state.data.page + 1});
    }, [requestKey, state.data, state.key, state.loading]);
    return {
      ...state,
      loading,
      hasMore,
      loadMore,
      reload: useCallback(() => { inFlight.current = "reload"; setCursor({key: requestKey, page: 1}); setRevision(value => value + 1); }, [requestKey])
    };
  }

  function shiftDay(iso, amount) {
    const date = new Date(`${iso}T12:00:00Z`);
    date.setUTCDate(date.getUTCDate() + amount);
    return date.toISOString().slice(0, 10);
  }
  function clamp(value, span) { return !span ? value : value < span.first ? span.first : value > span.last ? span.last : value; }
  function defaults(meta) {
    const span = meta.date_span;
    let providers = meta.providers.filter(provider => provider.enabled).map(provider => provider.id);
    if (!providers.length) providers = meta.providers.map(provider => provider.id);
    return {view: "activity", providers, from: span ? clamp(shiftDay(span.last, -30), span) : "", to: span ? span.last : "", detail: meta.detail_default};
  }

  function validDate(value) {
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    const parsed = new Date(`${value}T12:00:00Z`);
    return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
  }

  function resolveState(meta, state) {
    const fallback = defaults(meta), span = meta.date_span;
    const knownProviders = new Set(meta.providers.map(provider => provider.id));
    const knownCategories = new Set(meta.categories || []);
    const knownAspects = new Set(meta.aspects.map(aspect => aspect.id));
    const kinds = new Set(["added", "removed", "changed"]);
    const list = (value, allowed) => Array.isArray(value)
      ? value.filter(item => typeof item === "string" && item && (!allowed || allowed.has(item)))
      : [];
    const resolved = {...state};
    resolved.view = VIEWS.includes(state.view) ? state.view : fallback.view;
    resolved.detail = ["default", "all", "squelched"].includes(state.detail) ? state.detail : fallback.detail;
    resolved.providers = list(state.providers, knownProviders);
    if (!resolved.providers.length) resolved.providers = fallback.providers;
    resolved.categories = list(state.categories, knownCategories);
    resolved.kinds = list(state.kinds, kinds);
    for (const key of ["models", "pins", "cols"]) resolved[key] = list(state[key]);
    resolved.aspects = list(state.aspects, knownAspects).slice(0, ASPECT_LIMIT);
    if (span) {
      resolved.from = validDate(state.from) ? clamp(state.from, span) : fallback.from;
      resolved.to = validDate(state.to) ? clamp(state.to, span) : fallback.to;
      if (resolved.from > resolved.to) { resolved.from = fallback.from; resolved.to = fallback.to; }
    } else { resolved.from = ""; resolved.to = ""; }
    return resolved;
  }

  class ErrorBoundary extends preact.Component {
    constructor(props) { super(props); this.state = {error: null}; }
    static getDerivedStateFromError(error) { return {error}; }
    render(props, state) {
      if (!state.error) return props.children;
      return html`<section class="error-banner fatal" role="alert"><div><strong>The browser could not render this view</strong><span>Reset the URL filters or reload the local console.</span></div><button type="button" onClick=${() => location.reload()}>Reload</button></section>`;
    }
  }

  function ErrorBanner({error, reload}) {
    return error && html`<section class="error-banner" role="alert"><div><strong>Unable to refresh</strong><span>${error.message}</span></div><button type="button" onClick=${reload}>Try again</button></section>`;
  }
  function Segmented({label, value, options, onChange}) {
    return html`<fieldset class="segmented"><legend>${label}</legend><div>${options.map(option => html`<button key=${option.value} type="button" class=${value === option.value ? "is-active" : ""} aria-pressed=${value === option.value} onClick=${() => onChange(option.value)}>${option.label}</button>`)}</div></fieldset>`;
  }

  function FilterBar({meta, state, write, theme, setTheme}) {
    const providers = state.providers || [];
    const toggle = id => {
      const next = providers.includes(id) ? providers.filter(value => value !== id) : [...providers, id];
      if (next.length) write({providers: next});
    };
    const dateChange = key => event => {
      let value = clamp(event.currentTarget.value, meta.date_span);
      if (key === "from" && value > state.to) value = state.to;
      if (key === "to" && value < state.from) value = state.from;
      write({[key]: value});
    };
    return html`
      <section class="filter-bar" aria-label="Browser controls">
        <nav class="view-tabs" aria-label="Views">${VIEWS.map((view, index) => html`<button type="button" key=${view} class=${state.view === view ? "is-active" : ""} aria-current=${state.view === view ? "page" : undefined} onClick=${() => write({view})}><span>${index + 1}</span>${view[0].toUpperCase() + view.slice(1)}</button>`)}</nav>
        <div class="filter-row">
          <fieldset class="providers"><legend>Providers</legend><div>${meta.providers.map(provider => html`<button type="button" key=${provider.id} class=${providers.includes(provider.id) ? "chip is-active" : "chip"} aria-pressed=${providers.includes(provider.id)} onClick=${() => toggle(provider.id)}><i></i>${provider.label}</button>`)}</div></fieldset>
          <fieldset class="dates" disabled=${!meta.date_span}><legend>Date range</legend><label>From<input type="date" min=${meta.date_span && meta.date_span.first} max=${meta.date_span && meta.date_span.last} value=${state.from || ""} onChange=${dateChange("from")} /></label><b>→</b><label>To<input type="date" min=${meta.date_span && meta.date_span.first} max=${meta.date_span && meta.date_span.last} value=${state.to || ""} onChange=${dateChange("to")} /></label></fieldset>
          <${Segmented} label="Detail" value=${state.detail} options=${["default", "all", "squelched"].map(value => ({value, label: value[0].toUpperCase() + value.slice(1)}))} onChange=${detail => write({detail})} />
          <${Segmented} label="Theme" value=${theme} options=${THEMES.map(value => ({value, label: value[0].toUpperCase() + value.slice(1)}))} onChange=${setTheme} />
        </div>
      </section>`;
  }

  function Heatmap({rows, from, to, detail, write, loading}) {
    const drag = useRef(null);
    const moved = useRef(false);
    const days = useMemo(() => {
      const result = [], end = to || new Date().toISOString().slice(0, 10);
      for (let day = shiftDay(end, -179); day <= end; day = shiftDay(day, 1)) result.push(day);
      return result;
    }, [to]);
    const data = useMemo(() => new Map((rows || []).map(row => [row.date, row])), [rows]);
    const visibleCount = row => detail === "all"
      ? row.changed + row.squelched
      : detail === "squelched" ? row.squelched : row.changed;
    const max = Math.max(1, ...Array.from(data.values(), visibleCount));
    return html`
      <section class="instrument heatmap-panel" aria-labelledby="heat-title">
        <header class="section-heading"><div><p>01 / signal density</p><h2 id="heat-title">180-day activity field</h2></div><span>${loading ? "Sampling history…" : "Visible changes · presence marked"}</span></header>
        <div class="heatmap-scroll"><div class="heatmap">${days.map((day, index) => {
          const row = data.get(day) || {changed: 0, added: 0, removed: 0, squelched: 0};
          const visible = visibleCount(row);
          const level = visible ? Math.min(3, Math.ceil(visible / max * 3)) : 0;
          return html`<button type="button" key=${day} data-date=${day} tabIndex=${day === to ? 0 : -1} aria-pressed=${day >= from && day <= to} class=${`heat-cell heat-${level}`} aria-label=${`${day}: ${visible} visible changes, ${row.added} added, ${row.removed} removed`} title=${`${day} · ${visible} visible in ${detail} detail · ${row.squelched} squelched`}
            onPointerDown=${event => { drag.current = day; moved.current = false; event.currentTarget.setPointerCapture(event.pointerId); }}
            onPointerUp=${event => { if (!drag.current) return; const target = document.elementFromPoint(event.clientX, event.clientY); const end = target && target.closest("[data-date]"); const range = [drag.current, end ? end.dataset.date : day].sort(); moved.current = range[0] !== range[1]; write({from: range[0], to: range[1]}); drag.current = null; }}
            onKeyDown=${event => {
              let target = null;
              if (event.key === "ArrowLeft") target = index - 7;
              else if (event.key === "ArrowRight") target = index + 7;
              else if (event.key === "ArrowUp") target = index - 1;
              else if (event.key === "ArrowDown") target = index + 1;
              else if (event.key === "Home") target = 0;
              else if (event.key === "End") target = days.length - 1;
              if (target == null) return;
              event.preventDefault();
              const next = event.currentTarget.parentElement.querySelector(`[data-date="${days[Math.max(0, Math.min(days.length - 1, target))]}"]`);
              if (next) next.focus();
            }}
            onClick=${() => { if (!moved.current) write({from: day, to: day}); moved.current = false; }}>
            <span>${day.slice(8)}</span><em>${row.added ? html`<i class="added"></i>` : null}${row.removed ? html`<i class="removed"></i>` : null}</em>
          </button>`;
        })}</div></div>
        <footer class="heat-legend"><span>Less</span>${[0,1,2,3].map(value => html`<i class=${`heat-${value}`}></i>`)}<span>More</span></footer>
      </section>`;
  }

  function Facet({title, values, selected, labels, onChange}) {
    return html`<fieldset class="facet"><legend>${title}</legend>${values.map(value => html`<label key=${value}><input type="checkbox" checked=${selected.includes(value)} onChange=${() => onChange(selected.includes(value) ? selected.filter(item => item !== value) : [...selected, value])} /><span>${labels && labels[value] || value}</span></label>`)}</fieldset>`;
  }
  function Facets({meta, state, write, modelOptions}) {
    return html`<aside class="instrument facets"><header class="section-heading small"><div><p>02 / discriminate</p><h2>Facets</h2></div></header>
      <${Facet} title="Provider" values=${meta.providers.map(value => value.id)} selected=${state.providers || []} labels=${Object.fromEntries(meta.providers.map(value => [value.id, value.label]))} onChange=${providers => providers.length && write({providers})} />
      <details class="model-facet"><summary>Models${state.models && state.models.length ? ` · ${state.models.length}` : ""}</summary><div><${Facet} title="Model" values=${modelOptions.map(value => value.model_id)} selected=${state.models || []} labels=${Object.fromEntries(modelOptions.map(value => [value.model_id, value.display_name || value.model_id]))} onChange=${models => write({models})} /></div></details>
      <${Facet} title="Category" values=${meta.categories} selected=${state.categories || []} onChange=${categories => write({categories})} />
      <${Facet} title="Change kind" values=${["added", "removed", "changed"]} selected=${state.kinds || []} labels=${{added: "Added", removed: "Removed", changed: "Field changed"}} onChange=${kinds => write({kinds})} />
      <${Segmented} label="Visibility" value=${state.detail} options=${["default", "all", "squelched"].map(value => ({value, label: value[0].toUpperCase() + value.slice(1)}))} onChange=${detail => write({detail})} />
    </aside>`;
  }

  function semantic(change) {
    if (change.kind === "list") {
      return change.list_added && change.list_added.length ? "capability" : "dim";
    }
    if (change.semantic === "cost") return change.direction === "up" ? "cost-up" : change.direction === "down" ? "cost-down" : "dim";
    if (change.semantic === "capacity") return "capacity";
    if (change.semantic === "capability") return "capability";
    return "dim";
  }
  function ChangeTable({entry, openRaw}) {
    if (!entry.changes.length) return null;
    const activate = (event, index) => {
      if (event.type === "keydown" && !["Enter", " "].includes(event.key)) return;
      if (event.type === "keydown") event.preventDefault();
      const associated = entry.change_ids_by_change[index] || [];
      if (associated.length) openRaw(associated[0]);
    };
    return html`<div class="table-wrap"><table class="changes"><thead><tr><th>Field</th><th>Transition</th><th>Δ</th><th>%</th><th>Unit</th></tr></thead><tbody>${entry.changes.map((change, index) => html`
      <tr key=${`${change.field_path}-${index}`} tabindex=${entry.change_ids_by_change[index] && entry.change_ids_by_change[index].length ? 0 : undefined} class=${entry.change_ids_by_change[index] && entry.change_ids_by_change[index].length ? "actionable" : ""} onClick=${event => activate(event, index)} onKeyDown=${event => activate(event, index)}>
        <th scope="row"><span>${change.label}</span>${change.qualifier && html`<small>${change.qualifier}</small>`}</th>
        <td class=${`transition ${semantic(change)}`}>${change.old_display}<b>→</b>${change.new_display}</td><td>${change.delta_display || "—"}</td><td>${change.pct_display || (change.pct_basis_zero ? "from zero" : "—")}</td><td class="unit">${change.unit || "—"}</td>
      </tr>`)}</tbody></table></div>`;
  }

  function Entry({entry, openModel, openRaw}) {
    const model = value => html`<button class="model-link" type="button" onClick=${() => openModel(entry.provider_id, value.model_id, value.display_name, entry.date)}><strong>${value.display_name || value.model_id}</strong><small>${value.model_id}</small></button>`;
    const presence = ["added", "removed"].includes(entry.kind);
    return html`<article class=${`feed-entry ${presence ? `presence ${entry.kind}` : ""}`}>
      <header><div>${model(entry)}</div><p><span>${entry.provider_id}</span><b>${entry.kind}</b></p></header>
      ${presence && html`<button type="button" class="presence-summary" onClick=${() => entry.change_ids.length && openRaw(entry.change_ids[0])}><i>${entry.kind === "added" ? "+" : "−"}</i> Model ${entry.kind} from the observed catalog</button>`}
      <${ChangeTable} entry=${entry} openRaw=${openRaw} />
      ${entry.kind === "bulk" && html`<details class="bulk"><summary>${entry.bulk_models.length} models share this change</summary><ol>${entry.bulk_models.map(value => html`<li key=${value.model_id}>${model(value)}</li>`)}</ol></details>`}
      ${Object.values(entry.hidden || {}).some(Boolean) && html`<p class="entry-hidden">${Object.values(entry.hidden).reduce((a,b) => a+b, 0)} additional details hidden by visibility policy</p>`}
    </article>`;
  }

  function Feed({data, loading, hasMore, loadMore, openModel, openRaw, write}) {
    const groups = useMemo(() => {
      const result = [];
      for (const entry of data && data.entries || []) {
        let group = result.at(-1);
        if (!group || group.date !== entry.date) { group = {date: entry.date, entries: []}; result.push(group); }
        group.entries.push(entry);
      }
      return result;
    }, [data]);
    const rollupLine = day => {
      const rollup = data && data.rollups_by_date[day];
      const squelched = rollup && rollup.squelched || [];
      const count = squelched.reduce((sum, item) => sum + item[1], 0);
      if (!count) return null;
      const fields = squelched.slice(0, 3).map(item => item[0]).join(", ") + (squelched.length > 3 ? ", …" : "");
      return html`<p class="date-rollup">${count} squelched changes hidden (${fields}) — <button type="button" onClick=${() => write({detail: "all"})}>show</button></p>`;
    };
    return html`<section class="feed" aria-labelledby="feed-title" aria-busy=${loading}>
      <header class="section-heading"><div><p>03 / event record</p><h2 id="feed-title">Observed changes</h2></div><span>${data ? `${data.total} grouped events` : "Awaiting sample"}</span></header>
      ${loading && !data && html`<div class="loading"><i></i><p>Reconstructing the field log…</p></div>`}
      ${data && !data.entries.length && html`<div class="empty"><b>∅</b><div><h2>No changes in this slice</h2><p>Widen the date range or clear a facet.</p></div></div>`}
      ${groups.map(group => html`<section class="date-block" key=${group.date}><header><time datetime=${group.date}>${new Date(`${group.date}T12:00:00Z`).toLocaleDateString(undefined, {weekday: "short", month: "short", day: "numeric", year: "numeric", timeZone: "UTC"})}</time><span>${String(group.entries.length).padStart(2,"0")} entries</span></header><div>${group.entries.map(entry => html`<${Entry} key=${activityEntryId(entry)} entry=${entry} openModel=${openModel} openRaw=${openRaw} />`)}${rollupLine(group.date)}</div></section>`)}
      ${data && hasMore && html`<div class="feed-more"><button type="button" disabled=${loading} onClick=${loadMore}>${loading ? "Loading more changes…" : "Load more changes"}</button><span>${data.entries.length} of ${data.total} events loaded</span></div>`}
    </section>`;
  }

  function Activity({meta, state, write, openRaw, openModel, reportError}) {
    const common = {providers: state.providers, from: state.from, to: state.to, detail: state.detail};
    const feed = usePagedApi("/api/activity", {...common, models: state.models, categories: state.categories, kinds: state.kinds, page_size: 500}, Boolean(state.from && state.to));
    const heat = useApi("/api/heatmap", {
      providers: state.providers,
      from: clamp(shiftDay(state.to, -179), meta.date_span),
      to: state.to,
      detail: state.detail
    }, Boolean(state.to));
    const models = useApi("/api/models", {providers: state.providers, limit: 50}, Boolean(state.providers && state.providers.length));
    useEffect(() => reportError(feed.error || heat.error || models.error, feed.error ? feed.reload : heat.error ? heat.reload : models.reload), [feed.error, heat.error, models.error]);
    return html`<div class="activity"><${Heatmap} rows=${heat.data} from=${state.from} to=${state.to} detail=${state.detail} write=${write} loading=${heat.loading} /><div class="activity-grid"><${Facets} meta=${meta} state=${state} write=${write} modelOptions=${models.data || []} /><${Feed} data=${feed.data} loading=${feed.loading} hasMore=${feed.hasMore} loadMore=${feed.loadMore} openModel=${openModel} openRaw=${openRaw} write=${write} /></div></div>`;
  }

  function pinParts(pin, providers) {
    const provider = [...providers].sort((a, b) => b.id.length - a.id.length).find(item => pin.startsWith(`${item.id}/`));
    return provider ? {provider, model: pin.slice(provider.id.length + 1)} : {provider: null, model: pin};
  }

  function Pins({meta, pins, providers, write, inputRef, toast}) {
    const [query, setQuery] = useState("");
    const [debouncedQuery, setDebouncedQuery] = useState("");
    useEffect(() => {
      const timer = setTimeout(() => setDebouncedQuery(query), 150);
      return () => clearTimeout(timer);
    }, [query]);
    const results = useApi("/api/models", {providers, q: debouncedQuery, limit: 20}, Boolean(debouncedQuery.trim() && providers.length));
    const add = item => {
      const pin = `${item.provider_id}/${item.model_id}`;
      const next = pins.filter(value => value !== pin);
      next.push(pin);
      if (next.length > meta.pin_limit) {
        const dropped = next.splice(0, next.length - meta.pin_limit);
        toast(`Pin limit reached. Dropped ${dropped.join(", ")}.`);
      }
      write({pins: next});
      setQuery("");
    };
    return html`<section class="pins" aria-labelledby="pins-title">
      <header><div><p>01 / specimens</p><h2 id="pins-title">Pinned models</h2></div><span>${pins.length} / ${meta.pin_limit}</span></header>
      <ol>${pins.map((pin, index) => {
        const parts = pinParts(pin, meta.providers);
        return html`<li key=${pin}><i style=${`--pin-color: var(--series-${index + 1})`}></i><span><strong>${parts.model}</strong><small>${parts.provider ? parts.provider.label : pin}</small></span><button type="button" aria-label=${`Remove ${parts.model}`} onClick=${() => write({pins: pins.filter(value => value !== pin)})}>×</button></li>`;
      })}</ol>
      <div class="pin-search"><label for="pin-query">Add model</label><input id="pin-query" ref=${inputRef} type="search" autocomplete="off" value=${query} placeholder="Search model id or name" onInput=${event => setQuery(event.currentTarget.value)} onKeyDown=${event => {
        if (event.key === "Escape") setQuery("");
        else if (event.key === "ArrowDown") { const first = event.currentTarget.nextElementSibling && event.currentTarget.nextElementSibling.querySelector("button"); if (first) { event.preventDefault(); first.focus(); } }
      }} />
        ${query.trim() && html`<div class="typeahead" role="listbox" aria-label="Model search results">${results.loading ? html`<p>Searching local history…</p>` : results.error ? html`<p>${results.error.message}</p>` : results.data && results.data.length ? results.data.map(item => html`<button type="button" role="option" aria-selected="false" key=${`${item.provider_id}/${item.model_id}`} onClick=${() => add(item)}><strong>${item.display_name || item.model_id}</strong><span>${item.provider_id} / ${item.model_id}</span></button>`) : html`<p>No matching models</p>`}</div>`}
      </div>
    </section>`;
  }

  function ambiguousAspectIds(aspects) {
    const groups = new Map();
    for (const aspect of aspects) {
      const signature = [aspect.label, aspect.qualifier || "", aspect.unit || aspect.kind].join("|");
      const group = groups.get(signature) || [];
      group.push(aspect);
      groups.set(signature, group);
    }
    const result = new Set();
    for (const group of groups.values()) {
      if (new Set(group.map(aspect => aspect.provider_id)).size > 1) for (const aspect of group) result.add(aspect.id);
    }
    return result;
  }

  function AspectChoice({aspect, selected, write, toast, showProvider, providerLabel}) {
    const toggle = () => {
      if (selected.includes(aspect.id)) { write({aspects: selected.filter(value => value !== aspect.id)}); return; }
      if (selected.length >= ASPECT_LIMIT) { toast(`You can compare at most ${ASPECT_LIMIT} aspects.`); return; }
      write({aspects: [...selected, aspect.id]});
    };
    return html`<label class="aspect-choice"><input type="checkbox" checked=${selected.includes(aspect.id)} onChange=${toggle} /><span><strong>${aspect.label}</strong>${aspect.qualifier && html`<small>${aspect.qualifier}</small>`}${showProvider && html`<small class="aspect-provider">${providerLabel}</small>`}</span><em>${aspect.unit || aspect.kind}</em></label>`;
  }

  function AspectPicker({meta, pins, selected, write, toast}) {
    const pinProviders = new Set(pins.map(pin => pinParts(pin, meta.providers).provider).filter(Boolean).map(provider => provider.id));
    const available = meta.aspects.filter(aspect => pinProviders.has(aspect.provider_id));
    const availableIds = new Set(available.map(aspect => aspect.id));
    const visibleSelected = selected.filter(id => availableIds.has(id));
    const regular = available.filter(aspect => !aspect.squelched);
    const squelched = available.filter(aspect => aspect.squelched);
    const ambiguous = ambiguousAspectIds(available);
    const providerLabels = Object.fromEntries(meta.providers.map(provider => [provider.id, provider.label]));
    return html`<section class="aspect-picker" aria-labelledby="aspects-title"><header><p>02 / dimensions</p><h2 id="aspects-title">Aspects</h2></header>
      ${meta.categories.map(category => {
        const aspects = regular.filter(aspect => aspect.category === category);
        return aspects.length ? html`<fieldset key=${category}><legend>${category}</legend>${aspects.map(aspect => html`<${AspectChoice} key=${aspect.id} aspect=${aspect} selected=${visibleSelected} write=${write} toast=${toast} showProvider=${ambiguous.has(aspect.id)} providerLabel=${providerLabels[aspect.provider_id]} />`)}</fieldset>` : null;
      })}
      ${squelched.length ? html`<details class="squelched-aspects"><summary>Benchmarks / other squelched <span>${squelched.length}</span></summary>${meta.categories.map(category => {
        const aspects = squelched.filter(aspect => aspect.category === category);
        return aspects.length ? html`<fieldset key=${category}><legend>${category}</legend>${aspects.map(aspect => html`<${AspectChoice} key=${aspect.id} aspect=${aspect} selected=${visibleSelected} write=${write} toast=${toast} showProvider=${ambiguous.has(aspect.id)} providerLabel=${providerLabels[aspect.provider_id]} />`)}</fieldset>` : null;
      })}</details>` : null}
      ${pins.length && !available.length ? html`<p class="aside-note">No timeline aspects are available for these providers.</p>` : null}
    </section>`;
  }

  function cssSeries(index) {
    return getComputedStyle(document.documentElement).getPropertyValue(`--series-${index + 1}`).trim();
  }
  function cssToken(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function localDayFromEpoch(value) {
    const date = new Date(value * 1000);
    const pad = part => String(part).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  }
  function epochForDay(value) { return Date.parse(`${value}T12:00:00Z`) / 1000; }

  function focusPlotSeries(plots, model, focus) {
    for (const record of plots.current.values()) {
      if (!focus) { record.u.setSeries(null, {focus: false}); continue; }
      const index = record.models.indexOf(model) + 1;
      if (index > 0) record.u.setSeries(index, {focus: true});
    }
  }

  function setTimelineCursor(plots, epoch) {
    for (const record of plots.current.values()) {
      const left = epoch == null ? -10 : record.u.valToPos(epoch, "x");
      record.u.setCursor({left, top: -10});
    }
  }

  function TimelinePanel({aspect, axis, items, pins, plots, write}) {
    const host = useRef(null);
    useEffect(() => {
      if (!host.current || !axis.length) return;
      let zoomTimer = null, ready = false;
      const x = axis.map(point => Date.parse(point.completed_at) / 1000);
      const models = items.map(item => item.model);
      const queueZoomWrite = (min, max) => {
        clearTimeout(zoomTimer);
        zoomTimer = setTimeout(() => {
          if (Number.isFinite(min) && Number.isFinite(max)) write({from: localDayFromEpoch(min), to: localDayFromEpoch(max)});
        }, 220);
      };
      const options = {
        width: Math.max(320, host.current.clientWidth), height: 260,
        scales: {x: {time: true}},
        axes: [
          {stroke: cssToken("--ink-muted"), grid: {stroke: cssToken("--border"), width: 1}, ticks: {stroke: cssToken("--border"), width: 1}},
          {label: aspect.unit || "value", size: 70, stroke: cssToken("--ink-muted"), grid: {stroke: cssToken("--border"), width: 1}, ticks: {stroke: cssToken("--border"), width: 1}}
        ],
        cursor: {drag: {x: true, y: false, setScale: true}, sync: {key: "ms-browse"}},
        legend: {show: false},
        series: [{label: "Observed at"}, ...items.map(item => {
          const index = pins.indexOf(item.model);
          return {label: item.model, stroke: cssSeries(index), width: 2, spanGaps: false, paths: uPlot.paths.stepped({align: 1})};
        })],
        hooks: {ready: [() => { ready = true; }], setScale: [(u, key) => {
          if (!ready || key !== "x") return;
          queueZoomWrite(u.scales.x.min, u.scales.x.max);
        }]}
      };
      const u = new uPlot(options, [x, ...items.map(item => item.values)], host.current);
      const over = u.root.querySelector(".u-over");
      let pointerStart = null;
      const pointerDown = event => {
        if (event.pointerType === "mouse" && event.button !== 0) return;
        pointerStart = event.clientX;
      };
      const pointerUp = event => {
        if (pointerStart == null) return;
        const start = pointerStart;
        pointerStart = null;
        if (Math.abs(event.clientX - start) < 6) return;
        const bounds = over.getBoundingClientRect();
        const left = Math.max(0, Math.min(bounds.width, start - bounds.left));
        const right = Math.max(0, Math.min(bounds.width, event.clientX - bounds.left));
        const values = [u.posToVal(left, "x"), u.posToVal(right, "x")].sort((a, b) => a - b);
        queueZoomWrite(values[0], values[1]);
      };
      over.addEventListener("pointerdown", pointerDown);
      over.addEventListener("pointerup", pointerUp);
      plots.current.set(aspect.id, {u, models});
      const observer = new ResizeObserver(entries => {
        const width = Math.floor(entries[0].contentRect.width);
        if (width > 0 && width !== u.width) u.setSize({width, height: 260});
      });
      observer.observe(host.current);
      return () => { ready = false; clearTimeout(zoomTimer); over.removeEventListener("pointerdown", pointerDown); over.removeEventListener("pointerup", pointerUp); observer.disconnect(); plots.current.delete(aspect.id); u.destroy(); };
    }, [aspect.id, axis, items, pins, write]);
    return html`<div ref=${host} class="plot-host"></div>`;
  }

  function listToneAt(hashes, index) {
    let tone = 0, previous = null;
    for (let position = 0; position <= index; position += 1) {
      const hash = hashes[position];
      if (hash == null) continue;
      if (previous != null && hash !== previous) tone = tone ? 0 : 1;
      previous = hash;
    }
    return tone;
  }

  function StateStrip({aspect, axis, items, pins, providers}) {
    return html`<div class="state-strip" style=${`--axis-count: ${Math.max(1, axis.length)}`}>
      ${pins.map((pin, pinIndex) => {
        const item = items.find(value => value.model === pin);
        return html`<div class="state-strip-row" key=${pin}><strong title=${pin}><i style=${`background: var(--series-${pinIndex + 1})`}></i>${pinParts(pin, providers).model}</strong><div>${axis.map((point, index) => {
          const value = item ? item.values[index] : null;
          const hash = item && item.list_hash[index];
          const label = aspect.kind === "boolean" ? (value === null ? "missing" : value ? "true" : "false") : value === null ? "missing" : aspect.kind === "list" ? `${value} members · ${hash || "empty"}` : String(value);
          let state = "missing";
          if (aspect.kind === "boolean") state = value === null ? "missing" : value ? "true" : "false";
          else if (value !== null) state = `list-${listToneAt(aspect.kind === "list" ? item.list_hash : item.values, index)}`;
          return html`<span key=${`${point.scrape_id}-${point.provider_id}`} class=${state} title=${`${point.date} · ${label}`}></span>`;
        })}</div></div>`;
      })}
    </div>`;
  }

  function eventTone(event) {
    if (event.semantic === "cost") return event.direction === "up" ? "cost-up" : event.direction === "down" ? "cost-down" : "dim";
    if (event.semantic === "capacity") return "capacity";
    if (event.semantic === "capability" || event.kind === "list") return "capability";
    if (event.semantic === "coverage") return event.direction === "added" ? "presence-added" : "presence-removed";
    return "dim";
  }

  function allocateEventLanes(events) {
    const counts = new Map();
    let max = 1;
    const allocated = events.map(event => {
      const lane = counts.get(event.date) || 0;
      counts.set(event.date, lane + 1);
      max = Math.max(max, lane + 1);
      return {...event, lane};
    });
    return {events: allocated, max};
  }

  function EventRail({events, from, to, plots, openRaw}) {
    const start = epochForDay(from), end = epochForDay(to), span = Math.max(86400, end - start);
    const lanes = allocateEventLanes(events);
    return html`<section class="event-rail" aria-labelledby="rail-title"><header><div><p>03 / interventions</p><h2 id="rail-title">Event rail</h2></div><span>${events.length} events</span></header><div class="rail-track" style=${`--rail-lanes: ${lanes.max}`}>${lanes.events.map(event => {
      const offset = Math.max(0, Math.min(100, (epochForDay(event.date) - start) / span * 100));
      return html`<button type="button" key=${event.change_id} class=${`event-mark ${eventTone(event)}${event.squelched ? " is-squelched" : ""}`} style=${`left: ${offset}%; --rail-lane: ${event.lane}`} aria-label=${`${event.date}: ${event.model}, ${event.field || event.kind}`} title=${`${event.date} · ${event.model} · ${event.field || event.kind}`} onClick=${() => openRaw(event.change_id)} onMouseEnter=${() => setTimelineCursor(plots, epochForDay(event.date))} onMouseLeave=${() => setTimelineCursor(plots, null)} onFocus=${() => setTimelineCursor(plots, epochForDay(event.date))} onBlur=${() => setTimelineCursor(plots, null)}></button>`;
    })}</div></section>`;
  }

  function PanelStack({meta, aspects, pins, data, plots, write, themeKey}) {
    const lookup = new Map(meta.aspects.map(aspect => [aspect.id, aspect]));
    const selectedAspects = aspects.map(id => lookup.get(id)).filter(Boolean);
    const ambiguous = ambiguousAspectIds(selectedAspects);
    const providerLabels = Object.fromEntries(meta.providers.map(provider => [provider.id, provider.label]));
    return html`<div class="panel-stack">${aspects.map(aspectId => {
      const aspect = lookup.get(aspectId);
      if (!aspect) return null;
      const items = (data.series || []).filter(item => item.aspect === aspect.id);
      const state = aspect.kind === "boolean" || aspect.kind === "list" || aspect.kind === "scalar";
      return html`<section class="timeline-panel instrument" key=${`${aspect.id}:${themeKey}`}><header class="panel-heading"><div><p>${aspect.category}</p><h2>${aspect.label}${aspect.qualifier ? html`<small>${aspect.qualifier}</small>` : null}${ambiguous.has(aspect.id) ? html`<small class="panel-provider">${providerLabels[aspect.provider_id]}</small>` : null}</h2></div><span>${aspect.unit || aspect.kind}</span></header>
        <div class="panel-legend">${items.map(item => { const index = pins.indexOf(item.model); return html`<button type="button" key=${item.model} onMouseEnter=${() => focusPlotSeries(plots, item.model, true)} onMouseLeave=${() => focusPlotSeries(plots, item.model, false)} onFocus=${() => focusPlotSeries(plots, item.model, true)} onBlur=${() => focusPlotSeries(plots, item.model, false)}><i style=${`background: var(--series-${index + 1})`}></i>${pinParts(item.model, meta.providers).model}</button>`; })}</div>
        ${state ? html`<${StateStrip} aspect=${aspect} axis=${data.axis} items=${items} pins=${pins} providers=${meta.providers} />` : html`<${TimelinePanel} aspect=${aspect} axis=${data.axis} items=${items} pins=${pins} plots=${plots} write=${write} />`}
      </section>`;
    })}</div>`;
  }

  function Models({meta, state, write, inputRef, openRaw, reportError, toast, themeKey}) {
    const pins = state.pins || [], aspects = state.aspects || [];
    const pinProviders = new Set(pins.map(pin => pinParts(pin, meta.providers).provider).filter(Boolean).map(provider => provider.id));
    const aspectLookup = new Map(meta.aspects.map(aspect => [aspect.id, aspect]));
    const activeAspects = aspects.filter(id => aspectLookup.has(id) && pinProviders.has(aspectLookup.get(id).provider_id));
    const params = {models: pins, aspects: activeAspects, providers: state.providers, from: state.from, to: state.to, detail: state.detail};
    const enabled = Boolean(pins.length && activeAspects.length);
    const series = useApi("/api/series", params, enabled);
    const events = useApi("/api/events", {models: pins, providers: state.providers, from: state.from, to: state.to, detail: state.detail}, Boolean(pins.length));
    const plots = useRef(new Map());
    useEffect(() => reportError(series.error || events.error, series.error ? series.reload : events.reload), [series.error, events.error]);
    return html`<div class="models-view"><aside class="instrument model-controls"><${Pins} meta=${meta} pins=${pins} providers=${state.providers} write=${write} inputRef=${inputRef} toast=${toast} /><${AspectPicker} meta=${meta} pins=${pins} selected=${aspects} write=${write} toast=${toast} /></aside><main class="timeline-workbench">
      ${pins.length ? html`<${EventRail} events=${events.data || []} from=${state.from} to=${state.to} plots=${plots} openRaw=${openRaw} />` : null}
      ${!pins.length ? html`<div class="empty"><b>+</b><div><h2>Pin a model to begin</h2><p>Search the saved catalog at left, or press <kbd>/</kbd> from anywhere.</p></div></div>` : !activeAspects.length ? html`<div class="empty"><b>↗</b><div><h2>Select an aspect</h2><p>Pricing, limits, capabilities, and benchmark histories are available at left.</p></div></div>` : series.loading && !series.data ? html`<div class="loading"><i></i><p>Aligning saved snapshots…</p></div>` : series.data ? html`<${PanelStack} meta=${meta} aspects=${activeAspects} pins=${pins} data=${series.data} plots=${plots} write=${write} themeKey=${themeKey} />` : null}
    </main></div>`;
  }

  function catalogScrapes(meta, providerId) {
    return meta.scrapes.filter(scrape => scrape.provider_id === providerId && scrape.status === "success" && scrape.saved)
      .sort((left, right) => right.completed_at.localeCompare(left.completed_at) || right.scrape_id - left.scrape_id);
  }

  function defaultCatalogColumns(meta, providerId) {
    return meta.aspects.filter(aspect => aspect.provider_id === providerId && aspect.source === "column"
      && ["Pricing", "Context & Limits", "Capabilities"].includes(aspect.category)).map(aspect => aspect.id);
  }

  function scrapeLabel(scrape) {
    return `${scrape.date} · ${scrape.model_count} ${scrape.model_count === 1 ? "model" : "models"}`;
  }

  function Pickers({meta, providerId, scrapes, asOf, compare, write}) {
    const earlier = scrapes.filter(scrape => asOf && (scrape.completed_at < asOf.completed_at
      || scrape.completed_at === asOf.completed_at && scrape.scrape_id < asOf.scrape_id));
    return html`<section class="catalog-pickers instrument" aria-labelledby="catalog-pickers-title"><header class="section-heading"><div><p>01 / coordinates</p><h2 id="catalog-pickers-title">Snapshot coordinates</h2></div><span>Saved records only</span></header><div>
      <label>Provider<select value=${providerId} onChange=${event => write({providers: [event.currentTarget.value], asof: null, compare: null, cols: null, sort: null, dir: null})}>${meta.providers.map(provider => html`<option key=${provider.id} value=${provider.id} disabled=${!catalogScrapes(meta, provider.id).length}>${provider.label}</option>`)}</select></label>
      <label>As of<select value=${asOf ? String(asOf.scrape_id) : ""} onChange=${event => write({asof: event.currentTarget.value, compare: null})}>${scrapes.map(scrape => html`<option key=${scrape.scrape_id} value=${scrape.scrape_id}>${scrapeLabel(scrape)}</option>`)}</select></label>
      <label>Compare<select value=${compare ? String(compare.scrape_id) : ""} onChange=${event => write({compare: event.currentTarget.value || null})}><option value="">None</option>${earlier.map(scrape => html`<option key=${scrape.scrape_id} value=${scrape.scrape_id}>${scrapeLabel(scrape)}</option>`)}</select></label>
    </div></section>`;
  }

  function ColumnChooser({aspects, selected, write}) {
    const groups = [...new Set(aspects.map(aspect => aspect.category))];
    const toggle = id => write({cols: selected.includes(id) ? selected.filter(value => value !== id) : [...selected, id]});
    return html`<section class="column-chooser instrument" aria-labelledby="column-title"><header class="section-heading"><div><p>02 / projection</p><h2 id="column-title">Columns</h2></div><span>${selected.length} visible</span></header><div>${groups.map(group => html`<fieldset key=${group}><legend>${group}</legend>${aspects.filter(aspect => aspect.category === group).map(aspect => html`<label key=${aspect.id}><input type="checkbox" checked=${selected.includes(aspect.id)} onChange=${() => toggle(aspect.id)} /><span>${aspect.label}${aspect.qualifier || aspect.source === "path" ? html`<small>${aspect.qualifier || aspect.path}</small>` : null}</span></label>`)}</fieldset>`)}</div></section>`;
  }

  function sameList(left, right) {
    return left.length === right.length && left.every((value, index) => value === right[index]);
  }

  function cellChanged(cell) {
    return Object.prototype.hasOwnProperty.call(cell, "old_value") && JSON.stringify(cell.old_value) !== JSON.stringify(cell.value);
  }

  function SparklinePopover({meta, pin, aspect, write, close, themeKey}) {
    const host = useRef(null), closeRef = useRef(null), previous = useRef(null);
    const request = useApi("/api/series", {models: pin, aspects: aspect.id}, Boolean(pin && aspect));
    useEffect(() => {
      previous.current = document.activeElement;
      const timer = setTimeout(() => closeRef.current && closeRef.current.focus(), 0);
      const keyboard = event => { if (event.key === "Escape") close(); };
      addEventListener("keydown", keyboard);
      return () => { clearTimeout(timer); removeEventListener("keydown", keyboard); previous.current && previous.current.focus(); };
    }, []);
    useEffect(() => {
      if (!host.current || !request.data || !request.data.axis.length) return;
      const item = request.data.series[0];
      if (!item) return;
      const x = request.data.axis.map(point => Date.parse(point.completed_at) / 1000);
      const options = {
        width: Math.max(260, host.current.clientWidth), height: 80,
        scales: {x: {time: true}}, axes: [], cursor: {show: true}, legend: {show: false},
        series: [{}, {stroke: cssToken("--accent"), width: 2, spanGaps: false, paths: uPlot.paths.stepped({align: 1})}]
      };
      const plot = new uPlot(options, [x, item.values], host.current);
      return () => plot.destroy();
    }, [request.data, themeKey]);
    const parts = pinParts(pin, meta.providers), pins = [pin];
    return html`<div class="spark-layer" onMouseDown=${event => event.target === event.currentTarget && close()}><section class="spark-popover" role="dialog" aria-modal="true" aria-labelledby="spark-title"><header><div><p>${parts.model}</p><h2 id="spark-title">${aspect.label} over full history</h2></div><button ref=${closeRef} type="button" aria-label="Close sparkline" onClick=${close}>×</button></header><${ErrorBanner} error=${request.error} reload=${request.reload} />${request.loading && !request.data ? html`<div class="spark-loading">Loading series…</div>` : html`<div ref=${host} class="spark-host"></div>`}<footer><span>${aspect.unit || aspect.kind}</span><button type="button" onClick=${() => { write({view: "models", pins, aspects: [aspect.id], from: meta.date_span.first, to: meta.date_span.last}); close(); }}>Open timeline</button></footer></section></div>`;
  }

  function CatalogTable({data, aspects, state, write, page, setPage, openSparkline}) {
    const aspectLookup = new Map(aspects.map(aspect => [aspect.id, aspect]));
    const nextSortDirection = id => state.sort === id && state.dir !== "desc" ? "desc" : "asc";
    const sortAria = id => state.sort === id ? (state.dir === "desc" ? "descending" : "ascending") : "none";
    const pages = Math.max(1, Math.ceil(data.total / CATALOG_PAGE_SIZE));
    return html`<section class="catalog-table-panel instrument" aria-labelledby="catalog-table-title"><header class="catalog-toolbar"><div><p>03 / registry</p><h2 id="catalog-table-title">Model catalog</h2><span>${data.total} records</span></div><label>Filter models<input type="search" value=${state.q || ""} placeholder="ID or display name" onInput=${event => write({q: event.currentTarget.value || null})} /></label></header><div class="catalog-table-wrap"><table class="catalog-table"><thead><tr><th aria-sort=${sortAria("model_id")}><button type="button" onClick=${() => write({sort: "model_id", dir: nextSortDirection("model_id")})}>Model <span>↕</span></button></th>${aspects.map(aspect => html`<th key=${aspect.id} aria-sort=${sortAria(aspect.id)}><button type="button" onClick=${() => write({sort: aspect.id, dir: nextSortDirection(aspect.id)})}>${aspect.label}<span>↕</span></button><small>${aspect.unit || aspect.qualifier || aspect.kind}</small></th>`)}</tr></thead><tbody>${data.rows.map(row => html`<tr key=${row.model_id} class=${`catalog-row --presence-${row.presence}`}><th scope="row"><strong>${row.display_name || row.model_id}</strong><small>${row.model_id}</small>${row.presence !== "present" ? html`<em>${row.presence}</em>` : null}</th>${aspects.map(aspect => {
      const cell = row.cells[aspect.id], changed = cell && cellChanged(cell), numeric = ["price", "count", "numeric"].includes(aspect.kind);
      const content = changed ? html`<span class=${`cell-diff ${semantic(cell.change)}`}><del>${cell.old_display}</del><b>→</b><ins>${cell.display}</ins></span>` : html`<span>${cell ? cell.display : "—"}</span>`;
      return html`<td key=${aspect.id} class=${changed ? `is-changed ${semantic(cell.change)}` : ""}>${numeric && cell && (typeof cell.value === "number" || typeof cell.old_value === "number") ? html`<button type="button" class="spark-trigger" aria-label=${`Open ${aspect.label} history for ${row.model_id}`} onClick=${() => openSparkline({pin: `${data.as_of.provider_id}/${row.model_id}`, aspect: aspectLookup.get(aspect.id)})}>${content}<i>⌁</i></button>` : content}</td>`;
    })}</tr>`)}</tbody></table></div><footer class="catalog-pager"><span>Page ${page} of ${pages}</span><div><button type="button" disabled=${page <= 1} onClick=${() => setPage(Math.max(1, page - 1))}>Previous</button><button type="button" disabled=${page >= pages} onClick=${() => setPage(Math.min(pages, page + 1))}>Next</button></div></footer></section>`;
  }

  function Catalog({meta, state, write, themeKey}) {
    const providerIds = meta.providers.map(provider => provider.id);
    const availableProvider = providerIds.find(id => catalogScrapes(meta, id).length);
    const providerId = state.providers.find(id => catalogScrapes(meta, id).length) || availableProvider || state.providers[0];
    const scrapes = catalogScrapes(meta, providerId), requestedAsOf = Number(state.asof);
    const asOf = scrapes.find(scrape => scrape.scrape_id === requestedAsOf) || scrapes[0] || null;
    const compare = scrapes.find(scrape => scrape.scrape_id === Number(state.compare) && asOf && (scrape.completed_at < asOf.completed_at || scrape.completed_at === asOf.completed_at && scrape.scrape_id < asOf.scrape_id)) || null;
    const providerAspects = meta.aspects.filter(aspect => aspect.provider_id === providerId);
    const known = new Set(providerAspects.map(aspect => aspect.id));
    const requestedColumns = [...new Set((state.cols || []).filter(id => known.has(id)))];
    const columns = requestedColumns.length ? requestedColumns : defaultCatalogColumns(meta, providerId);
    const sort = state.sort === "model_id" || columns.includes(state.sort) ? state.sort : "model_id";
    const dir = ["asc", "desc"].includes(state.dir) ? state.dir : "asc";
    const [page, setPage] = useState(1), [sparkline, setSparkline] = useState(null);
    const requestKey = JSON.stringify([providerId, asOf && asOf.scrape_id, compare && compare.scrape_id, columns, state.q, sort, dir]);
    useEffect(() => {
      if (!providerId || !asOf) return;
      const patch = {};
      if (!state.providers.includes(providerId)) patch.providers = [providerId];
      if (String(state.asof || "") !== String(asOf.scrape_id)) patch.asof = String(asOf.scrape_id);
      if (state.compare && !compare) patch.compare = null;
      if (!sameList(state.cols || [], columns)) patch.cols = columns;
      if (state.sort !== sort) patch.sort = sort;
      if (state.dir !== dir) patch.dir = dir;
      if (Object.keys(patch).length) write(patch);
    }, [providerId, asOf && asOf.scrape_id, compare && compare.scrape_id, columns.join(","), JSON.stringify(state.providers), JSON.stringify(state.cols || []), state.asof, state.compare, sort, dir]);
    useEffect(() => setPage(1), [requestKey]);
    const request = useApi("/api/catalog", {provider: providerId, as_of: asOf && asOf.scrape_id, compare: compare && compare.scrape_id, columns, q: state.q, sort, dir, page, page_size: CATALOG_PAGE_SIZE}, Boolean(providerId && asOf && columns.length));
    const selectedAspects = columns.map(id => providerAspects.find(aspect => aspect.id === id)).filter(Boolean);
    const showFeed = () => {
      if (!compare || !asOf) return;
      const dates = [compare.date, asOf.date].sort();
      write({view: "activity", providers: [providerId], from: dates[0], to: dates[1]});
    };
    if (!providerId || !asOf) return html`<div class="empty"><b>∅</b><div><h2>No saved snapshots</h2><p>This provider has no successful saved scrape to browse.</p></div></div>`;
    return html`<div class="catalog-view"><aside class="catalog-controls"><${Pickers} meta=${meta} providerId=${providerId} scrapes=${scrapes} asOf=${asOf} compare=${compare} write=${write} /><${ColumnChooser} aspects=${providerAspects} selected=${columns} write=${write} />${compare ? html`<button class="feed-link" type="button" onClick=${showFeed}>Show as feed <span>↗</span></button>` : null}</aside><main class="catalog-workbench"><${ErrorBanner} error=${request.error} reload=${request.reload} />${request.loading && !request.data ? html`<div class="loading"><i></i><p>Resolving snapshot registry…</p></div>` : request.data ? html`<${CatalogTable} data=${request.data} aspects=${selectedAspects} state=${{...state, sort, dir}} write=${write} page=${page} setPage=${setPage} openSparkline=${setSparkline} />` : null}</main>${sparkline ? html`<${SparklinePopover} meta=${meta} pin=${sparkline.pin} aspect=${sparkline.aspect} write=${write} close=${() => setSparkline(null)} themeKey=${themeKey} />` : null}</div>`;
  }

  function RawDrawer({id, close}) {
    const closeRef = useRef(null), previous = useRef(null);
    const request = useApi(id ? `/api/change/${id}` : "", {}, Boolean(id));
    useEffect(() => {
      if (!id) return;
      previous.current = document.activeElement;
      const timer = setTimeout(() => closeRef.current && closeRef.current.focus(), 0);
      const keyboard = event => {
        if (event.key === "Escape") { close(); return; }
        if (event.key !== "Tab") return;
        const panel = closeRef.current && closeRef.current.closest('[role="dialog"]');
        const focusable = panel && [...panel.querySelectorAll('button, summary, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')].filter(element => !element.disabled);
        if (!focusable || !focusable.length) return;
        const first = focusable[0], last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      };
      addEventListener("keydown", keyboard);
      return () => { clearTimeout(timer); removeEventListener("keydown", keyboard); previous.current && previous.current.focus(); };
    }, [id]);
    if (!id) return null;
    const value = request.data;
    return html`<div class="drawer-layer" onMouseDown=${event => event.target === event.currentTarget && close()}><section class="drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title">
      <header><div><p>source record / ${id}</p><h2 id="drawer-title">Raw change evidence</h2></div><button ref=${closeRef} type="button" aria-label="Close raw change drawer" onClick=${close}>×</button></header>
      <${ErrorBanner} error=${request.error} reload=${request.reload} />
      ${request.loading && !value && html`<div class="loading"><i></i><p>Reading change record…</p></div>`}
      ${value && html`<div class="drawer-body"><dl><div><dt>Provider</dt><dd>${value.provider_id}</dd></div><div><dt>Model</dt><dd>${value.model_id}</dd></div><div><dt>Field</dt><dd>${value.rendered.label}${value.rendered.qualifier ? ` · ${value.rendered.qualifier}` : ""}</dd></div><div><dt>Observed</dt><dd>${value.detected_at}</dd></div></dl><p class=${`drawer-transition ${semantic(value.rendered)}`}>${value.rendered.old_display} <b>→</b> ${value.rendered.new_display}</p><div class="scrapes"><section><h3>From scrape</h3><p>${value.from_scrape ? `${value.from_scrape.date} · #${value.from_scrape.scrape_id} · ${value.from_scrape.status}` : "Initial observation"}</p></section><section><h3>To scrape</h3><p>${value.to_scrape ? `${value.to_scrape.date} · #${value.to_scrape.scrape_id} · ${value.to_scrape.status}` : "Unavailable"}</p></section></div><details open><summary>Raw JSON record</summary><pre>${JSON.stringify(value, null, 2)}</pre></details></div>`}
    </section></div>`;
  }

  function App() {
    const [state, write, replaceState] = useHashState();
    const metaRequest = useApi("/api/meta", {});
    const [theme, setTheme] = useState(() => { try { const value = localStorage.getItem(THEME_KEY); return THEMES.includes(value) ? value : "system"; } catch (error) { return "system"; } });
    const [themeRevision, repaint] = useState(0), [drawer, setDrawer] = useState(null), [toast, setToast] = useState(""), [viewError, setViewError] = useState({});
    const inputRef = useRef(null);
    useEffect(() => {
      if (theme === "system") document.documentElement.removeAttribute("data-theme"); else document.documentElement.dataset.theme = theme;
      try { localStorage.setItem(THEME_KEY, theme); } catch (error) { /* Storage may be unavailable. */ }
      const media = matchMedia("(prefers-color-scheme: dark)");
      const update = () => theme === "system" && repaint(value => value + 1);
      media.addEventListener("change", update);
      return () => media.removeEventListener("change", update);
    }, [theme]);
    useEffect(() => {
      if (!metaRequest.data) return;
      const missing = {};
      for (const [key, value] of Object.entries(defaults(metaRequest.data))) if (state[key] == null || state[key] === "" || Array.isArray(state[key]) && !state[key].length) missing[key] = value;
      if (Object.keys(missing).length) replaceState(missing);
    }, [metaRequest.data, JSON.stringify(state)]);
    useEffect(() => {
      const key = event => {
        const editing = /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName) || event.target.isContentEditable;
        if (event.key === "Escape" && drawer) { setDrawer(null); return; }
        if (editing || event.metaKey || event.ctrlKey || event.altKey) return;
        if (event.key === "/") { event.preventDefault(); if (state.view !== "models") write({view: "models"}); setTimeout(() => inputRef.current && inputRef.current.focus(), 0); }
        else if (["1","2","3"].includes(event.key)) write({view: VIEWS[Number(event.key) - 1]});
      };
      addEventListener("keydown", key); return () => removeEventListener("keydown", key);
    }, [drawer, state.view]);
    useEffect(() => { if (!toast) return; const timer = setTimeout(() => setToast(""), 4500); return () => clearTimeout(timer); }, [toast]);
    if (metaRequest.loading && !metaRequest.data) return html`<div class="boot" role="status"><i></i><p>Calibrating local history…</p></div>`;
    if (metaRequest.error && !metaRequest.data) return html`<${ErrorBanner} error=${metaRequest.error} reload=${metaRequest.reload} />`;
    const meta = metaRequest.data;
    if (!meta) return null;
    const resolved = resolveState(meta, state);
    const openModel = (provider, model, name, date) => {
      const pin = `${provider}/${model}`, pins = (resolved.pins || []).filter(value => value !== pin);
      pins.push(pin);
      if (pins.length > meta.pin_limit) { const dropped = pins.splice(0, pins.length - meta.pin_limit); setToast(`Pin limit reached. Dropped ${dropped.join(", ")}.`); }
      write({view: "models", pins, from: clamp(shiftDay(date, -30), meta.date_span), to: clamp(shiftDay(date, 30), meta.date_span)});
    };
    return html`<div class="app-shell"><div class="sr-live" role="status" aria-live="polite">${metaRequest.loading ? "Refreshing browser metadata" : ""}</div><${FilterBar} meta=${meta} state=${resolved} write=${write} theme=${theme} setTheme=${value => setTheme(THEMES.includes(value) ? value : "system")} /><${ErrorBanner} error=${metaRequest.error || viewError.error} reload=${metaRequest.error ? metaRequest.reload : viewError.reload} />
      ${!meta.date_span ? html`<div class="empty"><b>∅</b><div><h2>No saved history</h2><p>Run <code>model-sentinel scan --save</code> to create the first snapshot.</p></div></div>` : resolved.view === "activity" ? html`<${Activity} meta=${meta} state=${resolved} write=${write} openRaw=${setDrawer} openModel=${openModel} reportError=${(error,reload) => setViewError(current => current.error === error ? current : {error,reload})} />` : resolved.view === "models" ? html`<${Models} meta=${meta} state=${resolved} write=${write} inputRef=${inputRef} openRaw=${setDrawer} reportError=${(error,reload) => setViewError(current => current.error === error ? current : {error,reload})} toast=${setToast} themeKey=${`${theme}:${themeRevision}`} />` : html`<${Catalog} meta=${meta} state=${resolved} write=${write} themeKey=${`${theme}:${themeRevision}`} />`}
      <div class="toast-region" aria-live="polite">${toast && html`<div class="toast">${toast}</div>`}</div><${RawDrawer} id=${drawer} close=${() => setDrawer(null)} /></div>`;
  }
  render(html`<${ErrorBoundary}><${App} /></${ErrorBoundary}>`, document.getElementById("app"));
})();
