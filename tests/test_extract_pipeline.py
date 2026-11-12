import pytest

from conftest import TODAY
from invoiceiq.extract.llm import merge
from invoiceiq.extract.pdf import pdf_text
from invoiceiq.extract.rules import extract
from invoiceiq.models import Invoice
from invoiceiq.pipeline import process
from invoiceiq.synth import COMPANY, DEV_TEMPLATES, generate, render


@pytest.mark.parametrize("template", DEV_TEMPLATES)
def test_every_dev_layout_extracts_exactly(template):
    for d in generate(6, seed=3, fault_rate=0, templates=[template]):
        inv = extract(pdf_text(render(d)), company_gstin=COMPANY[1])
        assert inv.supplier_gstin == d.supplier[1] and inv.buyer_gstin == d.buyer[1]
        assert inv.invoice_no == d.invoice_no and inv.invoice_date == d.invoice_date
        assert (inv.taxable_value, inv.total) == (d.taxable, d.total)
        assert (inv.cgst, inv.sgst, inv.igst) == (d.cgst, d.sgst, d.igst)
        assert len(inv.items) == len(d.items) and inv.confidence == 1.0


def test_shared_line_cgst_sgst_and_indian_amounts():
    text = "Invoice No: A/1\nDate: 01/10/2026\nTaxable Value 1,00,000.00\n" \
           "CGST: 9,000.00  SGST: 9,000.00\nGrand Total Rs. 1,18,000.00"
    inv = extract(text)
    assert (inv.taxable_value, inv.cgst, inv.sgst, inv.total) == (100000, 9000, 9000, 118000)


def test_low_confidence_when_fields_missing():
    assert extract("Some text without an invoice").confidence < 0.8


class FakeLLM:
    model = "fake"

    def fields(self, text):
        return {"invoice_no": "X/9", "total": "1,180.00", "taxable_value": 1000, "cgst": 90,
                "sgst": 90, "supplier_gstin": "should-not-overwrite"}


def test_llm_merge_only_fills_gaps():
    inv = Invoice(supplier_gstin="29AAFCS1132M1Z7")
    out = merge(inv, FakeLLM().fields(""))
    assert out.invoice_no == "X/9" and out.total == 1180.0
    assert out.supplier_gstin == "29AAFCS1132M1Z7" and out.extractor == "rules+llm"


def test_pipeline_end_to_end_with_scanned_pdf():
    docs = generate(4, seed=5, fault_rate=0)
    files = [(d.file, render(d)) for d in docs]
    import io

    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.rect(10, 10, 100, 100)  # an "image only" page: no text layer
    c.save()
    files.append(("scan.pdf", buf.getvalue()))
    res = process(files, company_gstin=COMPANY[1], today=TODAY)
    assert {i.code for i in res.issues if i.source == "scan.pdf"} == {"SCANNED_PDF"}
    assert len(res.clean()) == 4


def test_llm_used_only_below_threshold(monkeypatch):
    calls = []

    class Spy(FakeLLM):
        def fields(self, text):
            calls.append(text)
            return super().fields(text)

    d = generate(1, seed=5, fault_rate=0)[0]
    process([(d.file, render(d))], company_gstin=COMPANY[1], llm=Spy(), today=TODAY)
    assert calls == []  # confident rule extraction never pays for an LLM call
