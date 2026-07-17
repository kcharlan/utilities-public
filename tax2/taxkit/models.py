from __future__ import annotations
from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional, List, Dict

class FilingStatus(str, Enum):
    single = "single"
    married_joint = "married_joint"

class IncomeClass(str, Enum):
    earned = "earned"
    unearned = "unearned"

class Bracket(BaseModel):
    up_to: Optional[float] = Field(None, description="Upper bound (annual taxable). None = no upper bound")
    rate: float

class Phaseout(BaseModel):
    start_income: float
    rate_per_dollar: float

class Credit(BaseModel):
    name: str
    amount: Optional[float] = 0.0
    amount_per_child: Optional[float] = None
    refundable_cap: Optional[float] = None
    phaseout: Optional[Phaseout] = None

class TaxComponent(BaseModel):
    name: str
    label: Optional[str] = None
    enabled: bool = True
    applies_to: List[IncomeClass] = Field(
        default_factory=lambda: [IncomeClass.earned, IncomeClass.unearned]
    )
    standard_deduction: Dict[FilingStatus, float]
    brackets: Dict[FilingStatus, List[Bracket]]

class QIFDefaults(BaseModel):
    state_expense: Optional[str] = None
    state_transfer: Optional[str] = None

class TaxRules(BaseModel):
    year: int
    jurisdiction: str
    display_name: Optional[str] = None
    filing_statuses: List[FilingStatus]
    components: List[TaxComponent]
    credits: List[Credit] = Field(default_factory=list)
    qif: Optional[QIFDefaults] = None

class TaxInput(BaseModel):
    earned_income: float = Field(0.0, ge=0)
    unearned_income: float = Field(0.0, ge=0)
    filing_status: FilingStatus

    @property
    def annual_income(self) -> float:
        return self.earned_income + self.unearned_income
