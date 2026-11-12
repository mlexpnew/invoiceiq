"""End to end: PDFs (+ optional GSTR-2B) in, checked invoices and a reconciliation out."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from .duplicates import find_duplicates
from .extract.pdf import pdf_text
from .extract.rules import extract
from .models import Invoice, Issue, ReconRow, Severity
from .reconcile import Gstr2bEntry, reconcile
from .validate import validate

log = logging.getLogger(__name__)
LLM_THRESHOLD = 0.8


@dataclass
class Result:
    invoices: list[Invoice] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    recon: list[ReconRow] = field(default_factory=list)

    def blocked_sources(self) -> set[str]:
        return {i.source for i in self.issues if i.severity is Severity.ERROR}

    def clean(self) -> list[Invoice]:
        """Invoices safe to post: no errors."""
        blocked = self.blocked_sources()
        return [inv for inv in self.invoices if inv.source not in blocked]


def read_invoice(data: bytes, source: str, company_gstin: str = "", llm=None) -> Invoice:
    text = pdf_text(data)
    if not text.strip():
        inv = Invoice(source=source, extractor="none")
        inv.confidence = 0.0
        return inv
    inv = extract(text, source=source, company_gstin=company_gstin)
    if llm is not None and inv.confidence < LLM_THRESHOLD:
        from .extract.llm import merge

        try:
            inv = merge(inv, llm.fields(text))
        except Exception as exc:  # the LLM is a helper, never a single point of failure
            log.warning("LLM fallback failed for %s: %s", source, exc)
    return inv


def process(
    files: list[tuple[str, bytes]],
    company_gstin: str = "",
    gstr2b: list[Gstr2bEntry] | None = None,
    llm=None,
    today: date | None = None,
) -> Result:
    res = Result()
    for name, data in files:
        inv = read_invoice(data, name, company_gstin, llm)
        res.invoices.append(inv)
        if inv.extractor == "none":
            res.issues.append(
                Issue(code="SCANNED_PDF", severity=Severity.ERROR, source=name,
                      message="no text layer: scanned image, needs OCR or manual entry")
            )  # fmt: skip
            continue
        res.issues += validate(inv, company_gstin=company_gstin, today=today)
    res.issues += find_duplicates([i for i in res.invoices if i.extractor != "none"])
    if gstr2b is not None:
        dup_sources = {i.source for i in res.issues if i.code == "DUPLICATE"}
        books = [i for i in res.invoices if i.source not in dup_sources and i.invoice_no]
        res.recon = reconcile(books, gstr2b)
    return res
