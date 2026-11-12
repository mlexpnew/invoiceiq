"""InvoiceIQ demo app (Streamlit). Deploy free on Streamlit Community Cloud.

    pip install -e ".[app]" && streamlit run app.py
"""

from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent / "src"))

from invoiceiq.export.excel import workbook  # noqa: E402
from invoiceiq.export.tally import tally_xml  # noqa: E402
from invoiceiq.pipeline import process  # noqa: E402
from invoiceiq.reconcile import load_gstr2b, summarize  # noqa: E402
from invoiceiq.synth import COMPANY, generate, gstr2b, render  # noqa: E402

st.set_page_config(page_title="InvoiceIQ", page_icon="🧾", layout="wide")
st.title("InvoiceIQ")
st.caption(
    "Check GST purchase invoices and reconcile them with GSTR-2B before you claim ITC. "
    "Files are processed in memory and never stored."
)


@st.cache_data
def sample_pack() -> tuple[list[tuple[str, bytes]], bytes]:
    docs = generate(24, seed=21)
    data, _ = gstr2b(docs)
    return [(d.file, render(d)) for d in docs], json.dumps(data).encode()


with st.sidebar:
    company = st.text_input("Your GSTIN (buyer)", value=COMPANY[1]).strip().upper()
    company_name = st.text_input("Company name for Tally", value=COMPANY[0])
    use_sample = st.toggle("Use sample invoices", value=True)

if use_sample:
    files, portal_raw = sample_pack()
    st.info(f"Loaded {len(files)} sample invoices (some with real-world errors) and a GSTR-2B.")
else:
    uploads = st.file_uploader("Invoice PDFs", type="pdf", accept_multiple_files=True)
    portal_up = st.file_uploader("GSTR-2B (JSON from the portal, or CSV)", type=["json", "csv"])
    files = [(u.name, u.getvalue()) for u in uploads or []]
    portal_raw = portal_up.getvalue() if portal_up else None

if files and st.button("Check invoices", type="primary"):
    portal = load_gstr2b(portal_raw) if portal_raw else None
    res = process(files, company_gstin=company, gstr2b=portal)
    clean = res.clean()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Invoices", len(res.invoices))
    c2.metric("Ready to post", len(clean))
    c3.metric("Blocked", len(res.invoices) - len(clean))
    if res.recon:
        c4.metric("ITC at risk", f"Rs. {summarize(res.recon)['itc_at_risk']:,.0f}")

    tabs = st.tabs(["Issues", "Invoices", "GSTR-2B reconciliation"])
    with tabs[0]:
        st.dataframe(
            [{"File": i.source, "Invoice": i.invoice_no, "Severity": i.severity.value,
              "Check": i.code, "What to do": i.message} for i in res.issues],
            use_container_width=True, hide_index=True,
        )  # fmt: skip
    with tabs[1]:
        blocked = res.blocked_sources()
        st.dataframe(
            [{"File": i.source, "Status": "Blocked" if i.source in blocked else "OK",
              "Supplier": i.supplier_name, "GSTIN": i.supplier_gstin, "Invoice": i.invoice_no,
              "Date": i.invoice_date, "Taxable": i.taxable_value, "Tax": i.total_tax,
              "Total": i.total} for i in res.invoices],
            use_container_width=True, hide_index=True,
        )  # fmt: skip
    with tabs[2]:
        if res.recon:
            s = summarize(res.recon)
            st.write("**Suppliers to chase**")
            st.dataframe(
                [{"Supplier": v["supplier"], "GSTIN": g, "Invoices": v["invoices"],
                  "ITC at risk": v["itc_at_risk"]} for g, v in s["suppliers_to_chase"].items()],
                use_container_width=True, hide_index=True,
            )  # fmt: skip
            st.dataframe(
                [r.model_dump(mode="json") for r in res.recon],
                use_container_width=True, hide_index=True,
            )
        else:
            st.write("Attach a GSTR-2B file to reconcile.")

    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w") as z:
        z.writestr("invoiceiq_review.xlsx", workbook(res))
        z.writestr("tally_import.xml", tally_xml(clean, company_name))
    st.download_button("Download review workbook + Tally file", bundle.getvalue(),
                       "invoiceiq_output.zip", "application/zip")  # fmt: skip
