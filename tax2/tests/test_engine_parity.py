"""Execute the pure browser engine from private file pages against frozen Python output."""
import json
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from taxkit.page import build_payload
from tests.test_page_build import REPO_ROOT, guard_browser_errors

PROJECT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT / "tests" / "fixtures" / "parity"
ORACLE = json.loads((FIXTURES / "python_parity.json").read_text())


@pytest.fixture
def engine_page(tmp_path, monkeypatch):
    assert not tmp_path.resolve().is_relative_to(REPO_ROOT.resolve())
    tmp_path.chmod(0o700)
    monkeypatch.setenv("TAX2_HOME", str(tmp_path / "runtime"))
    path = tmp_path / "engine.html"
    path.write_text('<!doctype html><meta charset="utf-8"><script>' +
                    (PROJECT / "web" / "engine.js").read_text() + '</script>')
    path.chmod(0o600)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(service_workers="block")
        requests = []
        context.on("request", lambda request: requests.append(request.url)
                   if not request.url.startswith("file:") else None)
        context.route("**/*", lambda route: route.continue_()
                      if route.request.url.startswith("file:") else route.abort())
        page = context.new_page()
        with guard_browser_errors(page):
            page.goto(path.as_uri())
            yield page
            assert requests == []
        browser.close()


def test_exact_frozen_annual_and_safe_monthly_parity(engine_page):
    payloads = {root: build_payload(FIXTURES / root / "rules", rules_source="custom")
                for root in ("bundled", "synthetic")}
    results = engine_page.evaluate("""({cases, payloads}) => cases.map(c => {
        const e = window.Tax2Engine, i = c.input;
        const annual = e.computeAnnual(i.monthly_earned, i.monthly_unearned,
            i.filing_status, i.year, i.states, payloads[c.root]);
        const federal = e.ceilCents(annual.federal_annual / 12);
        const states = annual.states.map(s => e.ceilCents(s.annual / 12));
        const earned = i.monthly_earned * 100, unearned = i.monthly_unearned * 100;
        const monthly = Number.isSafeInteger(earned) && Number.isSafeInteger(unearned)
            ? e.computeMonthly({earnedCents: earned, unearnedCents: unearned,
                filingStatus: i.filing_status, year: i.year, states: i.states}, payloads[c.root])
            : null;
        return {annual, federal, states, total: federal + states.reduce((a,b) => a+b, 0), monthly};
    })""", {"cases": ORACLE["compute_cases"], "payloads": payloads})
    whole_cent_count = 0
    for case, result in zip(ORACLE["compute_cases"], results):
        expected = case["expected"]
        # Metadata intentionally follows selected-year -> discovery -> code.
        # The old API used code directly when a selected-year label was absent.
        expected_states = []
        for state in expected["states"]:
            inventory = next(s for s in payloads[case["root"]]["states"] if s["code"] == state["code"])
            selected = inventory["rules"][str(case["input"]["year"])]
            expected_states.append({**{k: v for k, v in state.items() if k != "monthly_cents"},
                "display_name": selected.get("display_name") or inventory.get("display_name") or state["code"]})
        assert result["annual"] == {"federal_annual": expected["federal_annual"],
                "states": expected_states}, case["id"]
        assert result["federal"] == expected["federal_monthly_cents"], case["id"]
        assert result["states"] == [s["monthly_cents"] for s in expected["states"]], case["id"]
        assert result["total"] == expected["total_monthly_cents"], case["id"]
        if result["monthly"] is not None:
            whole_cent_count += 1
            monthly = result["monthly"]
            assert monthly["federal_cents"] == result["federal"], case["id"]
            assert monthly["total_monthly_cents"] == result["total"], case["id"]
            assert [s["state_cents"] for s in monthly["states"]] == result["states"], case["id"]
            gross = round(case["input"]["monthly_earned"] * 100) + round(case["input"]["monthly_unearned"] * 100)
            assert monthly["gross_cents"] == gross
            assert monthly["net_cents"] == gross - result["total"]
    assert len(results) == 2232
    assert whole_cent_count == sum(
        (case["input"]["monthly_earned"] * 100).is_integer()
        and (case["input"]["monthly_unearned"] * 100).is_integer()
        for case in ORACLE["compute_cases"])
    for case in ORACLE["error_cases"]:
        actual = engine_page.evaluate("""({i, rules}) => {
            try {Tax2Engine.computeAnnual(i.monthly_earned, i.monthly_unearned,
                i.filing_status, i.year, i.states, rules); return null;}
            catch(error) {return error.message;}
        }""", {"i": case["input"], "rules": payloads[case["root"]]})
        assert actual == case["expected"]["detail"]


def test_rounding_vectors_and_exact_cents_format(engine_page):
    actual = engine_page.evaluate("""() => {
        const e = Tax2Engine;
        return {money: [3.121,3.13,1.1,.07,.001,1e-9,0,1234.565].map(e.ceilCents),
            rates: [[100/3,10],[100/3,100],[24.5,100],[24,100],[.07*100,100]].map(([x,s]) => e.ceilScaled(x,s)),
            invalid: [-1,NaN,Infinity,-Infinity].map(x => {
                try {e.ceilCents(x);return null;} catch(error) {return error.message;}}),
            format: [0,7,313,-313,123456789,Number.MAX_SAFE_INTEGER].map(x => e.formatCents(x)),
            grouped: e.formatCents(-123456789, {grouping:true})};
    }""")
    assert actual == {"money": [313,313,110,7,1,0,0,123457],
                      "rates": [334,3334,2450,2400,700],
                      "invalid": ["Invalid rounding input"] * 4,
                      "format": ["0.00","0.07","3.13","-3.13","1234567.89","90071992547409.91"],
                      "grouped": "-1,234,567.89"}


def test_generic_components_credits_order_and_metadata(engine_page):
    actual = engine_page.evaluate("""() => {
        const e = Tax2Engine;
        const component = (basis, rate, enabled=true) => ({enabled, applies_to:basis,
            standard_deduction:{single:0}, brackets:{single:[{up_to:null,rate}]}});
        const rule = {filing_statuses:['single'], components:[component(['earned'],.1),
            component(['unearned'],.2),component(['earned','unearned'],10,false)], credits:[]};
        const tax = credits => e.computeTax({earned_income:1000,unearned_income:500},
            {...rule,credits}, 'single');
        const results = [tax([]), tax([{amount:20}]), tax([{amount_per_child:30}]),
            tax([{amount:20,amount_per_child:30}]), tax([{amount:-20}]),
            tax([{amount:100,phaseout:{start_income:1000,rate_per_dollar:.1}}]),
            tax([{amount:100,phaseout:{start_income:2000,rate_per_dollar:.1}}]),
            tax([{amount:100,refundable_cap:25}]),
            tax([{amount:20},{amount:30}]),tax([{amount:300}]),
            tax([{amount:100,phaseout:{start_income:0,rate_per_dollar:1}}]),
            tax([{amount:null,amount_per_child:null,refundable_cap:null}]),
            tax([{amount:100,phaseout:{start_income:1000,rate_per_dollar:.1},refundable_cap:75}]),
            tax([{amount:100,phaseout:{start_income:1000,rate_per_dollar:.1},refundable_cap:25}])];
        const credited = {...rule, display_name:'Selected Synthetic',
            credits:[{amount:100, phaseout:{start_income:1000,rate_per_dollar:.1}}]};
        const payload = {schema:1, federal:{2026:rule}, states:[
            {code:'XB',display_name:'Discovery Synthetic',years:[2026],rules:{2026:credited}},
            {code:'XA',display_name:'Fallback Synthetic',years:[2026],rules:{2026:rule}},
            {code:'XC',years:[2026],rules:{2026:rule}}]};
        const annual = e.computeAnnual(1000/12,500/12,'single',2026,
            [{code:'XB',allocation_pct:50},{code:'XA',allocation_pct:0},{code:'XC',allocation_pct:100}], payload);
        const monthly = e.computeMonthly({earnedCents:10000,unearnedCents:5000,
            filingStatus:'single',year:2026,states:[{code:'XC',allocation_pct:100}]},payload);
        const zero = e.computeMonthly({earnedCents:0,unearnedCents:0,
            filingStatus:'single',year:2026,states:[{code:'XC',allocation_pct:100}]},payload);
        return {results,annual,monthly,zeroRate:zero.effective_rate,
            bracket:e.applyBrackets(250,[{up_to:100,rate:.1},{up_to:null,rate:.2}])};
    }""")
    assert actual["results"] == [200,180,170,170,200,150,100,175,150,0,200,200,150,175]
    assert actual["annual"] == {"federal_annual": 200, "states": [
        {"code": "XB", "display_name": "Selected Synthetic", "allocation_pct": 50, "annual": 0},
        {"code": "XA", "display_name": "Fallback Synthetic", "allocation_pct": 0, "annual": 0},
        {"code": "XC", "display_name": "XC", "allocation_pct": 100, "annual": 200}]}
    assert actual["monthly"] == {"federal_cents": 2000, "states": [
        {"code": "XC", "display_name": "XC", "allocation_pct": 100, "state_cents": 2000}],
        "total_monthly_cents": 4000, "gross_cents": 15000, "net_cents": 11000, "effective_rate": 26.67}
    assert actual["zeroRate"] == 0
    assert actual["bracket"] == 40


def test_engine_rejects_invalid_inputs_and_missing_status_data(engine_page):
    actual = engine_page.evaluate("""() => {
        const e = Tax2Engine;
        const rule = {filing_statuses:['single'], components:[{enabled:true, applies_to:['earned'],
            standard_deduction:{single:0},brackets:{single:[{up_to:null,rate:.1}]}}],credits:[]};
        const rules = {schema:1,federal:{2026:rule},states:[{code:'XX',years:[2026],rules:{2026:rule}},
            {code:'XE',years:[],rules:{}}]};
        const input = {earnedCents:10000,unearnedCents:0,filingStatus:'single',year:2026,
            states:[{code:'XX',allocation_pct:100}]};
        const calls = [-1,NaN,Infinity,-Infinity,.5,Number.MAX_SAFE_INTEGER+1,'100'].map(
            x => () => e.computeMonthly({...input,earnedCents:x},rules));
        calls.push(...[-1,NaN,Infinity,-Infinity,'100'].flatMap(x => [
            () => e.computeAnnual(x,0,'single',2026,input.states,rules),
            () => e.computeAnnual(0,x,'single',2026,input.states,rules),
            () => e.computeMonthly({...input,unearnedCents:x},rules)]));
        calls.push(...[-1,101,NaN,Infinity,'100'].map(x => () => e.computeMonthly(
            {...input,states:[{code:'XX',allocation_pct:x}]},rules)));
        calls.push(() => e.computeMonthly({...input,unearnedCents:Number.MAX_SAFE_INTEGER},rules),
            () => e.computeMonthly({...input,filingStatus:'other'},rules),
            () => e.computeMonthly({...input,year:2025},rules),
            () => e.computeMonthly({...input,year:2026.5},rules),
            () => e.computeMonthly({...input,states:[]},rules),
            () => e.computeMonthly({...input,states:[{code:'UNKNOWN',allocation_pct:100}]},rules),
            () => e.computeTax({earned_income:0,unearned_income:0}, {...rule,components:[
                {...rule.components[0],standard_deduction:{}}]},'single'),
            () => e.computeTax({earned_income:0,unearned_income:0}, {...rule,components:[
                {...rule.components[0],brackets:{}}]},'single'),
            () => e.computeTax({earned_income:-1,unearned_income:0},rule,'single'),
            () => e.formatCents(.1));
        const errors = calls.map(call => {try {call();return null;}catch(error){return error.message;}});
        let emptyYear;
        try {e.computeAnnual(0,0,'single',2026,[{code:'XE',allocation_pct:100}],rules);}
        catch(error){emptyYear=error.message;}
        return {errors,emptyYear};
    }""")
    assert actual["errors"] == [
        "Invalid earned income",
        "Invalid earned cents",
        "Invalid earned cents",
        "Invalid earned cents",
        "Invalid earned cents",
        "Invalid earned cents",
        "Invalid earned cents",
        "Invalid earned income",
        "Invalid unearned income",
        "Invalid unearned income",
        "Invalid earned income",
        "Invalid unearned income",
        "Invalid unearned cents",
        "Invalid earned income",
        "Invalid unearned income",
        "Invalid unearned cents",
        "Invalid earned income",
        "Invalid unearned income",
        "Invalid unearned cents",
        "Invalid earned income",
        "Invalid unearned income",
        "Invalid unearned cents",
        "Invalid state allocation",
        "Invalid state allocation",
        "Invalid state allocation",
        "Invalid state allocation",
        "Invalid state allocation",
        "Invalid gross cents",
        "Unsupported filing status: other",
        "Federal has no rules for 2025",
        "Invalid year",
        "Select at least one state",
        "Unknown state: UNKNOWN",
        "Missing component data for filing status: single",
        "Missing component data for filing status: single",
        "Invalid earned income",
        "Invalid cents",
    ]
    assert actual["emptyYear"] == "State XE has no rules for 2026. Available years: none"


def test_negative_deductions_high_rates_and_negative_net_are_preserved(engine_page):
    result = engine_page.evaluate("""() => {
        const rule = {filing_statuses:['single'],components:[{enabled:true,applies_to:['earned'],
            standard_deduction:{single:-100},brackets:{single:[{up_to:null,rate:2}]}}],credits:[]};
        const rules = {schema:1,federal:{2026:rule},states:[{code:'XX',years:[2026],rules:{2026:rule}}]};
        return Tax2Engine.computeMonthly({earnedCents:10000,unearnedCents:0,filingStatus:'single',
            year:2026,states:[{code:'XX',allocation_pct:100}]},rules);
    }""")
    assert result == {"federal_cents": 21667, "states": [
        {"code": "XX", "display_name": "XX", "allocation_pct": 100, "state_cents": 21667}],
        "total_monthly_cents": 43334, "gross_cents": 10000, "net_cents": -33334, "effective_rate": 433.34}
