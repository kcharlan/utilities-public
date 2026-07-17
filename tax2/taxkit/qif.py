from __future__ import annotations
from dataclasses import dataclass
from datetime import date

@dataclass
class QIFConfig:
    payee: str = "Estimated Taxes Withholding"
    federal_expense: str = "Tax:Federal Income Tax Estimated Paid"
    federal_transfer: str = "[Federal Income Taxes]"
    state_expense: str = "Tax:State Income Tax Estimated Paid"
    state_transfer: str = "[GA State Income Taxes]"

@dataclass
class StateQIFItem:
    code: str
    amount: float
    expense: str
    transfer: str
    label: str | None = None

def _fmt_date(d: date) -> str:
    return d.strftime("%m/%d/%y")

def _memo(d: date, label: str) -> str:
    return f"{label} - {d.strftime('%m/%d/%Y')}"

def _transaction_lines(tx_date: date, amount: float, payee: str, memo: str, account: str) -> list[str]:
    return [
        f"D{_fmt_date(tx_date)}",
        f"T{amount:.2f}",
        f"P{payee}",
        f"M{memo}",
        f"L{account}",
        "^",
    ]

def build_qif_entries(tx_date: date, federal_tax: float, states, cfg: QIFConfig | None = None) -> str:
    cfg = cfg or QIFConfig()
    if isinstance(states, (int, float)):
        states = [
            StateQIFItem(
                code="GA",
                amount=float(states),
                expense=cfg.state_expense,
                transfer=cfg.state_transfer,
            )
        ]

    lines = ["!Type:Bank"]
    federal_memo = _memo(tx_date, 'Estimated Federal taxes')
    lines += _transaction_lines(
        tx_date, -abs(federal_tax), cfg.payee, federal_memo, cfg.federal_expense
    )
    lines += _transaction_lines(
        tx_date, abs(federal_tax), cfg.payee, federal_memo, cfg.federal_transfer
    )

    include_codes = len(states) >= 2
    for state in states:
        state_label = f"Estimated {state.code} State taxes" if include_codes else "Estimated State taxes"
        state_memo = _memo(tx_date, state_label)
        lines += _transaction_lines(
            tx_date, -abs(state.amount), cfg.payee, state_memo, state.expense
        )
        lines += _transaction_lines(
            tx_date, abs(state.amount), cfg.payee, state_memo, state.transfer
        )
    return "\n".join(lines)
