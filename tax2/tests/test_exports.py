"""Browser execution of pure export builders; all data is synthetic or frozen."""
import csv
import io

import pytest

from taxkit.page import build_payload
from tests.test_engine_parity import FIXTURES, ORACLE, engine_page


def payload(root="bundled"):
    return build_payload(FIXTURES / root / "rules", rules_source="custom", built_at="Synthetic build time")


def test_qif_frozen_exact(engine_page):
    actual = engine_page.evaluate("""({cases,rules}) => cases.map(({input:i}) =>
        Tax2Engine.buildQif({federal_cents:i.federal_cents,
            states:i.states.map(s=>({code:s.code,state_cents:s.amount_cents}))},
            {txDate:i.tx_date,payee:i.config.payee,federalExpense:i.config.federal_expense,
             federalTransfer:i.config.federal_transfer},
            Object.fromEntries(i.states.map(s=>[s.code,{expense:s.expense,transfer:s.transfer}])),rules))
    """, {"cases": ORACLE["qif_cases"], "rules": payload()})
    assert actual == [case["expected"] for case in ORACLE["qif_cases"]]


def test_lookup_bundled_rows(engine_page):
    text = engine_page.evaluate("r=>Tax2Engine.buildLookupCsv(2026,'single',r)", payload())
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == ["MonthlyIncome", "Federal monthly tax (total income)",
                       "GA monthly tax (total income)", "PA monthly tax (total income)"]
    assert len(rows) == 10002
    assert rows[1] == ["0.00"] * 4
    assert rows[101] == ["5000.00", "418.34", "203.60", "153.50"]
    assert rows[-1][0] == "500000.00"


def test_schedule_structure(engine_page):
    text = engine_page.evaluate("r=>Tax2Engine.buildRateSchedule(2026,r)", payload())
    for phrase in ["Synthetic build time", "2026", "not tax advice", "Federal", "GA", "PA",
                   "Single", "Married Filing Jointly", "disabled — not included", "3.07%",
                   "Over | But not over | Tax = base + rate × excess over", "interpolation",
                   "underestimate", "500,000", "qualified dividends", "FICA", "allocation"]:
        assert phrase in text
    assert "before dividing" not in text.casefold()


def test_schedule_manual_procedure_applies_credits_before_monthly_rounding(engine_page):
    text = engine_page.evaluate("r=>Tax2Engine.buildRateSchedule(2026,r)", payload("synthetic"))
    procedure = text.split("## Manual procedure\n\n", 1)[1].split(
        "\n\n## Caveats and lookup procedure", 1)[0]
    assert procedure.splitlines() == [
        "1. Multiply monthly income by 12.",
        "2. For a state, multiply earned and unearned income by its allocation first. Federal uses unallocated total income.",
        "3. Use each component's income basis. Subtract its standard deduction, flooring taxable income at 0.",
        "4. Find the bracket and apply its formula.",
        "5. For a jurisdiction with credits, subtract them once from the annual tax of its total-income components, flooring at zero (see Credits).",
        "6. Divide each component's annual tax (or the credited total-income section's) by 12 and round up to the next cent.",
        "7. Add the results.",
    ]
    assert "### Credits" in text
    assert "before dividing" not in text.casefold()


def test_schedule_escapes_every_user_supplied_label_path(engine_page):
    text = engine_page.evaluate("""({r,special})=>{
        r.built_at=special;
        r.federal[2026].components[0].label='A & B ~~x~~ #';
        const state=r.states.find(s=>s.code==='XC');
        state.code=special;
        delete state.rules[2026].components[0].label;
        state.rules[2026].components[0].name=special;
        state.rules[2026].credits[0].name='C #1 ~';
        state.rules[2026].credits.push({...state.rules[2026].credits[0],name:special});
        return Tax2Engine.buildRateSchedule(2026,r);
    }""", {"r": payload("synthetic"), "special": "SYNTHETIC \\ ` * _ [ ] < > | & ~ #\r\nEND"})
    escaped = r"SYNTHETIC \\ \` \* \_ \[ \] \< \> \| \& \~ \# END"
    assert f"Build time: {escaped}" in text.splitlines()
    assert f"## {escaped}" in text.splitlines()
    assert f"#### {escaped}" in text.splitlines()
    assert r"#### A \& B \~\~x\~\~ \#" in text.splitlines()
    assert r"- C \#1 \~: amount" in text
    assert f"- {escaped}: amount" in text
    assert "~~" not in text
    assert not any(line.endswith(" #") for line in text.splitlines())


def test_engine_digit_grouping_regex_has_one_shared_definition():
    engine = (FIXTURES.parents[2] / "web" / "engine.js").read_text()
    assert engine.count(r"/\B(?=(\d{3})+(?!\d))/g") == 1


def test_qif_defaults_dates_order_and_validation(engine_page):
    actual = engine_page.evaluate("""r => {
        const e=Tax2Engine;
        r.config.qif_overrides={XC:{state_expense:'Synthetic override',state_transfer:''}};
        const result={federal_cents:0,states:[{code:'XU',state_cents:7},{code:'XC',state_cents:313}]};
        const qif=e.buildQif(result,{txDate:'2000-02-29',payee:'Synthetic payee'},
            {XU:{expense:'',transfer:'[Synthetic edited]'},XC:{expense:'',transfer:''}},r);
        const errors=['','2026-02-29','1900-02-29','2026-04-31','2026-00-01','2026-13-01',
            '2026-01-00','0000-01-01','2026-1-01','2026-01-01T00:00:00Z'].map(date=>{
            try{e.parseQifDate(date);return null;}catch(x){return x.message;}});
        const centsErrors=[-1,.1,NaN,Infinity,Number.MAX_SAFE_INTEGER+1,'100'].map(cents=>{
            try{e.buildQif({...result,federal_cents:cents},{txDate:'2026-01-01'},{},r);return null;}
            catch(x){return x.message;}});
        return {qif,errors,centsErrors,date:e.parseQifDate('2000-02-29'),
            defaults:e.resolveStateQifDefaults('XC',r),unknown:e.resolveStateQifDefaults('XF',r)};
    }""", payload("synthetic"))
    assert actual["date"] == {"year": 2000, "month": 2, "day": 29}
    assert all(actual["errors"]) and all(actual["centsErrors"])
    assert actual["defaults"] == {"expense": "Synthetic override", "transfer": "[Synthetic Credit Transfer]"}
    assert actual["unknown"] == {"expense": "Tax:State Income Tax Estimated Paid", "transfer": "[XF State Income Taxes]"}
    qif = actual["qif"]
    assert qif.count("!Type:Bank") == 1 and not qif.endswith("\n")
    assert "D02/29/00\nT-0.00" in qif and "D02/29/00\nT0.00" in qif
    assert "Estimated XU State taxes - 02/29/2000" in qif
    assert qif.index("Estimated XU") < qif.index("Estimated XC")
    assert "LSynthetic:Unearned Tax" in qif and "L[Synthetic edited]" in qif
    assert "LSynthetic override" in qif and "L[Synthetic Credit Transfer]" in qif


@pytest.mark.parametrize("status", ["single", "married_joint"])
def test_synthetic_lookup_shared_engine_and_hand_values(engine_page, status):
    actual = engine_page.evaluate("""({r,status}) => {
        const e=Tax2Engine,before=JSON.stringify(r);
        const rows=e.buildLookupCsv(2026,status,r).split('\\n').map(line=>line.split(','));
        const samples=[0,1,2,40,50,60,100,200,10000].map(index=>{
            const income=index*50*12;
            const expected=[];
            for(const rule of [r.federal[2026],...r.states.map(s=>s.rules[2026])]) {
                for(const basis of [0,1,2]) {
                    const cs=rule.components.filter(c=>c.enabled &&
                        (c.applies_to.length===2 ? 0 : c.applies_to[0]==='earned' ? 1:2)===basis);
                    if(!cs.length)continue;
                    expected.push(e.formatCents(e.ceilCents(e.computeTax(
                        {earned_income:basis===1?income:0,unearned_income:basis===1?0:income},
                        {...rule,components:cs,credits:basis===0?rule.credits:[]},status)/12)));
                }
            }
            return {cells:rows[index+1].slice(1),expected};
        });
        return {header:rows[0],count:rows.length,samples,row:rows[101],unchanged:before===JSON.stringify(r)};
    }""", {"r": payload("synthetic"), "status": status})
    assert actual["header"] == ["MonthlyIncome", "Federal monthly tax (total income)",
                               "PA monthly tax (total income)", "PA monthly tax (earned income only)",
                               "XC monthly tax (total income)", "XU monthly tax (unearned income only)"]
    assert actual["count"] == 10002 and actual["unchanged"]
    for sample in actual["samples"]:
        assert sample["cells"] == sample["expected"]
    # PA flat 3.07%, local earned 1%; XC credit exhausted at 40,000 annual.
    assert actual["row"][2:5] == ["153.50", "50.00", "500.00"]
    assert actual["row"][5] == ("98.34" if status == "single" else "96.67")
    assert actual["samples"][0]["cells"] == ["0.00"] * 5
    assert [sample["cells"][3] for sample in actual["samples"][:6]] == [
        "0.00", "0.00", "0.00", "158.34", "208.34", "283.34"]


def test_missing_year_exports_and_calculator_are_independent(engine_page):
    actual = engine_page.evaluate("""r => {
        const e=Tax2Engine;
        r.states=[{code:'XF',years:[2025],rules:{2025:r.federal[2025]}}];
        const before=JSON.stringify(r);
        let error;try{e.computeAnnual(100,0,'single',2026,[{code:'XF',allocation_pct:100}],r);}
        catch(x){error=x.message;}
        const schedule=e.buildRateSchedule(2026,r);
        const csv=e.buildLookupCsv(2026,'single',r).split('\\n');
        return {schedule,header:csv[0],count:csv.length,error,unchanged:before===JSON.stringify(r)};
    }""", payload())
    assert actual["header"] == "MonthlyIncome,Federal monthly tax (total income)"
    assert actual["count"] == 10002 and actual["unchanged"]
    assert "## XF" not in actual["schedule"]
    assert "### Single" in actual["schedule"] and "### Married Filing Jointly" in actual["schedule"]
    assert actual["error"] == "State XF has no rules for 2026. Available years: [2025]"
    partial = engine_page.evaluate("r=>Tax2Engine.buildLookupCsv(2025,'single',r).split('\\n')[0]", payload())
    assert partial == "MonthlyIncome,Federal monthly tax (total income),GA monthly tax (total income)"


def test_exact_schedule_decimals_bases_and_credit_instructions(engine_page):
    text = engine_page.evaluate("""r => {
        const c={name:'Synthetic component',enabled:true,applies_to:['earned','unearned'],
          standard_deduction:{single:1234.56789,married_joint:1e-7},
          brackets:{single:[{up_to:1000.12345,rate:.0307},{up_to:2000.12345,rate:1e-7},
                  {up_to:2e21,rate:0},{up_to:null,rate:.4}],
              married_joint:[{up_to:null,rate:1e21}]}};
        r.federal[2026]={filing_statuses:['single','married_joint'],components:[c],credits:[]};
        return Tax2Engine.buildRateSchedule(2026,r);
    }""", payload("synthetic"))
    for phrase in ["1,234.56789", "0.0000001", "1,000.12345", "2,000,000,000,000,000,000,000",
                   "3.07%", "0.00001%", "30.71 + 0.00001%", "100000000000000000000000%",
                   "total income", "earned income only",
                   "unearned income only", "Synthetic unearned component", "Synthetic total-income component",
                   "refundable cap 500", "phaseout starts at total annual income 20,000", "reduction 0.05",
                   "Multiply monthly income by 12", "Divide each component's annual tax", "Add the results",
                   "floor", "approximate", "once", "next row up", "nondecreasing", "$25 ×",
                   "cap point", "bracket boundary", "about 2 cents", "self-employment", "NIIT"]:
        assert phrase in text
    assert "3.0700000000000003%" not in text


def test_group_rounding_credit_omission_cap_and_threshold_continuity(engine_page):
    actual = engine_page.evaluate("""r=>{
        const e=Tax2Engine;
        const component=(basis,rate)=>({name:'Synthetic',enabled:true,applies_to:basis,
            standard_deduction:{single:0,married_joint:0},
            brackets:{single:[{up_to:null,rate}],married_joint:[{up_to:null,rate}]}});
        const a=component(['earned'],.000001),b=component(['earned'],.000001);
        const rule={filing_statuses:['single','married_joint'],components:[a,b],
            credits:[{amount:100,refundable_cap:25,phaseout:{start_income:0,rate_per_dollar:.05}}]};
        r.states=[{code:'XO',years:[2026],rules:{2026:rule}}];
        const before=JSON.stringify(r);
        const rows=e.buildLookupCsv(2026,'single',r).split('\\n');
        const schedule=e.buildRateSchedule(2026,r);
        const bounds=[0,100].map(start=>{
            const view={...rule,components:[component(['earned','unearned'],.1)],
                credits:[{amount:20,refundable_cap:10,phaseout:{start_income:start,rate_per_dollar:.05}}]};
            return [start-1e-7,start,start+1e-7].filter(x=>x>=0).map(x=>
                e.computeTax({earned_income:x,unearned_income:0},view,'single'));
        });
        const conservative=[0,50,100,1000].map(m=>{
            const lookup=Number(rows[m/50+1].split(',')[2]);
            const calculated=e.ceilCents(e.computeTax({earned_income:m*12,unearned_income:0},rule,'single')/12)/100;
            return lookup>=calculated;
        });
        return {first:rows[2],schedule,conservative,bounds,unchanged:before===JSON.stringify(r)};
    }""", payload("synthetic"))
    assert actual["first"].endswith(",0.01")  # Sum two sub-cent components before rounding once.
    assert "Credits omitted: no enabled total-income component" in actual["schedule"]
    assert all(actual["conservative"]) and actual["unchanged"]
    for values in actual["bounds"]:
        assert values == sorted(values)
        assert max(values) - min(values) < 1e-7


def test_export_errors_and_alphabetical_component_groups(engine_page):
    actual = engine_page.evaluate("""r=>{
        const e=Tax2Engine;
        r.states.reverse();
        const csv=e.buildLookupCsv(2026,'single',r);
        const schedule=e.buildRateSchedule(2026,r);
        const errors=[()=>e.buildLookupCsv(2024,'single',r),()=>e.buildLookupCsv(2026,'other',r),
            ()=>e.buildRateSchedule(2024,r),()=>e.buildQif({federal_cents:0,
                states:[{code:'PA',state_cents:-1}]},{txDate:'2026-01-01'},{},r)].map(call=>{
                    try{call();return null;}catch(x){return x.message;}});
        return {header:csv.split('\\n')[0],schedule,errors};
    }""", payload("synthetic"))
    assert actual["header"].index("PA monthly") < actual["header"].index("XC monthly") < actual["header"].index("XU monthly")
    assert actual["schedule"].index("## Federal") < actual["schedule"].index("## PA") < actual["schedule"].index("## XC") < actual["schedule"].index("## XU")
    assert all(actual["errors"])


def test_supported_bracket_threshold_continuity_and_falling_bend(engine_page):
    actual = engine_page.evaluate("""()=>{
        const e=Tax2Engine;
        return [0,100].map(cap=>{
            const brackets=[{up_to:cap,rate:.2},{up_to:null,rate:.1}];
            return [Math.max(0,cap-1e-7),cap,cap+1e-7].map(x=>e.applyBrackets(x,brackets));
        });
    }""")
    assert actual[0] == [0, 0, 1e-8]
    assert actual[1][1] == 20
    assert actual[1] == sorted(actual[1])
    assert max(actual[1]) - min(actual[1]) < 1e-7


def test_qif_latest_inventory_defaults_and_generic_single_state(engine_page):
    actual = engine_page.evaluate("""r=>{
        const e=Tax2Engine;
        const ga=r.states.find(s=>s.code==='GA');
        ga.qif={state_expense:'Synthetic latest category',state_transfer:'[Synthetic latest transfer]'};
        ga.rules[2025].qif={state_expense:'Synthetic earlier category',state_transfer:'[Synthetic earlier transfer]'};
        return e.buildQif({federal_cents:1,states:[{code:'GA',state_cents:0}]},
            {txDate:'2025-12-31'}, {GA:{expense:'',transfer:''}},r);
    }""", payload())
    assert "Estimated State taxes - 12/31/2025" in actual
    assert "Estimated GA State taxes" not in actual
    assert "LSynthetic latest category" in actual and "L[Synthetic latest transfer]" in actual
    assert "earlier" not in actual


def test_csv_headers_escape_custom_state_codes(engine_page):
    text = engine_page.evaluate("""r=>{
        const rule=r.states[0].rules[2026];
        r.states=['X,SYNTHETIC','X"SYNTHETIC','X\\rSYNTHETIC','X\\nSYNTHETIC'].map(code=>
            ({code,years:[2026],rules:{2026:rule}}));
        return Tax2Engine.buildLookupCsv(2026,'single',r);
    }""", payload())
    rows = list(csv.reader(io.StringIO(text, newline="")))
    codes = sorted(['X,SYNTHETIC', 'X"SYNTHETIC', 'X\rSYNTHETIC', 'X\nSYNTHETIC'])
    assert rows[0] == ["MonthlyIncome", "Federal monthly tax (total income)",
                       *(f"{code} monthly tax (total income)" for code in codes)]
    assert len(rows) == 10002
    assert all(len(row) == len(rows[0]) for row in rows)
    assert rows[101] == ["5000.00", "418.34", *("203.60" for _ in codes)]


def test_schedule_custom_state_code_stays_one_escaped_heading(engine_page):
    text = engine_page.evaluate("""r=>{
        const rule=r.states[0].rules[2026];
        r.states=[{code:'X\\n# SYNTHETIC *[code]|',years:[2026],rules:{2026:rule}}];
        return Tax2Engine.buildRateSchedule(2026,r);
    }""", payload())
    headings = [line for line in text.splitlines() if line.startswith("## ")]
    assert headings == ["## Manual procedure", "## Caveats and lookup procedure", "## Federal",
                        r"## X \# SYNTHETIC \*\[code\]\|"]
    assert "\n# SYNTHETIC" not in text
