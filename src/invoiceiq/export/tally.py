"""Tally Prime import file: purchase vouchers for invoices that passed every check.

Only clean invoices are exported, so a blocked invoice can never reach the books by
accident. Ledger names are configurable to match the client's chart of accounts.
Each voucher balances to zero: party credited, purchase and input tax ledgers debited.
"""

from __future__ import annotations

from dataclasses import dataclass
from xml.sax.saxutils import escape

from ..models import Invoice


@dataclass(frozen=True)
class Ledgers:
    purchase: str = "Purchase @ {rate}%"
    cgst: str = "Input CGST"
    sgst: str = "Input SGST"
    igst: str = "Input IGST"
    round_off: str = "Round Off"


def _entry(ledger: str, amount: float) -> str:
    # Tally convention: negative = debit (ISDEEMEDPOSITIVE Yes), positive = credit
    deemed = "Yes" if amount < 0 else "No"
    return (
        "<LEDGERENTRIES.LIST>"
        f"<LEDGERNAME>{escape(ledger)}</LEDGERNAME>"
        f"<ISDEEMEDPOSITIVE>{deemed}</ISDEEMEDPOSITIVE>"
        f"<AMOUNT>{amount:.2f}</AMOUNT>"
        "</LEDGERENTRIES.LIST>"
    )


def voucher(inv: Invoice, ledgers: Ledgers = Ledgers()) -> tuple[str, float]:
    """Return voucher XML and its balance (must be 0.00)."""
    entries = [(inv.supplier_name or inv.supplier_gstin, inv.total)]
    by_rate: dict[float, float] = {}
    for it in inv.items:
        by_rate[it.gst_rate] = by_rate.get(it.gst_rate, 0.0) + it.taxable_value
    if not by_rate:
        by_rate[0.0] = inv.taxable_value
    for rate, amount in sorted(by_rate.items()):
        entries.append((ledgers.purchase.format(rate=f"{rate:g}"), -round(amount, 2)))
    for ledger, amount in ((ledgers.cgst, inv.cgst), (ledgers.sgst, inv.sgst),
                           (ledgers.igst, inv.igst)):  # fmt: skip
        if amount:
            entries.append((ledger, -amount))
    balance = round(sum(a for _, a in entries), 2)
    if balance:  # rounding difference goes to the round-off ledger
        entries.append((ledgers.round_off, -balance))
    xml = (
        '<TALLYMESSAGE xmlns:UDF="TallyUDF">'
        '<VOUCHER VCHTYPE="Purchase" ACTION="Create">'
        f"<DATE>{inv.invoice_date:%Y%m%d}</DATE>"
        "<VOUCHERTYPENAME>Purchase</VOUCHERTYPENAME>"
        f"<REFERENCE>{escape(inv.invoice_no)}</REFERENCE>"
        f"<REFERENCEDATE>{inv.invoice_date:%Y%m%d}</REFERENCEDATE>"
        f"<PARTYLEDGERNAME>{escape(entries[0][0])}</PARTYLEDGERNAME>"
        f"<PARTYGSTIN>{inv.supplier_gstin}</PARTYGSTIN>"
        f"<NARRATION>Imported by InvoiceIQ from {escape(inv.source)}</NARRATION>"
        + "".join(_entry(name, amt) for name, amt in entries)
        + "</VOUCHER></TALLYMESSAGE>"
    )
    return xml, round(sum(a for _, a in entries), 2)


def tally_xml(invoices: list[Invoice], company: str, ledgers: Ledgers = Ledgers()) -> str:
    body = "".join(voucher(inv, ledgers)[0] for inv in invoices)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>"
        "<BODY><IMPORTDATA><REQUESTDESC><REPORTNAME>Vouchers</REPORTNAME>"
        f"<STATICVARIABLES><SVCURRENTCOMPANY>{escape(company)}</SVCURRENTCOMPANY>"
        "</STATICVARIABLES></REQUESTDESC>"
        f"<REQUESTDATA>{body}</REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>"
    )
