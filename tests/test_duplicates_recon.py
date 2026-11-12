import json

from invoiceiq.duplicates import find_duplicates, normalize_invoice_no
from invoiceiq.models import ReconStatus
from invoiceiq.reconcile import load_gstr2b, reconcile, summarize


def test_invoice_number_normalisation():
    assert normalize_invoice_no("INV/0012/25-26") == normalize_invoice_no("inv-12-25-26")
    assert normalize_invoice_no("A-001") != normalize_invoice_no("A-010")


def test_exact_and_possible_duplicates(good_invoice):
    copy = good_invoice.model_copy(update={"source": "b.pdf", "invoice_no": "so-12/26-27"})
    reissued = good_invoice.model_copy(update={"source": "c.pdf", "invoice_no": "SO/0099/26-27"})
    issues = {(i.source, i.code) for i in find_duplicates([good_invoice, copy, reissued])}
    assert issues == {("b.pdf", "DUPLICATE"), ("c.pdf", "POSSIBLE_DUPLICATE")}


def portal(inv, tax, itcavl="Y", inum=None):
    item = {"txval": 7500, "cgst": tax / 2, "sgst": tax / 2, "igst": 0}
    doc = {"inum": inum or inv.invoice_no, "dt": "14-08-2026", "val": 1, "itcavl": itcavl,
           "items": [item]}  # fmt: skip
    supplier = {"ctin": inv.supplier_gstin, "trdnm": "S", "inv": [doc]}
    return json.dumps({"data": {"docdata": {"b2b": [supplier]}}})


def test_reconcile_buckets(good_invoice):
    status = lambda raw: reconcile([good_invoice], load_gstr2b(raw))[0].status  # noqa: E731
    assert status(portal(good_invoice, 1025, inum="SO-12-26-27")) is ReconStatus.MATCHED
    assert status(portal(good_invoice, 800)) is ReconStatus.VALUE_MISMATCH
    assert status(portal(good_invoice, 1025, itcavl="N")) is ReconStatus.ITC_UNAVAILABLE
    rows = reconcile([good_invoice], [])
    assert rows[0].status is ReconStatus.MISSING_IN_2B and rows[0].itc_at_risk == 1025


def test_missing_in_books_and_summary(good_invoice):
    other = good_invoice.model_copy(update={"invoice_no": "SO/0500/26-27"})
    rows = reconcile([], load_gstr2b(portal(other, 900)))
    assert rows[0].status is ReconStatus.MISSING_IN_BOOKS
    s = summarize(reconcile([good_invoice], []))
    assert s["itc_at_risk"] == 1025
    assert list(s["suppliers_to_chase"]) == [good_invoice.supplier_gstin]


def test_csv_gstr2b(good_invoice):
    csv = (
        "gstin,invoice_no,invoice_date,taxable_value,cgst,sgst,igst\n"
        f"{good_invoice.supplier_gstin},SO/0012/26-27,14/08/2026,7500,512.5,512.5,0\n"
    )
    (row,) = reconcile([good_invoice], load_gstr2b(csv, "2b.csv"))
    assert row.status is ReconStatus.MATCHED
