import streamlit as st
import pandas as pd
import os, sys

# Ensure src/ imports work when running from project root
sys.path.append(os.path.abspath("."))

from src.genai_copilot.loaders.csv_loader import read_csv_bytes
from src.genai_copilot.ratios import compute_ratios
from src.genai_copilot.anomalies import detect_anomalies
from src.genai_copilot.utils.kpi import compute_kpis
from src.genai_copilot.commentary import make_commentary

st.set_page_config(page_title="GenAI Financial Copilot", layout="wide")
st.title("📊 GenAI Financial Copilot — Streamlit")
st.caption("Upload a CSV with financial statements to get KPIs, ratios, anomalies, charts, and a summary.")

uploaded = st.file_uploader("Upload CSV", type=["csv"])

# Load file (with friendly error)
df = pd.DataFrame()
if uploaded is not None:
    try:
        b = uploaded.getvalue()
        df = read_csv_bytes(b)
    except Exception as e:
        st.error(f"Could not read file as CSV: {e}")
        df = pd.DataFrame()

if not df.empty:
    st.subheader("Data Preview")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Rows", df.shape[0])
    with c2:
        st.metric("Columns", df.shape[1])
    with c3:
        st.metric("Null values (total)", int(df.isna().sum().sum()))
    st.dataframe(df.head(20), width="stretch")

    # Compute analytics
    kpis = compute_kpis(df)
    ratios_df = compute_ratios(df)
    report = detect_anomalies(df)

    # KPIs
    if kpis and len(kpis) > 0:
        st.subheader("Key KPIs")
        kpi_cols = st.columns(len(kpis))
        for (k, v), col in zip(kpis.items(), kpi_cols):
            try:
                if isinstance(v, (int, float)) and abs(v) < 1:
                    col.metric(k.replace("_", " ").title(), f"{v:,.2%}")
                else:
                    col.metric(k.replace("_", " ").title(), f"{v:,.2f}")
            except Exception:
                col.metric(k.replace("_", " ").title(), str(v))

    # Ratios
    st.subheader("Financial Ratios")
    if isinstance(ratios_df, pd.DataFrame) and not ratios_df.empty:
        st.dataframe(ratios_df, width="stretch")
        num_cols = ratios_df.select_dtypes("number")
        if not num_cols.empty:
            st.line_chart(num_cols)
        st.download_button(
            "Download Ratios CSV",
            data=ratios_df.to_csv(index=False).encode("utf-8"),
            file_name="ratios.csv",
            mime="text/csv",
        )
    else:
        st.info(
            "No ratios computed — check column names (e.g., revenue, net_income, "
            "current_assets, current_liabilities, total_assets, total_equity, total_debt, interest_expense)."
        )

    # Anomalies
    st.subheader("Anomalies & Spikes")
    if isinstance(report, dict) and (report.get("outliers") or report.get("spikes")):
        st.json(report)
    else:
        st.success("No significant outliers or spikes detected with current thresholds.")

    # Summary
    st.subheader("Executive Summary")
    try:
        summary_text = make_commentary(kpis=kpis, ratios=ratios_df if isinstance(ratios_df, pd.DataFrame) else pd.DataFrame())
        st.write(summary_text)
    except Exception as e:
        st.warning(f"Could not generate commentary: {e}")
else:
    st.info("Upload a CSV to begin. A sample file is in `data/raw/sample_financials.csv`.")
