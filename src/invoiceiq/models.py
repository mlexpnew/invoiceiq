"""Typed records shared by extraction, validation, reconciliation and export."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field


class LineItem(BaseModel):
    description: str
    hsn: str = ""
    qty: float = 1.0
    unit_price: float = 0.0
    taxable_value: float = 0.0
    gst_rate: float = 0.0  # percent, e.g. 18.0


class Invoice(BaseModel):
    source: str = ""  # file name, so every row traces back to a document
    supplier_name: str = ""
    supplier_gstin: str = ""
    buyer_name: str = ""
    buyer_gstin: str = ""
    place_of_supply: str = ""  # 2-digit state code
    invoice_no: str = ""
    invoice_date: date | None = None
    items: list[LineItem] = Field(default_factory=list)
    taxable_value: float = 0.0
    cgst: float = 0.0
    sgst: float = 0.0
    igst: float = 0.0
    round_off: float = 0.0
    total: float = 0.0
    extractor: str = "rules"  # rules | llm
    confidence: float = 0.0  # share of required fields found and internally consistent

    @property
    def total_tax(self) -> float:
        return round(self.cgst + self.sgst + self.igst, 2)


class Severity(StrEnum):
    ERROR = "error"  # blocks posting to books / ITC claim
    WARNING = "warning"  # needs a human look


class Issue(BaseModel):
    code: str
    severity: Severity
    message: str
    source: str = ""
    invoice_no: str = ""


class ReconStatus(StrEnum):
    MATCHED = "matched"
    VALUE_MISMATCH = "value_mismatch"  # both sides have it, tax differs
    MISSING_IN_2B = "missing_in_2b"  # in books, supplier has not filed: ITC at risk
    MISSING_IN_BOOKS = "missing_in_books"  # in 2B, not recorded in purchase register
    ITC_UNAVAILABLE = "itc_unavailable"  # in 2B but flagged not eligible


class ReconRow(BaseModel):
    status: ReconStatus
    supplier_gstin: str
    supplier_name: str = ""
    invoice_no: str
    invoice_date: date | None = None
    books_tax: float = 0.0
    gstr2b_tax: float = 0.0
    difference: float = 0.0
    itc_at_risk: float = 0.0
    note: str = ""
