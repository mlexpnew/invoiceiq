"""Score InvoiceIQ end to end on the synthetic benchmark.

    python -m invoiceiq.evaluate --n 120 --out eval_results

Three questions, each answered with numbers:
1. Extraction: is every field read exactly right? (per field, per layout)
2. Checks: are the injected errors caught, and are clean invoices left alone?
3. Reconciliation: does every invoice land in the right GSTR-2B bucket?
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

from .duplicates import normalize_invoice_no
from .pipeline import LLM_THRESHOLD, process
from .reconcile import load_gstr2b
from .synth import COMPANY, DEV_TEMPLATES, HELD_OUT_TEMPLATES, TODAY, write_benchmark

FIELDS = ("supplier_gstin", "buyer_gstin", "invoice_no", "invoice_date", "place_of_supply",
          "taxable_value", "cgst", "sgst", "igst", "total", "n_items")  # fmt: skip


def _value(inv, field: str):
    if field == "invoice_date":
        return inv.invoice_date.isoformat() if inv.invoice_date else ""
    if field == "n_items":
        return len(inv.items)
    return getattr(inv, field)


def _same(a, b) -> bool:
    if isinstance(b, float) or isinstance(a, float):
        return abs(float(a or 0) - float(b or 0)) < 0.005
    return str(a).strip().upper() == str(b).strip().upper()


def _pct(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def run(
    bench: Path, n: int, seed: int, templates: list[str] | None = None, llm=None
) -> dict:
    docs = write_benchmark(bench, n, seed, templates)
    truth = {d.file: d.truth() for d in docs}
    files = [(d.file, (bench / "pdf" / d.file).read_bytes()) for d in docs]
    gstr2b = load_gstr2b((bench / "gstr2b.json").read_text())
    recon_truth = json.loads((bench / "recon_truth.json").read_text())

    t0 = time.perf_counter()
    res = process(files, company_gstin=COMPANY[1], gstr2b=gstr2b, today=TODAY, llm=llm)
    seconds = time.perf_counter() - t0

    # 1. Extraction
    field_ok: dict[str, int] = defaultdict(int)
    layout_ok: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    misses = []
    for inv in res.invoices:
        t = truth[inv.source]
        all_ok = True
        for f in FIELDS:
            ok = _same(_value(inv, f), t[f])
            field_ok[f] += ok
            if not ok:
                all_ok = False
                misses.append({"file": inv.source, "field": f, "got": str(_value(inv, f)),
                               "want": str(t[f])})  # fmt: skip
        layout_ok[t["template"]][0] += all_ok
        layout_ok[t["template"]][1] += 1
    # Confidence routing: wrong extractions should fall below the LLM threshold
    wrong = {m["file"] for m in misses}
    routed = sum(inv.confidence < LLM_THRESHOLD for inv in res.invoices if inv.source in wrong)
    kept = sum(inv.confidence >= LLM_THRESHOLD for inv in res.invoices if inv.source not in wrong)
    extraction = {
        "routing": {
            "wrong_docs": len(wrong),
            "wrong_sent_to_llm": routed,
            "correct_docs": len(docs) - len(wrong),
            "correct_kept_on_rules": kept,
        },
        "field_accuracy": {f: _pct(field_ok[f], len(docs)) for f in FIELDS},
        "documents_fully_correct": _pct(sum(v[0] for v in layout_ok.values()), len(docs)),
        "by_layout": {k: _pct(v[0], v[1]) for k, v in sorted(layout_ok.items())},
    }

    # 2. Error detection (only codes the benchmark injects are scored)
    scored = {c for t in truth.values() for c in t["expected_issues"]}
    found = defaultdict(set)
    for i in res.issues:
        if i.code in scored:
            found[i.source].add(i.code)
    per_code = {}
    tp_all = fp_all = fn_all = 0
    for code in sorted(scored):
        tp = sum(code in found[f] and code in t["expected_issues"] for f, t in truth.items())
        fp = sum(code in found[f] and code not in t["expected_issues"] for f, t in truth.items())
        fn = sum(code not in found[f] and code in t["expected_issues"] for f, t in truth.items())
        tp_all, fp_all, fn_all = tp_all + tp, fp_all + fp, fn_all + fn
        per_code[code] = {"injected": tp + fn, "caught": tp, "false_alarms": fp}
    clean = [f for f, t in truth.items() if not t["expected_issues"]]
    clean_flagged = sum(
        any(i.source == f and i.severity.value == "error" for i in res.issues) for f in clean
    )
    detection = {
        "precision": _pct(tp_all, tp_all + fp_all),
        "recall": _pct(tp_all, tp_all + fn_all),
        "clean_invoices": len(clean),
        "clean_wrongly_blocked": clean_flagged,
        "per_code": per_code,
    }

    # 3. Reconciliation
    got = {f"{r.supplier_gstin}|{normalize_invoice_no(r.invoice_no)}": r.status.value
           for r in res.recon}  # fmt: skip
    want = {
        f"{k.split('|')[0]}|{normalize_invoice_no(k.split('|')[1])}": v
        for k, v in recon_truth.items()
    }
    correct = sum(got.get(k) == v for k, v in want.items())
    by_status: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for k, v in want.items():
        by_status[v][0] += got.get(k) == v
        by_status[v][1] += 1
    recon = {
        "accuracy": _pct(correct, len(want)),
        "by_status": {k: f"{v[0]}/{v[1]}" for k, v in sorted(by_status.items())},
        "itc_at_risk": round(sum(r.itc_at_risk for r in res.recon), 2),
    }

    return {
        "benchmark": {"invoices": len(docs), "layouts": len({d.template for d in docs}),
                      "seed": seed, "llm": getattr(llm, "model", None),
                      "with_injected_errors": len(docs) - len(clean)},  # fmt: skip
        "extraction": extraction,
        "detection": detection,
        "reconciliation": recon,
        "throughput": {"seconds": round(seconds, 2),
                       "invoices_per_second": round(len(docs) / seconds, 1)},  # fmt: skip
        "extraction_misses": misses[:50],
    }


def report_markdown(r: dict) -> str:
    e, d, c, b = r["extraction"], r["detection"], r["reconciliation"], r["benchmark"]
    pct = lambda v: "n/a" if v is None else f"{v * 100:.1f}%"  # noqa: E731
    out = [
        f"### InvoiceIQ benchmark ({b['invoices']} invoices, {b['layouts']} layouts, "
        f"{b['with_injected_errors']} with injected errors, seed {b['seed']})",
        "",
        "| Metric | Score |",
        "|---|---|",
        f"| Documents with every field correct | {pct(e['documents_fully_correct'])} |",
        f"| Error detection precision | {pct(d['precision'])} |",
        f"| Error detection recall | {pct(d['recall'])} |",
        f"| Clean invoices wrongly blocked | {d['clean_wrongly_blocked']} of "
        f"{d['clean_invoices']} |",
        f"| GSTR-2B reconciliation accuracy | {pct(c['accuracy'])} |",
        f"| Throughput | {r['throughput']['invoices_per_second']} invoices/s (CPU, no LLM) |",
        "",
        "| Field | Accuracy |",
        "|---|---|",
        *[f"| {k} | {pct(v)} |" for k, v in e["field_accuracy"].items()],
        "",
        "| Error type | Injected | Caught | False alarms |",
        "|---|---|---|---|",
        *[f"| {k} | {v['injected']} | {v['caught']} | {v['false_alarms']} |"
          for k, v in d["per_code"].items()],  # fmt: skip
        "",
        "| Reconciliation bucket | Correct |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in c["by_status"].items()],
    ]
    return "\n".join(out) + "\n"


def held_out_markdown(h: dict, title: str = "") -> str:
    e, d, c, rt = h["extraction"], h["detection"], h["reconciliation"], h["extraction"]["routing"]
    pct = lambda v: "n/a" if v is None else f"{v * 100:.1f}%"  # noqa: E731
    weak = [f"{k} {pct(v)}" for k, v in e["field_accuracy"].items() if (v or 0) < 0.99]
    return "\n".join([
        title and f"### {title}"
        or f"### Held-out layout (never seen while building; {h['benchmark']['invoices']} "
        "invoices, rules only, no LLM)",
        "",
        "| Metric | Score |",
        "|---|---|",
        f"| Documents with every field correct | {pct(e['documents_fully_correct'])} |",
        f"| Error detection precision / recall | {pct(d['precision'])} / {pct(d['recall'])} |",
        f"| Clean invoices wrongly blocked | {d['clean_wrongly_blocked']} of "
        f"{d['clean_invoices']} |",
        f"| GSTR-2B reconciliation accuracy | {pct(c['accuracy'])} |",
        f"| Wrong extractions routed to LLM fallback | {rt['wrong_sent_to_llm']} of "
        f"{rt['wrong_docs']} |",
        f"| Correct extractions kept on rules | {rt['correct_kept_on_rules']} of "
        f"{rt['correct_docs']} |",
        "",
        f"Weak fields: {', '.join(weak) or 'none'}",
    ]) + "\n"  # fmt: skip


GATES = {"documents_fully_correct": 0.95, "precision": 0.95, "recall": 0.95, "recon": 0.95}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Evaluate InvoiceIQ on the synthetic benchmark")
    p.add_argument("--n", type=int, default=120)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--out", default="eval_results")
    p.add_argument("--held-out-n", type=int, default=60, help="invoices in the unseen layout")
    p.add_argument("--llm", default="", help="also score the held-out layout with this LLM")
    p.add_argument("--gate", action="store_true", help="exit 1 if a score drops below its gate")
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        r = run(Path(tmp) / "dev", a.n, a.seed, DEV_TEMPLATES)
        h = run(Path(tmp) / "held_out", a.held_out_n, a.seed + 1, HELD_OUT_TEMPLATES)
        if a.llm:
            from .extract.llm import LLMExtractor

            h_llm = run(Path(tmp) / "held_out_llm", a.held_out_n, a.seed + 1,
                        HELD_OUT_TEMPLATES, llm=LLMExtractor(a.llm))  # fmt: skip
    results = {"dev": r, "held_out": h}
    md = report_markdown(r) + "\n" + held_out_markdown(h)
    if a.llm:
        results["held_out_llm"] = h_llm
        md += "\n" + held_out_markdown(h_llm, title=f"Held-out layout with LLM fallback ({a.llm})")
    (out / "results.json").write_text(json.dumps(results, indent=2))
    (out / "report.md").write_text(md)
    print(md)
    if a.gate:
        scores = {
            "documents_fully_correct": r["extraction"]["documents_fully_correct"],
            "precision": r["detection"]["precision"],
            "recall": r["detection"]["recall"],
            "recon": r["reconciliation"]["accuracy"],
        }
        failed = [k for k, v in scores.items() if (v or 0) < GATES[k]]
        if failed:
            print(f"below gate: {', '.join(failed)}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
