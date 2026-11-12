"""Reconcile the purchase register against GSTR-2B.

GSTR-2B is what suppliers actually reported to the GST portal. ITC is claimable only for
invoices that appear there, so every invoice in the books but missing from 2B is tax
credit at risk, and the supplier needs a follow-up before the return is filed.
"""

from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from datetime import date, datetime

from .duplicates import normalize_invoice_no
from .models import Invoice, ReconRow, ReconStatus

TAX_TOLERANCE = 1.0


class Gstr2bEntry(dict):
    """gstin, name, invoice_no, invoice_date, taxable, tax, itc_available."""


def _parse_date(s: str) -> date | None:
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


def load_gstr2b(raw: bytes | str, filename: str = "") -> list[Gstr2bEntry]:
    """Read the portal's GSTR-2B JSON, or a flat CSV export of it."""
    text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw
    if filename.lower().endswith(".csv") or not text.lstrip().startswith("{"):
        return _from_csv(text)
    data = json.loads(text)
    b2b = (data.get("data") or data).get("docdata", {}).get("b2b", [])
    out = []
    for sup in b2b:
        for inv in sup.get("inv", []):
            items = inv.get("items") or []
            taxable = sum(float(i.get("txval", 0)) for i in items)
            tax = sum(float(i.get(k, 0)) for i in items for k in ("igst", "cgst", "sgst"))
            out.append(
                Gstr2bEntry(
                    gstin=sup.get("ctin", "").upper(),
                    name=sup.get("trdnm", ""),
                    invoice_no=str(inv.get("inum", "")),
                    invoice_date=_parse_date(inv.get("dt", "")),
                    taxable=round(taxable, 2),
                    tax=round(tax, 2),
                    itc_available=str(inv.get("itcavl", "Y")).upper() != "N",
                )
            )
    return out


def _from_csv(text: str) -> list[Gstr2bEntry]:
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        r = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        tax = sum(float(r.get(k) or 0) for k in ("igst", "cgst", "sgst"))
        out.append(
            Gstr2bEntry(
                gstin=r.get("gstin", "").upper(),
                name=r.get("supplier_name", ""),
                invoice_no=r.get("invoice_no", ""),
                invoice_date=_parse_date(r.get("invoice_date", "")),
                taxable=float(r.get("taxable_value") or 0),
                tax=round(tax, 2),
                itc_available=r.get("itc_available", "Y").upper() != "N",
            )
        )
    return out


def reconcile(books: list[Invoice], gstr2b: list[Gstr2bEntry]) -> list[ReconRow]:
    portal = {(e["gstin"], normalize_invoice_no(e["invoice_no"])): e for e in gstr2b}
    rows: list[ReconRow] = []
    matched_keys = set()
    for inv in books:
        key = (inv.supplier_gstin, normalize_invoice_no(inv.invoice_no))
        e = portal.get(key)
        base = dict(
            supplier_gstin=inv.supplier_gstin,
            supplier_name=inv.supplier_name,
            invoice_no=inv.invoice_no,
            invoice_date=inv.invoice_date,
            books_tax=inv.total_tax,
        )
        if e is None:
            rows.append(
                ReconRow(
                    status=ReconStatus.MISSING_IN_2B,
                    itc_at_risk=inv.total_tax,
                    note="supplier has not reported this invoice: ask them to file GSTR-1",
                    **base,
                )
            )
            continue
        matched_keys.add(key)
        diff = round(inv.total_tax - e["tax"], 2)
        if not e["itc_available"]:
            status, risk, note = (
                ReconStatus.ITC_UNAVAILABLE,
                inv.total_tax,
                "reported, but marked ITC not available in 2B",
            )
        elif abs(diff) > TAX_TOLERANCE:
            status, risk = ReconStatus.VALUE_MISMATCH, max(diff, 0.0)
            note = f"books {inv.total_tax:,.2f} vs portal {e['tax']:,.2f}: confirm with supplier"
        else:
            status, risk, note = ReconStatus.MATCHED, 0.0, ""
        portal_date = e["invoice_date"]
        if status is ReconStatus.MATCHED and portal_date and portal_date != inv.invoice_date:
            note = f"date differs: portal shows {e['invoice_date']}"
        rows.append(
            ReconRow(
                status=status, gstr2b_tax=e["tax"], difference=diff, itc_at_risk=risk,
                note=note, **base,
            )
        )  # fmt: skip
    for key, e in portal.items():
        if key not in matched_keys:
            rows.append(
                ReconRow(
                    status=ReconStatus.MISSING_IN_BOOKS,
                    supplier_gstin=e["gstin"],
                    supplier_name=e["name"],
                    invoice_no=e["invoice_no"],
                    invoice_date=e["invoice_date"],
                    gstr2b_tax=e["tax"],
                    difference=-e["tax"],
                    note="on the portal but not in your books: unrecorded purchase or wrong entry",
                )
            )
    return rows


def summarize(rows: list[ReconRow]) -> dict:
    by_status: dict[str, int] = defaultdict(int)
    for r in rows:
        by_status[r.status.value] += 1
    chase: dict[str, dict] = {}
    for r in rows:
        if r.itc_at_risk > 0:
            c = chase.setdefault(
                r.supplier_gstin, {"supplier": r.supplier_name, "invoices": 0, "itc_at_risk": 0.0}
            )
            c["invoices"] += 1
            c["itc_at_risk"] = round(c["itc_at_risk"] + r.itc_at_risk, 2)
    return {
        "counts": dict(by_status),
        "itc_in_books": round(sum(r.books_tax for r in rows), 2),
        "itc_in_2b": round(
            sum(r.gstr2b_tax for r in rows if r.status is not ReconStatus.ITC_UNAVAILABLE), 2
        ),
        "itc_at_risk": round(sum(r.itc_at_risk for r in rows), 2),
        "suppliers_to_chase": dict(
            sorted(chase.items(), key=lambda kv: kv[1]["itc_at_risk"], reverse=True)
        ),
    }
