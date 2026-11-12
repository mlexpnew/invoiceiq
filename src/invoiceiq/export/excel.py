"""Excel review workbook: what an accountant opens first.

Sheets: Summary (ITC position and suppliers to chase), Invoices, Issues, Reconciliation.
"""

from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from ..models import Severity
from ..pipeline import Result
from ..reconcile import summarize

HEADER = PatternFill("solid", fgColor="1F3A5F")
RED = PatternFill("solid", fgColor="FBE3E1")
AMBER = PatternFill("solid", fgColor="FFF4D6")
GREEN = PatternFill("solid", fgColor="E3F4E8")
# Indian digit grouping (1,23,45,678.00): Excel needs conditional sections for lakh/crore
INR = r"[>=10000000]##\,##\,##\,##0.00;[>=100000]##\,##\,##0.00;##,##0.00"


def _sheet(wb: Workbook, title: str, headers: list[str], rows: list[list], money_cols=()):
    ws = wb.create_sheet(title)
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = HEADER
        c.alignment = Alignment(vertical="center")
    for r in rows:
        ws.append(r)
    for col in money_cols:
        for cell in ws.iter_rows(min_row=2, min_col=col, max_col=col):
            cell[0].number_format = INR
    for i, h in enumerate(headers, start=1):
        width = max([len(str(h))] + [len(str(r[i - 1])) for r in rows[:200]]) + 2
        ws.column_dimensions[get_column_letter(i)].width = min(width, 60)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    return ws


def workbook(res: Result) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    blocked = res.blocked_sources()

    # Summary
    ws = wb.create_sheet("Summary")
    errors = sum(i.severity is Severity.ERROR for i in res.issues)
    warnings = len(res.issues) - errors
    lines = [
        ("Invoices processed", len(res.invoices)),
        ("Ready to post (no errors)", len(res.invoices) - len(blocked)),
        ("Blocked (errors)", len(blocked)),
        ("Errors / warnings", f"{errors} / {warnings}"),
    ]
    if res.recon:
        s = summarize(res.recon)
        lines += [
            ("ITC as per books", s["itc_in_books"]),
            ("ITC as per GSTR-2B", s["itc_in_2b"]),
            ("ITC at risk", s["itc_at_risk"]),
        ]
    ws.append(["InvoiceIQ review summary"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([])
    for k, v in lines:
        ws.append([k, v])
        if isinstance(v, float):
            ws.cell(ws.max_row, 2).number_format = INR
    if res.recon:
        ws.append([])
        ws.append(["Suppliers to chase", "GSTIN", "Invoices", "ITC at risk"])
        for c in ws[ws.max_row]:
            c.font = Font(bold=True)
        for g, c in s["suppliers_to_chase"].items():
            ws.append([c["supplier"], g, c["invoices"], c["itc_at_risk"]])
            ws.cell(ws.max_row, 4).number_format = INR
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 22

    # Invoices
    inv_rows = [
        [i.source, "BLOCKED" if i.source in blocked else "OK", i.supplier_name, i.supplier_gstin,
         i.invoice_no, i.invoice_date.isoformat() if i.invoice_date else "", i.taxable_value,
         i.cgst, i.sgst, i.igst, i.total, i.extractor, i.confidence]
        for i in res.invoices
    ]  # fmt: skip
    ws = _sheet(wb, "Invoices",
                ["File", "Status", "Supplier", "Supplier GSTIN", "Invoice No", "Date",
                 "Taxable", "CGST", "SGST", "IGST", "Total", "Read by", "Confidence"],
                inv_rows, money_cols=range(7, 12))  # fmt: skip
    for row in ws.iter_rows(min_row=2, max_col=2):
        row[1].fill = RED if row[1].value == "BLOCKED" else GREEN

    # Issues
    ws = _sheet(wb, "Issues", ["File", "Invoice No", "Severity", "Code", "What to do"],
                [[i.source, i.invoice_no, i.severity.value, i.code, i.message]
                 for i in res.issues])  # fmt: skip
    for row in ws.iter_rows(min_row=2, min_col=3, max_col=3):
        row[0].fill = RED if row[0].value == "error" else AMBER

    # Reconciliation
    if res.recon:
        ws = _sheet(wb, "GSTR-2B Recon",
                    ["Status", "Supplier", "GSTIN", "Invoice No", "Date", "Tax (books)",
                     "Tax (2B)", "Difference", "ITC at risk", "Note"],
                    [[r.status.value, r.supplier_name, r.supplier_gstin, r.invoice_no,
                      r.invoice_date.isoformat() if r.invoice_date else "", r.books_tax,
                      r.gstr2b_tax, r.difference, r.itc_at_risk, r.note] for r in res.recon],
                    money_cols=range(6, 10))  # fmt: skip
        for row in ws.iter_rows(min_row=2, max_col=1):
            row[0].fill = GREEN if row[0].value == "matched" else (
                AMBER if row[0].value == "missing_in_books" else RED)  # fmt: skip

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
