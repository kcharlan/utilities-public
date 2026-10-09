/* Browser state and downloads; every tax calculation belongs to Tax2Engine. */
(function () {
    'use strict';
    const html = htm.bind(preact.h);
    const {useState, useEffect, useRef} = preactHooks;
    const engine = window.Tax2Engine;
    const payload = JSON.parse(document.getElementById('tax2-data').textContent);
    const years = Object.keys(payload.federal).map(Number).sort((a, b) => b - a);
    const stateName = code => payload.states.find(state => state.code === code)?.display_name || code;
    const money = cents => `${cents < 0 ? '-' : ''}$${engine.formatCents(Math.abs(cents), {grouping: true})}`;
    const rawMoney = cents => engine.formatCents(cents).replace(/\.00$/, '').replace(/(\.\d)0$/, '$1');

    function readStorage(key) {
        try { return localStorage.getItem(key); } catch (_) { return null; }
    }
    function writeStorage(key, value) {
        try { localStorage.setItem(key, value); } catch (_) { /* Preferences are optional. */ }
    }
    function validStates(value) {
        if (!Array.isArray(value)) return [];
        const known = new Set(payload.states.map(state => state.code));
        return [...new Set(value.filter(code => known.has(code)))];
    }
    function initialStates() {
        let saved = [];
        try { saved = validStates(JSON.parse(readStorage('tax2:selected-states'))); } catch (_) { /* Use config. */ }
        if (saved.length) return saved;
        const configured = validStates(payload.config.default_states);
        return configured.length ? configured : [payload.states[0].code];
    }
    function localDate() {
        const today = new Date();
        return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
    }
    function initialMoney(cents) {
        return {text: engine.formatCents(cents, {grouping: true}), cents, error: null, focused: false};
    }
    function download(text, type, filename) {
        const url = URL.createObjectURL(new Blob([text], {type}));
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        // Let the browser activate and capture the download before revoking it.
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    }

    function MoneyInput({id, label, field, setField, primary = false}) {
        const change = text => setField(previous => ({...previous, text,
            ...engine.parseMoneyInput(text, previous.cents)}));
        const focus = event => {
            const text = field.error ? field.text : field.cents === 0 ? '' : rawMoney(field.cents);
            // Update before the browser selects text for editing; the render then agrees.
            event.currentTarget.value = text;
            event.currentTarget.select();
            setField(previous => ({...previous, focused: true, text}));
        };
        const blur = () => setField(previous => ({...previous, focused: false,
            text: previous.error ? previous.text : engine.formatCents(previous.cents, {grouping: true})}));
        return html`<div class=${primary ? 'income-primary' : ''}>
            <label for=${id} class="income-label">${label}</label>
            <div class="income-display"><span class="currency-symbol">$</span>
                <input id=${id} type="text" inputMode="decimal" class="income-input" value=${field.text}
                    aria-invalid=${!!field.error} aria-describedby=${field.error ? `${id}-error` : undefined}
                    onInput=${event => change(event.currentTarget.value)} onFocus=${focus} onBlur=${blur} placeholder="0.00" />
            </div>
            ${field.error && html`<p id=${`${id}-error`} class="field-error">${field.error}</p>`}
        </div>`;
    }

    // The builder escapes the licence notices into a <template>; mount one copy at
    // the end of the export column so they scroll with it and never extend the page.
    function LicenseNotices() {
        const slot = useRef(null);
        useEffect(() => {
            slot.current.replaceChildren(document.getElementById('tax2-licenses').content.cloneNode(true));
        }, []);
        return html`<div class="license-notices" ref=${slot}></div>`;
    }

    function ResultCard({kind, label, cents, sublabel}) {
        return html`<div class=${`result-card ${kind}`}><div class="result-label">${label}</div>
            <div class="result-amount" style=${{'--amount-length': money(cents).length}}>${money(cents)}</div><div class="result-sublabel">${sublabel}</div></div>`;
    }

    function App() {
        const [selectedStates, setSelectedStates] = useState(initialStates);
        const [year, setYear] = useState(() => years.includes(new Date().getFullYear()) ? new Date().getFullYear() : years[0]);
        const [status, setStatus] = useState('single');
        const [dark, setDark] = useState(() => readStorage('tax2:theme') === 'dark');
        const [unearned, setUnearned] = useState(() => initialMoney(1250000));
        const [earned, setEarned] = useState(() => initialMoney(0));
        const [allocations, setAllocations] = useState(() => Object.fromEntries(selectedStates.map(code =>
            [code, {text: '100', value: 100, lastValid: 100, error: null}])));
        const [qifStates, setQifStates] = useState(() => Object.fromEntries(selectedStates.map(code =>
            [code, engine.resolveStateQifDefaults(code, payload)])));
        const [qifConfig, setQifConfig] = useState(() => ({txDate: localDate(), payee: 'Estimated Taxes Withholding',
            federalExpense: 'Tax:Federal Income Tax Estimated Paid', federalTransfer: '[Federal Income Taxes]'}));
        const [downloadError, setDownloadError] = useState(null);
        useEffect(() => {
            document.documentElement.classList.toggle('dark', dark);
            writeStorage('tax2:theme', dark ? 'dark' : 'light');
        }, [dark]);

        function toggleState(code) {
            if (selectedStates.includes(code) && selectedStates.length === 1) return;
            const next = selectedStates.includes(code) ? selectedStates.filter(item => item !== code) : [...selectedStates, code];
            setAllocations(previous => Object.hasOwn(previous, code) ? previous : {...previous,
                [code]: {text: '100', value: 100, lastValid: 100, error: null}});
            setQifStates(previous => Object.hasOwn(previous, code) ? previous : {...previous,
                [code]: engine.resolveStateQifDefaults(code, payload)});
            setSelectedStates(next);
            writeStorage('tax2:selected-states', JSON.stringify(next));
        }
        function allocationInput(code, text) {
            const parsed = engine.parseAllocation(text);
            const displayed = !parsed.error && Number(text) !== parsed.value ? String(parsed.value) : text;
            setAllocations(previous => ({...previous, [code]: {text: displayed, ...parsed,
                lastValid: parsed.error ? previous[code].lastValid : parsed.value}}));
        }
        function allocationKey(code, event) {
            if (!['ArrowUp', 'ArrowDown'].includes(event.key)) return;
            event.preventDefault();
            const field = allocations[code];
            const value = field.value ?? field.lastValid;
            allocationInput(code, String(event.key === 'ArrowUp' ? Math.floor(value) + 1 : Math.ceil(value) - 1));
        }
        function updateQif(key, value) { setQifConfig(previous => ({...previous, [key]: value})); }
        function updateStateQif(code, key, value) {
            setQifStates(previous => ({...previous, [code]: {...previous[code], [key]: value}}));
        }
        const invalid = unearned.error || earned.error || selectedStates.some(code => allocations[code]?.error);
        let result = null, error = null;
        try {
            if (invalid) throw new Error('Fix the highlighted inputs.');
            result = engine.computeMonthly({earnedCents: earned.cents, unearnedCents: unearned.cents,
                filingStatus: status, year, states: selectedStates.map(code =>
                    ({code, allocation_pct: allocations[code]?.value ?? 100}))}, payload);
        } catch (failure) { error = failure.message; }
        let dateError = null;
        try { engine.parseQifDate(qifConfig.txDate); } catch (failure) { dateError = failure.message; }
        const exportValid = !!payload.federal[year] && ['single', 'married_joint'].includes(status);
        const gross = unearned.cents + earned.cents;
        const rate = cents => `${engine.ratePercent(cents, result.gross_cents, 1).toFixed(1)}% effective`;
        function exportFile(builder, type, filename) {
            try { download(builder(), type, filename); setDownloadError(null); }
            catch (failure) { setDownloadError(failure.message); }
        }
        function qifField(key, label, type = 'text') {
            return html`<div class="export-section"><label class="export-label" for=${key}>${label}</label>
                <input id=${key} type=${type} class=${key.includes('federal') ? 'category-input' : ''}
                    value=${qifConfig[key]} onInput=${event => updateQif(key, event.currentTarget.value)}
                    aria-invalid=${key === 'txDate' && !!dateError}
                    aria-describedby=${key === 'txDate' && dateError ? 'txDate-error' : undefined} />
                ${key === 'txDate' && dateError && html`<p id="txDate-error" class="field-error">${dateError}</p>`}
            </div>`;
        }
        return html`<div class="app-container">
            <aside class="sidebar"><div class="sidebar-header"><h1 class="app-title">Tax2</h1>
                <div class="app-subtitle">Professional Edition</div></div>
                <div class="control-section"><label class="control-label" for="year">Tax Year</label>
                    <div class="select-wrapper"><select id="year" value=${year} onChange=${event => setYear(Number(event.currentTarget.value))}>
                        ${years.map(value => html`<option key=${value} value=${value}>${value}</option>`)}
                    </select></div></div>
                <div class="control-section"><div class="control-label">Filing Status</div><div class="radio-group">
                    ${[['single', 'Single'], ['married_joint', 'Married Filing Jointly']].map(([value, label]) => html`
                        <div class="radio-option"><input id=${value} type="radio" name="filing" checked=${status === value}
                            onChange=${() => setStatus(value)} /><label for=${value}>${label}</label></div>`)}
                </div></div>
                <div class="control-section"><div class="control-label">States</div><div class="radio-group">
                    ${payload.states.map(state => html`<div class="radio-option" key=${state.code}>
                        <input id=${`state-${state.code}`} type="checkbox" checked=${selectedStates.includes(state.code)}
                            disabled=${selectedStates.includes(state.code) && selectedStates.length === 1}
                            onChange=${() => toggleState(state.code)} /><label for=${`state-${state.code}`}>${stateName(state.code)}</label>
                    </div>`)}
                </div></div>
                <div class="control-section"><div class="control-label">Allocation %</div><div class="radio-group">
                    ${selectedStates.map(code => html`<div key=${code}>
                        <label class="export-label" for=${`allocation-${code}`}>${stateName(code)}</label>
                        <input id=${`allocation-${code}`} type="text" inputMode="decimal" aria-label=${`${stateName(code)} allocation`}
                            aria-invalid=${!!allocations[code]?.error} value=${allocations[code]?.text ?? '100'}
                            aria-describedby=${allocations[code]?.error ? `allocation-${code}-error` : undefined}
                            onInput=${event => allocationInput(code, event.currentTarget.value)}
                            onKeyDown=${event => allocationKey(code, event)} />
                        ${allocations[code]?.error && html`<p id=${`allocation-${code}-error`} class="field-error">${allocations[code].error}</p>`}
                    </div>`)}
                </div></div>
            </aside>
            <section class="main-panel"><div class="header-bar"><div class="year-badge">FY ${year}</div>
                <button class="theme-toggle" aria-label="Toggle Theme" onClick=${() => setDark(previous => !previous)}>◐ Toggle Theme</button></div>
                <div class="income-section">
                    <${MoneyInput} id="unearned" label="Monthly Unearned Income" field=${unearned} setField=${setUnearned} primary />
                    <${MoneyInput} id="earned" label="Monthly Earned Income" field=${earned} setField=${setEarned} />
                    <div class="income-sublabel">${unearned.error || earned.error
                        ? 'Total unavailable — fix the highlighted inputs.'
                        : `Total ${money(gross)} monthly = ${money(gross * 12)} annually`}</div>
                </div>
                ${error && html`<div class="error-card" role="alert"><strong>Error:</strong> ${error}</div>`}
                ${result && html`<div class="results-grid" role="group" aria-label="Monthly tax breakdown">
                    <${ResultCard} kind="federal" label="Federal Tax" cents=${result.federal_cents} sublabel=${rate(result.federal_cents)} />
                    ${result.states.map(state => html`<${ResultCard} key=${state.code} kind="state"
                        label=${`${state.display_name}${state.allocation_pct !== 100 ? ` (${state.allocation_pct}%)` : ''}`}
                        cents=${state.state_cents} sublabel=${rate(state.state_cents)} />`)}
                </div><div class="summary-grid" role="group" aria-label="Monthly income summary">
                    <${ResultCard} kind="total" label="Total Monthly Tax" cents=${result.total_monthly_cents} sublabel=${`${result.effective_rate}% combined`} />
                    <${ResultCard} kind="net" label="Net Monthly Income" cents=${result.net_cents} sublabel="Gross minus estimated taxes" />
                </div><p class="summary-note">Net income is after the estimated taxes shown above.</p>`}
                <p class="built-at">Built ${payload.built_at}</p>
            </section>
            <aside class="export-panel"><div class="export-header"><h2 class="export-title">QIF Export</h2>
                <p class="export-description">Configure transaction details for Quicken/Moneydance import</p></div>
                ${qifField('txDate', 'Transaction Date', 'date')}${qifField('payee', 'Payee Name')}
                ${qifField('federalExpense', 'Federal Expense Category')}${qifField('federalTransfer', 'Federal Transfer Account')}
                ${selectedStates.map(code => html`<div key=${code}>${[['expense', 'Expense Category'], ['transfer', 'Transfer Account']].map(([key, label]) => html`
                    <div class="export-section"><label class="export-label" for=${`qif-${code}-${key}`}>${stateName(code)} ${label}</label>
                        <input id=${`qif-${code}-${key}`} type="text" class="category-input" value=${qifStates[code]?.[key] ?? ''}
                            onInput=${event => updateStateQif(code, key, event.currentTarget.value)} /></div>`)}
                </div>`)}
                <button class="export-button" disabled=${!result || !!dateError} onClick=${() => exportFile(
                    () => engine.buildQif(result, qifConfig, qifStates, payload), 'application/qif', 'tax_transactions.qif')}>↓ Download QIF</button>
                <div class="table-exports"><h2 class="export-title">Tax Tables</h2>
                    <p class="export-description">Export rules for ${year}; lookup income uses ${status === 'single' ? 'Single' : 'Married Filing Jointly'}.</p>
                    <button class="export-button" disabled=${!exportValid} onClick=${() => exportFile(
                        () => engine.buildRateSchedule(year, payload), 'text/markdown', `tax2_rate_schedule_${year}.md`)}>↓ Download rate schedule</button>
                    <button class="export-button" disabled=${!exportValid} onClick=${() => exportFile(
                        () => engine.buildLookupCsv(year, status, payload), 'text/csv', `tax2_lookup_${year}_${status}.csv`)}>↓ Download lookup table</button>
                </div>${downloadError && html`<p class="field-error" role="alert">${downloadError}</p>`}
                <${LicenseNotices} />
            </aside>
        </div>`;
    }
    preact.render(html`<${App} />`, document.getElementById('app'));
})();
