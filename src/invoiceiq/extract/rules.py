"""Rule-based extraction from invoice text.

Indian invoices vary in labels ("Invoice No", "Inv #", "Bill No"), date formats and
column order, but share structure: GSTINs, a tax summary and HSN-coded line items.
This extractor targets that shared structure through label synonyms rather than one
fixed template. Fields it cannot find stay empty and lower the confidence score, which
decides whether the LLM fallback runs.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from .. import gstin as G
from ..models import Invoice, LineItem

GSTIN_TOKEN = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][0-9A-Z]Z[0-9A-Z]\b")
AMOUNT = r"-?\s?(?:₹|Rs\.?|INR)?\s?-?[\d,]+\.\d{2}"
AMOUNT_RE = re.compile(AMOUNT)
BUYER_WORDS = ("bill to", "billed to", "buyer", "recipient", "ship to", "customer", "to:")
SELLER_WORDS = ("seller", "supplier", "from:", "sold by")

LABELS = {
    "invoice_no": r"(?:tax\s+)?(?:invoice|inv|bill)\s*(?:no\.?|number|#)",
    "invoice_date": (
        r"(?:invoice\s+date|bill\s+date|inv\.?\s+date|date\s+of\s+(?:invoice|issue|supply)"
        r"|dated|date)"
    ),
    "place_of_supply": r"(?:place\s+of\s+supply|pos)",
}
TOTALS = {
    "taxable_value": r"(?:taxable\s+(?:value|amount)|sub\s*total)",
    "cgst": r"cgst",
    "sgst": r"(?:sgst|utgst)",
    "igst": r"igst",
    "round_off": r"round(?:ed|ing)?\s*off(?:\s*\(\+/-\))?",
    "total": (
        r"(?:grand\s+total|invoice\s+total|total\s+invoice\s+value|invoice\s+value"
        r"|total\s+amount(?:\s*\(rs\.?\))?|total\s+payable|amount\s+payable|net\s+payable)"
    ),
}
DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d-%b-%Y", "%d %b %Y", "%Y-%m-%d", "%d %B %Y")
DATE_TOKEN = re.compile(
    r"\b(\d{1,2}[/.-]\d{1,2}[/.-]\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}[ -][A-Za-z]{3,9}[ -]\d{4})\b"
)
STATE_BY_NAME = {name.lower(): code for code, name in G.STATES.items()}

# Line item rows. Two common column orders:
#   [S.No] Description  HSN  Qty  Rate  Amount  GST%
#   [S.No] Description  HSN  Qty  Rate  GST%  Amount
_N = r"[\d,]+\.\d{2}"
_UNIT = r"(?:\s+(?:nos|pcs|kg|kgs|box|ltr|hrs|mtr|set|unit|units|ea)\.?)?"
ROW_AMOUNT_LAST = re.compile(  # unit column (Nos, Pcs, Kg...) is optional
    rf"^(?:\d{{1,3}}\s+)?(?P<desc>.+?)\s+(?P<hsn>\d{{4,8}})\s+(?P<qty>\d+(?:\.\d+)?){_UNIT}\s+"
    rf"(?P<price>{_N})\s+(?P<gst>\d{{1,2}}(?:\.\d+)?)\s?%\s+(?P<amt>{_N})$",
    re.I,
)
ROW_GST_LAST = re.compile(
    rf"^(?:\d{{1,3}}\s+)?(?P<desc>.+?)\s+(?P<hsn>\d{{4,8}})\s+(?P<qty>\d+(?:\.\d+)?){_UNIT}\s+"
    rf"(?P<price>{_N})\s+(?P<amt>{_N})\s+(?P<gst>\d{{1,2}}(?:\.\d+)?)\s?%$",
    re.I,
)


def money(s: str) -> float:
    s = s.replace("₹", "").replace("INR", "").replace("Rs.", "").replace("Rs", "")
    s = s.replace(",", "").replace(" ", "")
    return round(float(s), 2)


def parse_date(s: str) -> date | None:
    s = s.strip().replace(",", "")
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _labelled_value(lines: list[str], label: str, value: str) -> str | None:
    # (?!\w) instead of \b: labels like "Inv #" end in a symbol, where \b never matches
    pat = re.compile(rf"\b{label}(?!\w)\s*[:.#-]?\s*(?P<v>{value})", re.I)
    for line in lines:
        m = pat.search(line)
        if m:
            return m.group("v").strip()
    return None


def _assign_gstins(lines: list[str], company_gstin: str) -> tuple[str, str]:
    """Supplier vs buyer GSTIN, from nearby labels; the client's own GSTIN is the buyer."""
    found: list[tuple[str, str]] = []  # (gstin, role hint)
    for i, line in enumerate(lines):
        for g in GSTIN_TOKEN.findall(line.upper()):
            context = " ".join(lines[max(0, i - 3) : i + 1]).lower()
            same_line = line.lower()
            if any(w in same_line for w in BUYER_WORDS):
                role = "buyer"
            elif any(w in same_line for w in SELLER_WORDS):
                role = "supplier"
            elif any(w in context for w in BUYER_WORDS):
                role = "buyer"
            else:
                role = "supplier"
            if g not in (x[0] for x in found):
                found.append((g, role))
    supplier = next((g for g, r in found if r == "supplier"), "")
    buyer = next((g for g, r in found if r == "buyer"), "")
    if company_gstin and supplier == company_gstin and buyer != company_gstin:
        supplier, buyer = buyer, supplier
    if not supplier and found:
        supplier = next((g for g, _ in found if g != buyer), "")
    return supplier, buyer


def _names(lines: list[str], supplier_gstin: str, buyer_gstin: str) -> tuple[str, str]:
    supplier = next((ln.strip() for ln in lines if ln.strip()), "")
    for w in ("from:", "seller:", "supplier:"):
        for ln in lines:
            if ln.lower().startswith(w) and len(ln) > len(w) + 1:
                supplier = re.split(r"\s+GSTIN", ln[len(w) :], flags=re.I)[0].strip()
    buyer = ""
    for i, ln in enumerate(lines):
        low = ln.lower().strip()
        for w in ("bill to:", "billed to:", "buyer:", "to:"):
            if low.startswith(w):
                rest = re.split(r"\s+GSTIN", ln.strip()[len(w) :], flags=re.I)[0].strip()
                buyer = rest or (lines[i + 1].strip() if i + 1 < len(lines) else "")
                break
        if buyer:
            break
    return supplier, buyer


def _items(lines: list[str]) -> list[LineItem]:
    items = []
    for line in lines:
        s = line.strip()
        m = ROW_AMOUNT_LAST.match(s) or ROW_GST_LAST.match(s)
        if not m:
            continue
        items.append(
            LineItem(
                description=m.group("desc").strip(),
                hsn=m.group("hsn"),
                qty=float(m.group("qty")),
                unit_price=money(m.group("price")),
                taxable_value=money(m.group("amt")),
                gst_rate=float(m.group("gst")),
            )
        )
    return items


def _totals(lines: list[str]) -> dict[str, float]:
    """First amount after each label, so "CGST: 10.00  SGST: 10.00" on one line reads right."""
    out: dict[str, float] = {}
    for field, label in TOTALS.items():
        pat = re.compile(rf"(?:^|\s){label}\b(?:\s*@\s*\d+(?:\.\d+)?\s*%)?", re.I)
        for line in lines:
            if re.search(r"total\s+tax\b", line, re.I):  # "Total Tax", not "Total Taxable"
                continue
            m = pat.search(line)
            if not m or (field != "total" and _is_item_row(line)):
                continue
            amount = AMOUNT_RE.search(line, m.end())
            if amount:
                out[field] = money(amount.group())
                break
    return out


def _is_item_row(line: str) -> bool:
    s = line.strip()
    return bool(ROW_AMOUNT_LAST.match(s) or ROW_GST_LAST.match(s))


def _place_of_supply(lines: list[str]) -> str:
    raw = _labelled_value(lines, LABELS["place_of_supply"], r".+")
    if not raw:
        return ""
    m = re.search(r"\b(\d{2})\b", raw)
    if m and m.group(1) in G.STATES:
        return m.group(1)
    low = raw.lower()
    for name, code in STATE_BY_NAME.items():
        if name in low:
            return code
    return ""


REQUIRED = ("supplier_gstin", "invoice_no", "invoice_date", "taxable_value", "total")


def confidence(inv: Invoice) -> float:
    found = sum(bool(getattr(inv, f)) for f in REQUIRED) / len(REQUIRED)
    consistent = abs(inv.taxable_value + inv.total_tax + inv.round_off - inv.total) <= 1.0
    return round(found * (1.0 if consistent else 0.8), 2)


def extract(text: str, source: str = "", company_gstin: str = "") -> Invoice:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    supplier_gstin, buyer_gstin = _assign_gstins(lines, company_gstin)
    supplier_name, buyer_name = _names(lines, supplier_gstin, buyer_gstin)
    raw_date = _labelled_value(lines, LABELS["invoice_date"], DATE_TOKEN.pattern)
    inv = Invoice(
        source=source,
        supplier_name=supplier_name,
        supplier_gstin=supplier_gstin,
        buyer_name=buyer_name,
        buyer_gstin=buyer_gstin,
        place_of_supply=_place_of_supply(lines),
        invoice_no=_labelled_value(lines, LABELS["invoice_no"], r"[A-Za-z0-9/_-]+") or "",
        invoice_date=parse_date(raw_date) if raw_date else None,
        items=_items(lines),
        **_totals(lines),
    )
    inv.confidence = confidence(inv)
    return inv
