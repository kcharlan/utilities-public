/* Pure calculation surface. Rules come only from the schema-1 page payload. */
(function () {
    'use strict';

    function nonnegative(value, label) {
        if (!Number.isFinite(value) || value < 0) {
            throw new Error(`Invalid ${label}`);
        }
    }

    function safeInteger(value, label) {
        if (!Number.isSafeInteger(value)) throw new Error(`Invalid ${label}`);
        return value;
    }

    function validateIncome(earned, unearned) {
        nonnegative(earned, 'earned income');
        nonnegative(unearned, 'unearned income');
    }

    function applyBrackets(taxable, brackets) {
        let tax = 0;
        let prevCap = 0;
        for (const bracket of brackets) {
            const cap = bracket.up_to != null ? bracket.up_to : taxable;
            if (taxable > prevCap) {
                const slice = Math.min(taxable, cap) - prevCap;
                if (slice > 0) tax += slice * bracket.rate;
                prevCap = cap;
            }
            if (bracket.up_to == null || taxable <= cap) break;
        }
        return Math.max(tax, 0);
    }

    function computeTax(income, taxRules, filingStatus) {
        validateIncome(income.earned_income, income.unearned_income);
        if (!['single', 'married_joint'].includes(filingStatus) ||
            !taxRules.filing_statuses.includes(filingStatus)) {
            throw new Error(`Unsupported filing status: ${filingStatus}`);
        }
        let base = 0;
        for (const component of taxRules.components) {
            if (!component.enabled) continue;
            if (!Object.hasOwn(component.standard_deduction, filingStatus) ||
                !Object.hasOwn(component.brackets, filingStatus)) {
                throw new Error(`Missing component data for filing status: ${filingStatus}`);
            }
            let applicable = 0;
            for (const incomeClass of component.applies_to) {
                applicable += income[`${incomeClass}_income`];
            }
            const taxable = Math.max(0, applicable - component.standard_deduction[filingStatus]);
            base += applyBrackets(taxable, component.brackets[filingStatus]);
        }
        let creditTotal = 0;
        for (const credit of taxRules.credits) {
            let effective = 0;
            if (credit.amount != null) effective = Math.max(effective, credit.amount);
            // Preserve the Python engine's one-child placeholder and max semantics.
            if (credit.amount_per_child != null) effective = Math.max(effective, credit.amount_per_child);
            if (credit.phaseout) {
                const over = Math.max(0, income.earned_income + income.unearned_income - credit.phaseout.start_income);
                const reduction = over * credit.phaseout.rate_per_dollar;
                effective = Math.max(0, effective - reduction);
            }
            if (credit.refundable_cap != null) effective = Math.min(effective, credit.refundable_cap);
            creditTotal += effective;
        }
        return Math.max(0, base - creditTotal);
    }

    function computeAnnual(earned, unearned, filingStatus, year, states, rules) {
        validateIncome(earned, unearned);
        if (!Number.isSafeInteger(year)) throw new Error('Invalid year');
        if (!rules || rules.schema !== 1) throw new Error('Unsupported rules schema');
        if (!Array.isArray(states) || states.length === 0) throw new Error('Select at least one state');
        const federalRules = rules.federal[year];
        if (!federalRules) throw new Error(`Federal has no rules for ${year}`);
        const federalAnnual = computeTax({earned_income: earned * 12,
            unearned_income: unearned * 12}, federalRules, filingStatus);
        const stateResults = states.map(selection => {
            nonnegative(selection.allocation_pct, 'state allocation');
            if (selection.allocation_pct > 100) throw new Error('Invalid state allocation');
            const state = rules.states.find(item => item.code === selection.code);
            if (!state) throw new Error(`Unknown state: ${selection.code}`);
            const stateRules = state.rules[year];
            if (!stateRules) {
                const available = state.years.length ? `[${state.years.join(', ')}]` : 'none';
                throw new Error(`State ${selection.code} has no rules for ${year}. Available years: ${available}`);
            }
            const factor = selection.allocation_pct / 100;
            const annual = computeTax({earned_income: earned * 12 * factor,
                unearned_income: unearned * 12 * factor}, stateRules, filingStatus);
            return {code: selection.code, display_name: stateRules.display_name || state.display_name || selection.code,
                allocation_pct: selection.allocation_pct, annual};
        });
        return {federal_annual: federalAnnual, states: stateResults};
    }

    function ceilScaled(x, scale) {
        if (!Number.isFinite(x) || x < 0) throw new Error('Invalid rounding input');
        const c = x * scale;
        const r = Math.round(c);
        return Math.abs(c - r) <= 1e-6 ? r : Math.ceil(c);
    }

    function ceilCents(x) {
        return ceilScaled(x, 100);
    }

    function ratePercent(taxCents, grossCents, decimals) {
        const scale = 10 ** decimals;
        return grossCents > 0 ? ceilScaled(taxCents / grossCents * 100, scale) / scale : 0;
    }

    function computeMonthly(input, rules) {
        const {earnedCents, unearnedCents, filingStatus, year, states} = input;
        safeInteger(earnedCents, 'earned cents');
        safeInteger(unearnedCents, 'unearned cents');
        validateIncome(earnedCents, unearnedCents);
        const gross = safeInteger(earnedCents + unearnedCents, 'gross cents');
        const annual = computeAnnual(earnedCents / 100, unearnedCents / 100,
            filingStatus, year, states, rules);
        const federal = safeInteger(ceilCents(annual.federal_annual / 12), 'federal cents');
        const stateResults = annual.states.map(state => ({code: state.code,
            display_name: state.display_name, allocation_pct: state.allocation_pct,
            state_cents: safeInteger(ceilCents(state.annual / 12), 'state cents')}));
        let total = federal;
        for (const state of stateResults) total = safeInteger(total + state.state_cents, 'total cents');
        const net = safeInteger(gross - total, 'net cents');
        return {federal_cents: federal, states: stateResults, total_monthly_cents: total,
            gross_cents: gross, net_cents: net,
            effective_rate: ratePercent(total, gross, 2)};
    }

    function groupDigits(text) {
        return text.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    }

    function formatCents(cents, {grouping = false} = {}) {
        safeInteger(cents, 'cents');
        const magnitude = Math.abs(cents);
        let dollars = String(Math.floor(magnitude / 100));
        if (grouping) dollars = groupDigits(dollars);
        return `${cents < 0 ? '-' : ''}${dollars}.${String(magnitude % 100).padStart(2, '0')}`;
    }

    function parseMoneyInput(text, previousCents) {
        const raw = text.trim();
        if (raw === '') return {cents: 0, error: null, inProgress: false};
        if (raw === '.') return {cents: previousCents, error: null, inProgress: true};
        if (!/^\s*(?:(?:\d{1,3}(?:,\d{3}){1,3}|\d{1,12})(?:\.\d{0,2})?|\.\d{1,2})\s*$/.test(text)) {
            return {cents: previousCents, error: 'Enter a dollar amount, up to 2 decimal places', inProgress: false};
        }
        const [dollars, fraction = ''] = raw.replace(/,/g, '').split('.');
        return {cents: Number(dollars) * 100 + Number(fraction.padEnd(2, '0')),
            error: null, inProgress: false};
    }

    function parseAllocation(text) {
        const number = /^\s*[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)\s*$/.test(text) ? Number(text) : NaN;
        return Number.isFinite(number)
            ? {value: Math.max(0, Math.min(100, number)), error: null}
            : {value: null, error: 'Enter 0–100'};
    }

    function resolveStateQifDefaults(code, rules) {
        const state = rules.states.find(item => item.code === code);
        const override = rules.config.qif_overrides[code] || {};
        const qif = state?.qif || {};
        return {expense: override.state_expense || qif.state_expense || 'Tax:State Income Tax Estimated Paid',
            transfer: override.state_transfer || qif.state_transfer || `[${code} State Income Taxes]`};
    }

    function parseQifDate(text) {
        const match = typeof text === 'string' && /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
        if (!match) throw new Error('Enter a valid transaction date');
        const [year, month, day] = match.slice(1).map(Number);
        const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
        const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
        if (year < 1 || month < 1 || month > 12 || day < 1 || day > days[month - 1]) {
            throw new Error('Enter a valid transaction date');
        }
        return {year, month, day};
    }

    // The UI binds txDate/payee/federalExpense/federalTransfer directly.
    function buildQif(result, qifConfig, qifStates, rules) {
        const {year, month, day} = parseQifDate(qifConfig.txDate);
        const full = `${String(month).padStart(2, '0')}/${String(day).padStart(2, '0')}/${String(year).padStart(4, '0')}`;
        const short = full.slice(0, 6) + String(year % 100).padStart(2, '0');
        const lines = ['!Type:Bank'];
        const pair = (cents, label, expense, transfer) => {
            safeInteger(cents, 'QIF cents');
            nonnegative(cents, 'QIF cents');
            const amount = formatCents(cents);
            for (const [sign, account] of [['-', expense], ['', transfer]]) {
                lines.push(`D${short}`, `T${sign}${amount}`, `P${qifConfig.payee ?? 'Estimated Taxes Withholding'}`,
                    `M${label} - ${full}`, `L${account}`, '^');
            }
        };
        pair(result.federal_cents, 'Estimated Federal taxes',
            qifConfig.federalExpense ?? 'Tax:Federal Income Tax Estimated Paid',
            qifConfig.federalTransfer ?? '[Federal Income Taxes]');
        for (const state of result.states) {
            const defaults = resolveStateQifDefaults(state.code, rules);
            const edited = qifStates[state.code] || {};
            pair(state.state_cents, result.states.length >= 2 ? `Estimated ${state.code} State taxes` : 'Estimated State taxes',
                edited.expense || defaults.expense, edited.transfer || defaults.transfer);
        }
        return lines.join('\n');
    }

    const bases = ['total income', 'earned income only', 'unearned income only'];
    function componentBasis(component) {
        if (component.applies_to.includes('earned') && component.applies_to.includes('unearned')) return 0;
        return component.applies_to.includes('earned') ? 1 : 2;
    }

    function exportJurisdictions(year, rules) {
        if (!rules || rules.schema !== 1) throw new Error('Unsupported rules schema');
        if (!Number.isSafeInteger(year)) throw new Error('Invalid year');
        if (!rules.federal[year]) throw new Error(`Federal has no rules for ${year}`);
        return [{code: 'Federal', rule: rules.federal[year]}, ...rules.states
            .filter(state => state.rules[year])
            .slice().sort((a, b) => a.code < b.code ? -1 : a.code > b.code ? 1 : 0)
            .map(state => ({code: state.code, rule: state.rules[year]}))];
    }

    // Move decimal digits, including exponent expansion; never multiply rates.
    function exactNumber(value, shift = 0, grouping = true) {
        if (!Number.isFinite(value)) throw new Error('Invalid rule number');
        const sign = value < 0 ? '-' : '';
        const [mantissa, exponent = '0'] = String(Math.abs(value)).split('e');
        const [whole, fraction = ''] = mantissa.split('.');
        const digits = whole + fraction;
        const point = whole.length + Number(exponent) + shift;
        let integer, decimal;
        if (point <= 0) { integer = '0'; decimal = '0'.repeat(-point) + digits; }
        else if (point >= digits.length) { integer = digits + '0'.repeat(point - digits.length); decimal = ''; }
        else { integer = digits.slice(0, point); decimal = digits.slice(point); }
        integer = integer.replace(/^0+(?=\d)/, '');
        decimal = decimal.replace(/0+$/, '');
        if (grouping) integer = groupDigits(integer);
        return sign + integer + (decimal ? '.' + decimal : '');
    }

    function buildLookupCsv(year, filingStatus, rules) {
        if (!['single', 'married_joint'].includes(filingStatus)) {
            throw new Error(`Unsupported filing status: ${filingStatus}`);
        }
        const groups = [];
        for (const {code, rule} of exportJurisdictions(year, rules)) {
            for (let basis = 0; basis < bases.length; basis++) {
                const components = rule.components.filter(c => c.enabled && componentBasis(c) === basis);
                if (components.length) groups.push({code, basis,
                    rule: {...rule, components, credits: basis === 0 ? rule.credits : []}});
            }
        }
        const csvField = text => /[,"\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
        const lines = [['MonthlyIncome', ...groups.map(g => `${g.code} monthly tax (${bases[g.basis]})`)]
            .map(csvField).join(',')];
        for (let monthly = 0; monthly <= 500000; monthly += 50) {
            const cells = groups.map(group => {
                const income = {earned_income: group.basis === 1 ? monthly * 12 : 0,
                    unearned_income: group.basis === 1 ? 0 : monthly * 12};
                return formatCents(ceilCents(computeTax(income, group.rule, filingStatus) / 12));
            });
            lines.push([formatCents(monthly * 100), ...cells].join(','));
        }
        return lines.join('\n');
    }

    function markdownText(value) {
        return String(value).replace(/\\/g, '\\\\').replace(/([`*_\[\]<>|&~#])/g, '\\$1').replace(/[\r\n]+/g, ' ');
    }

    function buildRateSchedule(year, rules) {
        const lines = [`# Tax2 rate schedule — ${year}`, '', `Build time: ${markdownText(rules.built_at)}`,
            `Rules year: ${year}`, 'This is not tax advice. Verify rules and eligibility before use.', '',
            '## Manual procedure', '',
            '1. Multiply monthly income by 12.',
            '2. For a state, multiply earned and unearned income by its allocation first. Federal uses unallocated total income.',
            "3. Use each component's income basis. Subtract its standard deduction, flooring taxable income at 0.",
            '4. Find the bracket and apply its formula.',
            '5. For a jurisdiction with credits, subtract them once from the annual tax of its total-income components, flooring at zero (see Credits).',
            "6. Divide each component's annual tax (or the credited total-income section's) by 12 and round up to the next cent.",
            '7. Add the results.', '',
            '## Caveats and lookup procedure', '',
            'Every computed amount rounds up to the next cent. The calculator rounds each jurisdiction once; individually rounded schedule components and lookup columns can overstate a manual total by a few cents.',
            'Lookup tables apply no state allocation. Multiply monthly income by allocation before lookup, then use total, earned-only or unearned-only income for the matching columns and add them. Federal uses unallocated total income.',
            'Not modelled: preferential rates on qualified dividends and long-term capital gains, net investment income tax (NIIT), FICA and self-employment tax.',
            'Credits couple the components: subtract once in the total-income section/column and floor each column at zero. Credited jurisdictions have approximate lookups. With no enabled total-income component, credits are omitted, which overestimates tax.',
            'Between rows, use linear interpolation and round up to the next cent. Within a straight segment this never falls below the calculator and can add about 2 cents per column.',
            'At a standard-deduction threshold, bracket boundary ((deduction + up_to) / 12), credit phaseout or cap point, interpolation is approximate. Across a bend where the rate drops it can underestimate; use the rate schedule for an exact figure.',
            'Use the next row up to never underestimate: nonnegative rates and valid credits make tax nondecreasing. Above 500,000 monthly income, use the schedule.',
            'Nearest-row lookup without interpolation can be off by $25 × the marginal rate per month per column (about $9.25 at 37%); totals across columns can be off by more.', ''];
        for (const {code, rule} of exportJurisdictions(year, rules)) {
            lines.push(`## ${markdownText(code)}`, '');
            for (const status of ['single', 'married_joint']) {
                lines.push(`### ${status === 'single' ? 'Single' : 'Married Filing Jointly'}`, '');
                for (const component of rule.components) {
                    lines.push(`#### ${markdownText(component.label || component.name)}`, '');
                    if (!component.enabled) { lines.push('disabled — not included', ''); continue; }
                    if (!Object.hasOwn(component.standard_deduction, status) || !Object.hasOwn(component.brackets, status)) {
                        throw new Error(`Missing component data for filing status: ${status}`);
                    }
                    lines.push(`Income basis: ${bases[componentBasis(component)]}`,
                        `Standard deduction: ${exactNumber(component.standard_deduction[status])}`, '',
                        '| Over | But not over | Tax = base + rate × excess over |', '| --- | --- | --- |');
                    let lower = 0;
                    const brackets = component.brackets[status];
                    for (const bracket of brackets) {
                        const base = formatCents(ceilCents(applyBrackets(lower, brackets)), {grouping: true});
                        lines.push(`| ${exactNumber(lower)} | ${bracket.up_to == null ? 'No limit' : exactNumber(bracket.up_to)} | ${base} + ${exactNumber(bracket.rate, 2, false)}% × excess over ${exactNumber(lower)} |`);
                        lower = bracket.up_to;
                    }
                    lines.push('');
                }
            }
            if (rule.credits.length) {
                lines.push('### Credits', '', 'Lookups for this jurisdiction are approximate.');
                lines.push('For each credit, start with max(0, amount, amount per child), using one child. Subtract the phaseout reduction, floor at zero, then apply the refundable cap. Sum credits and subtract once from annual total-income tax, flooring tax at zero.');
                if (!rule.components.some(c => c.enabled && componentBasis(c) === 0)) {
                    lines.push('Credits omitted: no enabled total-income component; omission overestimates tax.');
                }
                for (const credit of rule.credits) {
                    const fields = [];
                    if (credit.amount != null) fields.push(`amount ${exactNumber(credit.amount)}`);
                    if (credit.amount_per_child != null) fields.push(`amount per child ${exactNumber(credit.amount_per_child)} (one-child placeholder; use the greater of amount and amount per child, floored at zero)`);
                    if (credit.phaseout) fields.push(`phaseout starts at total annual income ${exactNumber(credit.phaseout.start_income)}, reduction ${exactNumber(credit.phaseout.rate_per_dollar)} per dollar above it, flooring credit at zero`);
                    if (credit.refundable_cap != null) fields.push(`refundable cap ${exactNumber(credit.refundable_cap)}`);
                    lines.push(`- ${markdownText(credit.name || 'Credit')}: ${fields.join('; ')}.`);
                }
                lines.push('');
            }
        }
        return lines.join('\n');
    }

    window.Tax2Engine = Object.freeze({applyBrackets, computeTax, computeAnnual,
        computeMonthly, ceilScaled, ceilCents, ratePercent, formatCents, parseMoneyInput, parseAllocation, resolveStateQifDefaults,
        parseQifDate, buildQif, buildRateSchedule, buildLookupCsv});
})();
