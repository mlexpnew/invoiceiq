"""Duplicate invoices: the most common way ITC gets claimed twice.

Exact duplicate: same supplier and same invoice number after normalising formatting
("INV/007" and "inv-7" are the same document). Possible duplicate: same supplier, same
total and same date under a different number, which usually means a re-issued copy.
"""

from __future__ import annotations

import re

from .models import Invoice, Issue, Severity


def normalize_invoice_no(no: str) -> str:
    """Uppercase, strip leading zeros in each number, drop separators."""
    s = re.sub(r"\d+", lambda m: str(int(m.group())), no.upper())
    return re.sub(r"[^A-Z0-9]", "", s)


def find_duplicates(invoices: list[Invoice]) -> list[Issue]:
    issues: list[Issue] = []
    seen_no: dict[tuple[str, str], Invoice] = {}
    seen_amount: dict[tuple, Invoice] = {}
    for inv in invoices:
        key = (inv.supplier_gstin, normalize_invoice_no(inv.invoice_no))
        if inv.invoice_no and key in seen_no:
            first = seen_no[key]
            issues.append(
                Issue(
                    code="DUPLICATE",
                    severity=Severity.ERROR,
                    message=f"same supplier and invoice number as {first.source}",
                    source=inv.source,
                    invoice_no=inv.invoice_no,
                )
            )
            continue
        seen_no[key] = inv

        amount_key = (inv.supplier_gstin, inv.invoice_date, round(inv.total, 0))
        if inv.total > 0 and inv.invoice_date and amount_key in seen_amount:
            first = seen_amount[amount_key]
            issues.append(
                Issue(
                    code="POSSIBLE_DUPLICATE",
                    severity=Severity.WARNING,
                    message=(
                        f"same supplier, date and total as {first.source} "
                        f"({first.invoice_no}) under a different number"
                    ),
                    source=inv.source,
                    invoice_no=inv.invoice_no,
                )
            )
        else:
            seen_amount.setdefault(amount_key, inv)
    return issues
