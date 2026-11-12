"""Command line: a folder of PDFs in, a review workbook (and Tally file) out.

    invoiceiq invoices/ --company-gstin 29AACCN4821K1Z9 --gstr2b 2B_Oct.json --out review.xlsx
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .export.excel import workbook
from .export.tally import tally_xml
from .pipeline import process
from .reconcile import load_gstr2b, summarize


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="invoiceiq", description=__doc__.splitlines()[0])
    p.add_argument("folder", help="folder of invoice PDFs")
    p.add_argument("--company-gstin", default="", help="your GSTIN: invoices must be billed to it")
    p.add_argument("--company-name", default="My Company", help="Tally company name")
    p.add_argument("--gstr2b", help="GSTR-2B JSON (from the GST portal) or CSV")
    p.add_argument("--out", default="invoiceiq_review.xlsx")
    p.add_argument("--tally", help="also write a Tally import XML of clean invoices")
    p.add_argument("--llm", default="", help="LLM fallback: groq, gemini, openrouter, ollama")
    p.add_argument("--json", action="store_true", help="print the summary as JSON")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    pdfs = sorted(Path(a.folder).glob("*.pdf"))
    if not pdfs:
        print(f"no PDFs in {a.folder}", file=sys.stderr)
        return 2
    gstr2b = None
    if a.gstr2b:
        path = Path(a.gstr2b)
        gstr2b = load_gstr2b(path.read_bytes(), path.name)
    llm = None
    if a.llm:
        from .extract.llm import LLMExtractor

        llm = LLMExtractor(a.llm)

    res = process([(f.name, f.read_bytes()) for f in pdfs], a.company_gstin, gstr2b, llm)
    Path(a.out).write_bytes(workbook(res))
    clean = res.clean()
    if a.tally:
        Path(a.tally).write_text(tally_xml(clean, a.company_name), encoding="utf-8")

    summary = {
        "invoices": len(res.invoices),
        "ready_to_post": len(clean),
        "blocked": len(res.invoices) - len(clean),
        "issues": len(res.issues),
        "workbook": a.out,
    }
    if res.recon:
        s = summarize(res.recon)
        summary.update(itc_at_risk=s["itc_at_risk"], recon=s["counts"])
    if a.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"{summary['invoices']} invoices: {summary['ready_to_post']} ready to post, "
              f"{summary['blocked']} blocked, {summary['issues']} issues")  # fmt: skip
        if res.recon:
            print(f"ITC at risk: Rs. {summary['itc_at_risk']:,.2f}")
        print(f"review workbook: {a.out}" + (f", Tally file: {a.tally}" if a.tally else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
