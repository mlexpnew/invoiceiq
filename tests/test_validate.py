from datetime import date

from conftest import COMPANY, SUPPLIER_MH, TODAY
from invoiceiq.validate import itc_deadline, validate


def codes(inv, **kw):
    return {i.code for i in validate(inv, company_gstin=COMPANY, today=TODAY, **kw)}


def test_clean_invoice_has_no_issues(good_invoice):
    assert codes(good_invoice) == set()


def test_math_errors_are_caught_independently(good_invoice):
    good_invoice.items[0].unit_price = 2600.0
    assert codes(good_invoice) == {"LINE_MATH"}


def test_total_and_tax_math(good_invoice):
    good_invoice.total += 500
    assert codes(good_invoice) == {"TOTAL_MATH"}


def test_overcharged_tax(good_invoice):
    good_invoice.cgst += 100
    good_invoice.sgst += 100
    good_invoice.total += 200
    assert codes(good_invoice) == {"TAX_MATH"}


def test_wrong_tax_type_for_inter_state(good_invoice):
    good_invoice.supplier_gstin = SUPPLIER_MH  # Maharashtra -> Karnataka needs IGST
    assert "TAX_TYPE" in codes(good_invoice)


def test_unequal_cgst_sgst(good_invoice):
    good_invoice.cgst += 50
    good_invoice.sgst -= 50
    assert "CGST_SGST_SPLIT" in codes(good_invoice)


def test_billed_to_someone_else_blocks_itc(good_invoice):
    good_invoice.buyer_gstin = "29AACCN9999Z1Z" + "7"
    assert "BUYER_MISMATCH" in codes(good_invoice)


def test_rule_46_invoice_number(good_invoice):
    good_invoice.invoice_no = "SO/0012/26-27/BRANCH-EAST"
    assert codes(good_invoice) == {"INVOICE_NO_FORMAT"}


def test_retired_slab_after_gst2(good_invoice):
    good_invoice.items[1].gst_rate = 12.0
    good_invoice.cgst = good_invoice.sgst = 600.0
    good_invoice.total = 8700.0
    assert codes(good_invoice) == {"RATE_RETIRED"}


def test_itc_deadline_section_16_4():
    assert itc_deadline(date(2025, 6, 10)) == date(2026, 11, 30)
    assert itc_deadline(date(2026, 2, 10)) == date(2026, 11, 30)


def test_itc_lapsed_and_closing_soon(good_invoice):
    good_invoice.invoice_date = date(2025, 1, 15)
    assert "ITC_LAPSED" in codes(good_invoice)
    good_invoice.invoice_date = date(2025, 12, 1)  # FY 25-26 deadline 30 Nov 2026
    assert "ITC_DEADLINE" in codes(good_invoice)


def test_missing_fields_and_future_date(good_invoice):
    good_invoice.invoice_no = ""
    good_invoice.invoice_date = date(2027, 1, 1)
    assert {"MISSING_FIELD", "DATE_FUTURE"} <= codes(good_invoice)
