"""Compliance checks on one purchase invoice.

Every check returns Issues instead of raising, so a reviewer sees all problems at once.
Errors block posting and ITC claims; warnings need a human look.
"""

from __future__ import annotations

import re
from datetime import date

from . import gstin as G
from .models import Invoice, Issue, Severity
from .rates import check_rate

TOLERANCE = 1.0  # rupees: invoices round each tax line, so allow small drift
INVOICE_NO_RE = re.compile(r"^[A-Za-z0-9/-]{1,16}$")  # CGST Rule 46: max 16 chars, / and -


def itc_deadline(invoice_date: date) -> date:
    """Last date to claim ITC, Section 16(4): 30 November after the financial year ends."""
    fy_end_year = invoice_date.year + 1 if invoice_date.month >= 4 else invoice_date.year
    return date(fy_end_year, 11, 30)


def validate(inv: Invoice, company_gstin: str = "", today: date | None = None) -> list[Issue]:
    today = today or date.today()
    issues: list[Issue] = []

    def add(code: str, sev: Severity, msg: str) -> None:
        issues.append(
            Issue(
                code=code, severity=sev, message=msg, source=inv.source, invoice_no=inv.invoice_no
            )
        )

    E, W = Severity.ERROR, Severity.WARNING

    # Required fields
    for field in ("supplier_gstin", "invoice_no", "invoice_date"):
        if not getattr(inv, field):
            add("MISSING_FIELD", E, f"{field.replace('_', ' ')} not found")
    if inv.total <= 0:
        add("MISSING_FIELD", E, "invoice total not found")

    # Identity
    for who, value in (("supplier", inv.supplier_gstin), ("buyer", inv.buyer_gstin)):
        if value:
            for p in G.problems(value):
                add("GSTIN_INVALID", E, f"{who} GSTIN {value}: {p}")
    if inv.supplier_gstin and inv.supplier_gstin == inv.buyer_gstin:
        add("SELF_INVOICE", E, "supplier and buyer GSTIN are the same")
    if company_gstin and inv.buyer_gstin and inv.buyer_gstin != company_gstin:
        add(
            "BUYER_MISMATCH",
            E,
            f"billed to {inv.buyer_gstin}, not your GSTIN {company_gstin}: ITC not claimable",
        )
    if inv.invoice_no and not INVOICE_NO_RE.match(inv.invoice_no):
        add("INVOICE_NO_FORMAT", W, f"'{inv.invoice_no}' breaks Rule 46 (max 16, A-Z 0-9 / -)")

    # Dates
    if inv.invoice_date:
        if inv.invoice_date > today:
            add("DATE_FUTURE", E, f"dated {inv.invoice_date}, which is in the future")
        deadline = itc_deadline(inv.invoice_date)
        days_left = (deadline - today).days
        if days_left < 0:
            add("ITC_LAPSED", E, f"ITC window closed on {deadline} (Section 16(4))")
        elif days_left <= 30:
            add("ITC_DEADLINE", W, f"ITC must be claimed by {deadline}: {days_left} days left")

    # Rates and line math
    for i, it in enumerate(inv.items, start=1):
        verdict = check_rate(it.gst_rate, inv.invoice_date)
        if verdict == "invalid":
            add("RATE_INVALID", E, f"line {i}: {it.gst_rate:g}% is not a GST rate")
        elif verdict == "retired":
            add("RATE_RETIRED", W, f"line {i}: {it.gst_rate:g}% slab was folded in GST 2.0")
        if it.qty and it.unit_price and abs(it.qty * it.unit_price - it.taxable_value) > TOLERANCE:
            add(
                "LINE_MATH",
                E,
                f"line {i}: {it.qty:g} x {it.unit_price:,.2f} = "
                f"{it.qty * it.unit_price:,.2f}, invoice says {it.taxable_value:,.2f}",
            )

    # Tax type: same state -> CGST + SGST, different state -> IGST
    supplier_state = G.state_code(inv.supplier_gstin)
    pos = inv.place_of_supply or G.state_code(inv.buyer_gstin)
    if supplier_state and pos:
        intra = supplier_state == pos
        if intra and inv.igst > 0:
            add("TAX_TYPE", E, "intra-state supply charged IGST; should be CGST + SGST")
        if not intra and (inv.cgst > 0 or inv.sgst > 0):
            add("TAX_TYPE", E, "inter-state supply charged CGST/SGST; should be IGST")
    if abs(inv.cgst - inv.sgst) > TOLERANCE:
        add("CGST_SGST_SPLIT", E, f"CGST {inv.cgst:,.2f} and SGST {inv.sgst:,.2f} must be equal")

    # Totals
    if inv.items:
        items_taxable = round(sum(it.taxable_value for it in inv.items), 2)
        if abs(items_taxable - inv.taxable_value) > TOLERANCE:
            add(
                "TAXABLE_MATH",
                E,
                f"line items add to {items_taxable:,.2f}, taxable value says "
                f"{inv.taxable_value:,.2f}",
            )
        expected_tax = round(sum(it.taxable_value * it.gst_rate / 100 for it in inv.items), 2)
        if abs(expected_tax - inv.total_tax) > TOLERANCE:
            add(
                "TAX_MATH",
                E,
                f"tax should be {expected_tax:,.2f} from line rates, invoice charges "
                f"{inv.total_tax:,.2f}",
            )
    expected_total = round(inv.taxable_value + inv.total_tax + inv.round_off, 2)
    if inv.total and abs(expected_total - inv.total) > TOLERANCE:
        add(
            "TOTAL_MATH",
            E,
            f"taxable + tax + round off = {expected_total:,.2f}, total says {inv.total:,.2f}",
        )
    return issues
