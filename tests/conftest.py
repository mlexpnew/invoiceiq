import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from invoiceiq import gstin as G  # noqa: E402
from invoiceiq.models import Invoice, LineItem  # noqa: E402

COMPANY = G.make("29", "AACCN4821K")
SUPPLIER_KA = G.make("29", "AAFCS1132M")
SUPPLIER_MH = G.make("27", "AAGFW2245N")
TODAY = date(2026, 11, 12)


@pytest.fixture
def good_invoice() -> Invoice:
    """Intra-state Karnataka purchase, every figure consistent."""
    return Invoice(
        source="a.pdf", supplier_name="Sahyadri Office Supplies", supplier_gstin=SUPPLIER_KA,
        buyer_gstin=COMPANY, place_of_supply="29", invoice_no="SO/0012/26-27",
        invoice_date=date(2026, 8, 14),
        items=[LineItem(description="Toner", hsn="8443", qty=2, unit_price=2500.0,
                        taxable_value=5000.0, gst_rate=18.0),
               LineItem(description="Paper", hsn="4802", qty=10, unit_price=250.0,
                        taxable_value=2500.0, gst_rate=5.0)],
        taxable_value=7500.0, cgst=512.5, sgst=512.5, round_off=0.0, total=8525.0,
    )  # fmt: skip
