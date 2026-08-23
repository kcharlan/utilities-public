(() => {
  "use strict";
  const {h, render} = preact;
  const {useState, useEffect, useMemo, useRef, useCallback} = preactHooks;
  const html = htm.bind(h);
  const THEME_KEY = "model_sentinel.browse.theme";
  const THEMES = ["system", "light", "dark"];
  const VIEWS = ["activity", "models", "catalog"];
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
    for (const key of ["models", "pins", "aspects", "cols"]) resolved[key] = list(state[key]);
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

  function Placeholder({view, inputRef}) {
    const models = view === "models";
    return html`<section class="instrument placeholder"><p>${models ? "timeline laboratory" : "snapshot registry"}</p><h2>${models ? "Models" : "Catalog"}</h2><p>${models ? "Pinned model timelines are the next instrument in this console." : "Snapshot comparison is reserved for the next console module."}</p>${models && html`<label>Model typeahead<input ref=${inputRef} type="search" placeholder="Available with model timelines" readonly aria-describedby="model-staged" /></label>`}<span id=${models ? "model-staged" : undefined}>Module staged · state preserved</span></section>`;
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
    const [, repaint] = useState(0), [drawer, setDrawer] = useState(null), [toast, setToast] = useState(""), [viewError, setViewError] = useState({});
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
      ${!meta.date_span ? html`<div class="empty"><b>∅</b><div><h2>No saved history</h2><p>Run <code>model-sentinel scan --save</code> to create the first snapshot.</p></div></div>` : resolved.view === "activity" ? html`<${Activity} meta=${meta} state=${resolved} write=${write} openRaw=${setDrawer} openModel=${openModel} reportError=${(error,reload) => setViewError(current => current.error === error ? current : {error,reload})} />` : html`<${Placeholder} view=${resolved.view} inputRef=${inputRef} />`}
      <div class="toast-region" aria-live="polite">${toast && html`<div class="toast">${toast}</div>`}</div><${RawDrawer} id=${drawer} close=${() => setDrawer(null)} /></div>`;
  }
  render(html`<${ErrorBoundary}><${App} /></${ErrorBoundary}>`, document.getElementById("app"));
})();
