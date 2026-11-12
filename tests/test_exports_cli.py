import io
import json
import xml.etree.ElementTree as ET

from openpyxl import load_workbook

from conftest import TODAY
from invoiceiq.cli import main
from invoiceiq.export.excel import workbook
from invoiceiq.export.tally import tally_xml, voucher
from invoiceiq.pipeline import process
from invoiceiq.reconcile import load_gstr2b
from invoiceiq.synth import COMPANY, generate, gstr2b, render


def test_tally_voucher_balances_with_round_off(good_invoice):
    good_invoice.round_off, good_invoice.total = 0.4, 8525.4
    xml, balance = voucher(good_invoice)
    assert balance == 0.0 and "Round Off" in xml and "Purchase @ 18%" in xml
    ET.fromstring(tally_xml([good_invoice], "Nimbus & Co"))  # well-formed, escaped


def test_workbook_has_review_sheets():
    docs = generate(12, seed=4)
    data, _ = gstr2b(docs)
    res = process([(d.file, render(d)) for d in docs], COMPANY[1],
                  load_gstr2b(json.dumps(data)), today=TODAY)  # fmt: skip
    wb = load_workbook(io.BytesIO(workbook(res)))
    assert wb.sheetnames == ["Summary", "Invoices", "Issues", "GSTR-2B Recon"]
    assert wb["Invoices"].max_row == 13


def test_cli_writes_workbook_and_tally(tmp_path, capsys):
    folder = tmp_path / "pdfs"
    folder.mkdir()
    docs = generate(5, seed=2, fault_rate=0)
    for d in docs:
        (folder / d.file).write_bytes(render(d))
    data, _ = gstr2b(docs)
    (tmp_path / "2b.json").write_text(json.dumps(data))
    out, tally = tmp_path / "r.xlsx", tmp_path / "t.xml"
    code = main([str(folder), "--company-gstin", COMPANY[1], "--gstr2b", str(tmp_path / "2b.json"),
                 "--out", str(out), "--tally", str(tally), "--json"])  # fmt: skip
    summary = json.loads(capsys.readouterr().out)
    assert code == 0 and out.exists() and tally.exists()
    assert summary["invoices"] == 5 and "itc_at_risk" in summary


def test_cli_empty_folder(tmp_path):
    assert main([str(tmp_path)]) == 2


def test_streamlit_app_runs_on_sample_data():
    import pytest

    pytest.importorskip("streamlit")
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=60)
    at.run()
    at.button[0].click().run()
    assert not at.exception and at.metric[0].value == "24"
