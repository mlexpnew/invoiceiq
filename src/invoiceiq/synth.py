"""Synthetic benchmark: realistic GST invoice PDFs with known answers.

Real client invoices cannot be published, so the benchmark generates PDFs from three
vendor layouts (different labels, date formats, column orders and tax presentation),
injects the errors accountants actually find, and records the ground truth. Matching
GSTR-2B data is generated with the gaps a real portal shows: unfiled invoices, value
differences, ITC marked unavailable, and purchases missing from the books.

    python -m invoiceiq.synth --n 120 --out bench/
"""

from __future__ import annotations

import argparse
import io
import json
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from . import gstin as G

COMPANY = ("Nimbus Retail Private Limited", G.make("29", "AACCN4821K"))
TODAY = date(2026, 11, 12)  # fixed so ITC deadline checks are reproducible

SUPPLIERS = [
    ("Sahyadri Office Supplies", "29", "AAFCS1132M"),
    ("Kaveri Electronics LLP", "29", "AALFK5520Q"),
    ("Bluepeak Logistics Pvt Ltd", "29", "AADCB7741R"),
    ("Deccan Packaging Co", "29", "AAKFD3309L"),
    ("Mandovi Facility Services", "29", "AAJFM6618B"),
    ("Western Ghats Furniture", "27", "AAGFW2245N"),
    ("Konkan Print House", "27", "AAPFK9013C"),
    ("Marina Tech Distributors", "33", "AAHCM4456D"),
    ("Coromandel Beverages Ltd", "33", "AABCC8802E"),
    ("Yamuna Stationery Mart", "07", "AAIFY1178F"),
    ("Charminar IT Solutions", "36", "AACCC3390G"),
    ("Sabarmati Textiles", "24", "AAEFS5561H"),
]
CATALOG = [  # description, HSN/SAC, price range, GST % (GST 2.0 slabs)
    ("Laptop 14in i5", "8471", (42000, 68000), 18.0),
    ("LED Monitor 24in", "8528", (8500, 14000), 18.0),
    ("Office Chair Mesh", "9401", (4200, 9800), 18.0),
    ("Copier Paper A4 Ream", "4802", (240, 320), 5.0),
    ("Courier Services", "996812", (800, 4500), 18.0),
    ("Corrugated Boxes Pack", "4819", (900, 2400), 5.0),
    ("Housekeeping Services", "998533", (12000, 30000), 18.0),
    ("Aerated Drinks Case", "2202", (480, 720), 40.0),
    ("Cotton Uniform Set", "6203", (650, 980), 5.0),
    ("Printer Toner Cartridge", "8443", (2100, 4600), 18.0),
    ("Annual Software Licence", "997331", (18000, 56000), 18.0),
    ("Whiteboard Markers Box", "9608", (180, 360), 18.0),
]

FAULTS = {
    "gstin_checksum": {"GSTIN_INVALID"},
    "line_math": {"LINE_MATH"},
    "tax_math": {"TAX_MATH"},
    "total_math": {"TOTAL_MATH"},
    "tax_type": {"TAX_TYPE"},
    "retired_rate": {"RATE_RETIRED"},
    "buyer_mismatch": {"BUYER_MISMATCH"},
    "long_invoice_no": {"INVOICE_NO_FORMAT"},
    "itc_lapsed": {"ITC_LAPSED"},
    "duplicate": {"DUPLICATE"},
    "possible_duplicate": {"POSSIBLE_DUPLICATE"},
}


@dataclass
class Item:
    desc: str
    hsn: str
    qty: int
    price: float
    rate: float
    amount: float  # taxable value as printed


@dataclass
class Doc:
    file: str
    template: str
    supplier: tuple[str, str]  # name, gstin
    buyer: tuple[str, str]
    pos: str
    invoice_no: str
    invoice_date: date
    items: list[Item]
    taxable: float
    cgst: float
    sgst: float
    igst: float
    round_off: float
    total: float
    fault: str = ""
    expected_issues: set[str] = field(default_factory=set)

    def truth(self) -> dict:
        return {
            "file": self.file,
            "template": self.template,
            "fault": self.fault,
            "expected_issues": sorted(self.expected_issues),
            "supplier_gstin": self.supplier[1],
            "buyer_gstin": self.buyer[1],
            "invoice_no": self.invoice_no,
            "invoice_date": self.invoice_date.isoformat(),
            "place_of_supply": self.pos,
            "taxable_value": self.taxable,
            "cgst": self.cgst,
            "sgst": self.sgst,
            "igst": self.igst,
            "total": self.total,
            "n_items": len(self.items),
        }


def _totals(items: list[Item], intra: bool) -> tuple[float, float, float, float, float, float]:
    taxable = round(sum(i.amount for i in items), 2)
    tax = sum(i.amount * i.rate / 100 for i in items)
    if intra:
        cgst = sgst = round(tax / 2, 2)
        igst = 0.0
    else:
        cgst = sgst = 0.0
        igst = round(tax, 2)
    raw = taxable + cgst + sgst + igst
    total = float(round(raw))
    return taxable, cgst, sgst, igst, round(total - raw, 2), total


def _new_doc(rng: random.Random, idx: int, template: str) -> Doc:
    name, state, pan = rng.choice(SUPPLIERS)
    supplier = (name, G.make(state, pan))
    items = []
    for desc, hsn, (lo, hi), rate in rng.sample(CATALOG, rng.randint(1, 4)):
        qty = rng.randint(1, 12)
        price = round(rng.uniform(lo, hi), 2)
        items.append(Item(desc, hsn, qty, price, rate, round(qty * price, 2)))
    intra = state == "29"
    taxable, cgst, sgst, igst, ro, total = _totals(items, intra)
    prefix = "".join(w[0] for w in name.split()[:2]).upper()
    d = date(2026, 4, 1) + timedelta(days=rng.randint(0, 200))
    return Doc(
        file=f"inv_{idx:04d}.pdf", template=template, supplier=supplier, buyer=COMPANY,
        pos="29", invoice_no=f"{prefix}/{rng.randint(1, 9999):04d}/26-27", invoice_date=d,
        items=items, taxable=taxable, cgst=cgst, sgst=sgst, igst=igst, round_off=ro, total=total,
    )  # fmt: skip


def _inject(doc: Doc, fault: str, rng: random.Random, pool: list[Doc]) -> Doc:
    doc.fault, doc.expected_issues = fault, set(FAULTS[fault])
    intra = doc.supplier[1][:2] == doc.pos
    if fault == "gstin_checksum":
        g = doc.supplier[1]
        bad = next(c for c in G.ALPHABET if c != g[14])
        doc.supplier = (doc.supplier[0], g[:14] + bad)
    elif fault == "line_math":
        it = doc.items[0]
        it.price = round(it.price * 1.07, 2)  # printed rate no longer explains the amount
        if it.qty == 1:
            it.qty = 2
            it.price = round(it.amount / 2 * 1.07, 2)
    elif fault == "tax_math":
        bump = round(max(50.0, doc.taxable * 0.02), 2)  # overcharged tax, totals consistent
        if intra:
            doc.cgst = round(doc.cgst + bump / 2, 2)
            doc.sgst = round(doc.sgst + bump / 2, 2)
        else:
            doc.igst = round(doc.igst + bump, 2)
        raw = doc.taxable + doc.cgst + doc.sgst + doc.igst
        doc.total = float(round(raw))
        doc.round_off = round(doc.total - raw, 2)
    elif fault == "total_math":
        doc.total = doc.total + 500
    elif fault == "tax_type":
        if intra:  # charge IGST on an intra-state supply
            doc.igst, doc.cgst, doc.sgst = round(doc.cgst + doc.sgst, 2), 0.0, 0.0
        else:  # charge CGST + SGST on an inter-state supply
            half = round(doc.igst / 2, 2)
            doc.cgst = doc.sgst = half
            doc.igst = 0.0
            raw = doc.taxable + doc.cgst + doc.sgst
            doc.total = float(round(raw))
            doc.round_off = round(doc.total - raw, 2)
    elif fault == "retired_rate":
        doc.items[0].rate = 12.0
        _recompute(doc, intra)
    elif fault == "buyer_mismatch":
        doc.buyer = ("Nimbus Retail Private Limited", G.make("29", "AACCN9999Z"))
    elif fault == "long_invoice_no":
        doc.invoice_no = f"{doc.invoice_no}/BRANCH-KA-EAST"
    elif fault == "itc_lapsed":
        doc.invoice_date = date(2025, 2, 10) + timedelta(days=rng.randint(0, 40))
        doc.invoice_no = doc.invoice_no.replace("26-27", "24-25")
    return doc


def _recompute(doc: Doc, intra: bool) -> None:
    doc.taxable, doc.cgst, doc.sgst, doc.igst, doc.round_off, doc.total = _totals(doc.items, intra)


def _copy_as(doc: Doc, file: str, invoice_no: str, fault: str) -> Doc:
    import copy

    d = copy.deepcopy(doc)
    d.file, d.invoice_no, d.fault, d.expected_issues = file, invoice_no, fault, set(FAULTS[fault])
    return d


# "ledger" was the first held-out layout. It exposed generic gaps (see README, error
# analysis), so after fixing them it joined the dev set and "einvoice" became the new
# held-out layout, written before any extractor run against it.
DEV_TEMPLATES = ["classic", "modern", "compact", "ledger"]
HELD_OUT_TEMPLATES = ["einvoice"]


def generate(
    n: int = 120, seed: int = 7, fault_rate: float = 0.35, templates: list[str] | None = None
) -> list[Doc]:
    rng = random.Random(seed)
    templates = templates or DEV_TEMPLATES
    docs: list[Doc] = []
    simple = [f for f in FAULTS if f not in ("duplicate", "possible_duplicate")]
    for idx in range(1, n + 1):
        doc = _new_doc(rng, idx, templates[idx % len(templates)])
        clean_pool = [d for d in docs if not d.fault]
        roll = rng.random()
        if roll < fault_rate * 0.15 and clean_pool:  # exact duplicate, reformatted number
            src = rng.choice(clean_pool)
            no = src.invoice_no.replace("/", "-").lower()
            doc = _copy_as(src, f"inv_{idx:04d}.pdf", no, "duplicate")
            doc.template = templates[idx % len(templates)]
        elif roll < fault_rate * 0.25 and clean_pool:  # re-issued under a new number
            src = rng.choice(clean_pool)
            no = src.invoice_no.split("/")[0] + f"/{rng.randint(1, 9999):04d}/26-27"
            doc = _copy_as(src, f"inv_{idx:04d}.pdf", no, "possible_duplicate")
        elif roll < fault_rate:
            doc = _inject(doc, rng.choice(simple), rng, docs)
        docs.append(doc)
    return docs


# --- PDF rendering -------------------------------------------------------------------


def _money(x: float) -> str:
    return f"{x:,.2f}"


def render(doc: Doc) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = [800]

    def line(text: str, x: int = 40, size: int = 10, bold: bool = False, gap: int = 15):
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(x, y[0], text)
        y[0] -= gap

    def row(cols: list[tuple[int, str]], bold: bool = False):
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 9)
        for x, t in cols:
            c.drawString(x, y[0], t)
        y[0] -= 14

    sname, sg = doc.supplier
    bname, bg = doc.buyer
    state_name = G.STATES[doc.pos]
    t = doc.template
    if t == "classic":
        line(sname, size=14, bold=True, gap=18)
        line("No. 42, Industrial Area, Phase 2")
        line(f"GSTIN: {sg}", gap=22)
        line("TAX INVOICE", size=12, bold=True, gap=20)
        line(f"Invoice No: {doc.invoice_no}")
        line(f"Invoice Date: {doc.invoice_date:%d/%m/%Y}", gap=20)
        line("Bill To:", bold=True)
        line(bname)
        line(f"GSTIN: {bg}")
        line(f"Place of Supply: {state_name} ({doc.pos})", gap=22)
        row([(40, "Description"), (230, "HSN"), (290, "Qty"), (330, "Rate"),
             (420, "Amount"), (500, "GST%")], bold=True)  # fmt: skip
        for it in doc.items:
            row([(40, it.desc), (230, it.hsn), (290, str(it.qty)), (330, _money(it.price)),
                 (420, _money(it.amount)), (500, f"{it.rate:g}%")])  # fmt: skip
        y[0] -= 10
        line(f"Taxable Value   {_money(doc.taxable)}", x=330)
        if doc.igst:
            line(f"IGST   {_money(doc.igst)}", x=330)
        if doc.cgst or doc.sgst:
            line(f"CGST   {_money(doc.cgst)}", x=330)
            line(f"SGST   {_money(doc.sgst)}", x=330)
        line(f"Round Off   {_money(doc.round_off)}", x=330)
        line(f"Grand Total   Rs. {_money(doc.total)}", x=330, bold=True)
    elif t == "modern":
        line("TAX INVOICE", size=16, bold=True, gap=22)
        line(f"Seller: {sname}")
        line(f"Seller GSTIN {sg}", gap=20)
        line(f"Inv #: {doc.invoice_no}")
        line(f"Dated: {doc.invoice_date:%d-%b-%Y}", gap=20)
        line(f"Buyer: {bname}")
        line(f"Buyer GSTIN {bg}")
        line(f"POS: {doc.pos}-{state_name}", gap=22)
        row([(40, "S.No"), (75, "Item"), (250, "HSN/SAC"), (310, "Qty"), (345, "Price"),
             (430, "GST%"), (480, "Amount")], bold=True)  # fmt: skip
        for n, it in enumerate(doc.items, 1):
            row([(40, str(n)), (75, it.desc), (250, it.hsn), (310, str(it.qty)),
                 (345, _money(it.price)), (430, f"{it.rate:g}%"),
                 (480, _money(it.amount))])  # fmt: skip
        y[0] -= 10
        line(f"Sub Total {_money(doc.taxable)}", x=345)
        for lab, v in (("CGST", doc.cgst), ("SGST", doc.sgst), ("IGST", doc.igst)):
            if v:
                line(f"{lab} {_money(v)}", x=345)
        if doc.round_off:
            line(f"Rounding Off {_money(doc.round_off)}", x=345)
        line(f"Total Amount (Rs.) {_money(doc.total)}", x=345, bold=True)
    elif t == "ledger":  # held-out layout: typical of Tally-printed invoices
        line(f"M/s {sname}", size=13, bold=True, gap=18)
        line(f"GST No: {sg}", gap=20)
        line("TAX INVOICE  (Original for Recipient)", bold=True, gap=18)
        line(f"Invoice Number : {doc.invoice_no}")
        line(f"Date of Invoice : {doc.invoice_date:%d %B %Y}")
        line(f"Place of Supply : {doc.pos} - {state_name}", gap=20)
        line("Details of Receiver (Billed to)", bold=True)
        line(f"Name : {bname}")
        line(f"GST No: {bg}", gap=20)
        row([(40, "Sr"), (60, "Description of Goods"), (230, "HSN"), (285, "Qty"), (315, "Unit"),
             (350, "Rate"), (420, "Taxable Value"), (510, "GST Rate")], bold=True)  # fmt: skip
        for n, it in enumerate(doc.items, 1):
            row([(40, str(n)), (60, it.desc), (230, it.hsn), (285, str(it.qty)), (315, "Nos"),
                 (350, _money(it.price)), (420, _money(it.amount)),
                 (510, f"{it.rate:g}%")])  # fmt: skip
        y[0] -= 10
        line(f"Total Taxable Value   {_money(doc.taxable)}", x=330)
        for lab, v in (("CGST", doc.cgst), ("SGST", doc.sgst), ("IGST", doc.igst)):
            if v:
                line(f"Add: {lab}   {_money(v)}", x=330)
        line(f"Rounded Off (+/-)   {_money(doc.round_off)}", x=330)
        line(f"Total Invoice Value   {_money(doc.total)}", x=330, bold=True)
    elif t == "einvoice":  # held-out: modelled on the GST e-invoice (IRN) print format
        irn = f"{abs(hash((doc.file, doc.invoice_no))):x}".ljust(64, "a")[:64]
        line("e-Invoice", size=14, bold=True, gap=18)
        line(f"IRN: {irn}", size=7)
        line(f"Ack No.: 1126{abs(hash(doc.file)) % 10**11:011d}   Ack Date: "
             f"{doc.invoice_date:%d/%m/%Y}", size=8, gap=18)  # fmt: skip
        line("1. e-Invoice Details", bold=True)
        line(f"Document Type: Tax Invoice   Document No.: {doc.invoice_no}")
        line(f"Document Date: {doc.invoice_date:%d/%m/%Y}", gap=18)
        line("2. Party Details", bold=True)
        line(f"Supplier: {sname}")
        line(f"Supplier GSTIN: {sg}")
        line(f"Recipient: {bname}")
        line(f"Recipient GSTIN: {bg}")
        line(f"Place of Supply: {state_name.upper()}", gap=18)
        line("3. Details of Goods / Services", bold=True)
        row([(40, "SlNo"), (68, "Item Description"), (215, "HSN Code"), (270, "Quantity"),
             (315, "Unit"), (345, "Unit Price(Rs)"), (420, "Taxable Amount(Rs)"),
             (510, "Tax Rate")], bold=True)  # fmt: skip
        for n, it in enumerate(doc.items, 1):
            row([(40, str(n)), (68, it.desc), (215, it.hsn), (270, f"{it.qty:.2f}"), (315, "NOS"),
                 (345, _money(it.price)), (420, _money(it.amount)),
                 (510, f"{it.rate:g}")])  # fmt: skip
        y[0] -= 10
        line(f"Tax'ble Amt: {_money(doc.taxable)}", x=300)
        line(f"CGST Amt: {_money(doc.cgst)}   SGST Amt: {_money(doc.sgst)}", x=300)
        line(f"IGST Amt: {_money(doc.igst)}", x=300)
        line(f"Rnd. off Amt: {_money(doc.round_off)}", x=300)
        line(f"Tot Inv. Amt: {_money(doc.total)}", x=300, bold=True)
    else:  # compact
        line(f"From: {sname} GSTIN {sg}", bold=True)
        line(f"To: {bname} GSTIN {bg}", gap=20)
        line(f"Bill No. {doc.invoice_no}   Date {doc.invoice_date:%Y-%m-%d}")
        line(f"Place of Supply: {state_name}", gap=20)
        row([(40, "Particulars"), (230, "HSN"), (290, "Qty"), (330, "Rate"),
             (420, "Value"), (500, "Tax")], bold=True)  # fmt: skip
        for it in doc.items:
            row([(40, it.desc), (230, it.hsn), (290, str(it.qty)), (330, _money(it.price)),
                 (420, _money(it.amount)), (500, f"{it.rate:g}%")])  # fmt: skip
        y[0] -= 10
        line(f"Taxable Amount: {_money(doc.taxable)}", x=330)
        line(f"CGST: {_money(doc.cgst)}  SGST: {_money(doc.sgst)}", x=330)
        line(f"IGST: {_money(doc.igst)}", x=330)
        line(f"Round Off: {_money(doc.round_off)}", x=330)
        line(f"Invoice Total: {_money(doc.total)}", x=330, bold=True)
    line("This is a computer generated invoice.", y and 40, size=8)
    c.showPage()
    c.save()
    return buf.getvalue()


# --- GSTR-2B with realistic gaps -----------------------------------------------------


def gstr2b(docs: list[Doc], seed: int = 11) -> tuple[dict, dict[str, str]]:
    """Portal-style GSTR-2B JSON plus the expected reconciliation status per invoice."""
    rng = random.Random(seed)
    expected: dict[str, str] = {}
    by_supplier: dict[str, list] = {}
    names = {}
    for d in docs:
        if d.fault == "duplicate":
            continue  # a duplicate is excluded from the books before reconciliation
        key = f"{d.supplier[1]}|{d.invoice_no}"
        names[d.supplier[1]] = d.supplier[0]
        roll = rng.random()
        if roll < 0.10:
            expected[key] = "missing_in_2b"
            continue
        tax_scale, itcavl, status = 1.0, "Y", "matched"
        if roll < 0.16:
            tax_scale, status = 0.85, "value_mismatch"
        elif roll < 0.21:
            itcavl, status = "N", "itc_unavailable"
        expected[key] = status
        inum = d.invoice_no
        if rng.random() < 0.3:  # portal formatting differs from the printed number
            inum = inum.replace("/", "-")
        by_supplier.setdefault(d.supplier[1], []).append(_inv_json(d, inum, tax_scale, itcavl))
    for _ in range(6):  # purchases on the portal that never reached the books
        name, state, pan = rng.choice(SUPPLIERS)
        g = G.make(state, pan)
        no = f"EXT/{rng.randint(1, 9999):04d}/26-27"
        expected[f"{g}|{no}"] = "missing_in_books"
        names[g] = name
        taxable = round(rng.uniform(2000, 40000), 2)
        tax = round(taxable * 0.18, 2)
        by_supplier.setdefault(g, []).append({
            "inum": no, "dt": "15-09-2026", "val": round(taxable + tax, 2), "itcavl": "Y",
            "items": [{"num": 1, "rt": 18, "txval": taxable, "igst": tax, "cgst": 0, "sgst": 0}],
        })  # fmt: skip
    data = {
        "data": {
            "gstin": COMPANY[1],
            "rtnprd": "102026",
            "docdata": {
                "b2b": [
                    {"ctin": g, "trdnm": names[g], "inv": invs}
                    for g, invs in by_supplier.items()
                ]
            },
        }
    }
    return data, expected


def _inv_json(d: Doc, inum: str, tax_scale: float, itcavl: str) -> dict:
    return {
        "inum": inum,
        "dt": f"{d.invoice_date:%d-%m-%Y}",
        "val": d.total,
        "pos": d.pos,
        "itcavl": itcavl,
        "items": [{
            "num": 1, "rt": 18, "txval": d.taxable,
            "igst": round(d.igst * tax_scale, 2),
            "cgst": round(d.cgst * tax_scale, 2),
            "sgst": round(d.sgst * tax_scale, 2),
        }],
    }  # fmt: skip


def write_benchmark(
    out: Path, n: int = 120, seed: int = 7, templates: list[str] | None = None
) -> list[Doc]:
    out.mkdir(parents=True, exist_ok=True)
    (out / "pdf").mkdir(exist_ok=True)
    docs = generate(n, seed, templates=templates)
    for d in docs:
        (out / "pdf" / d.file).write_bytes(render(d))
    (out / "truth.jsonl").write_text("".join(json.dumps(d.truth()) + "\n" for d in docs))
    data, expected = gstr2b(docs)
    (out / "gstr2b.json").write_text(json.dumps(data, indent=1))
    (out / "recon_truth.json").write_text(json.dumps(expected, indent=1))
    return docs


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Generate the InvoiceIQ synthetic benchmark")
    p.add_argument("--n", type=int, default=120)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--out", default="bench")
    a = p.parse_args(argv)
    docs = write_benchmark(Path(a.out), a.n, a.seed)
    print(f"wrote {len(docs)} invoices to {a.out}/pdf")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
