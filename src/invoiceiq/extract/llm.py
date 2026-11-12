"""LLM fallback for layouts the rules miss.

Runs only when rule confidence is below a threshold, and only fills fields the rules left
empty: a figure read correctly by a regex is never overwritten by a model guess. Every
LLM-filled invoice still goes through the same validation, so a hallucinated total shows
up as a TOTAL_MATH error instead of silently entering the books.

Any OpenAI-compatible endpoint works; presets cover Groq, Gemini, OpenRouter and Ollama.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable

from ..models import Invoice, LineItem
from .rules import confidence, parse_date

PRESETS = {
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "llama-3.3-70b-versatile"),
    "gemini": (
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "GEMINI_API_KEY",
        "gemini-2.5-flash",
    ),
    "openrouter": (
        "https://openrouter.ai/api/v1",
        "OPENROUTER_API_KEY",
        "meta-llama/llama-3.3-70b-instruct",
    ),
    "ollama": ("http://localhost:11434/v1", None, "qwen2.5:7b-instruct"),
}

PROMPT = """You extract data from an Indian GST tax invoice. Use only text that appears in the
invoice. If a field is absent, use "" or 0. Never compute or guess numbers.

Return ONLY a JSON object with keys:
supplier_name, supplier_gstin, buyer_name, buyer_gstin, place_of_supply (2-digit state code),
invoice_no, invoice_date (YYYY-MM-DD), taxable_value, cgst, sgst, igst, round_off, total,
items: [{{description, hsn, qty, unit_price, taxable_value, gst_rate}}]

INVOICE TEXT:
{text}
"""


class LLMExtractor:
    def __init__(
        self,
        provider: str = "groq",
        model: str | None = None,
        post: Callable[[str, dict, dict], dict] | None = None,
    ) -> None:
        base, key_env, default_model = PRESETS[provider]
        key = os.getenv(key_env) if key_env else None
        if key_env and not key:
            raise RuntimeError(f"{key_env} is not set")
        self.url = base + "/chat/completions"
        self.headers = {"Content-Type": "application/json"}
        if key:
            self.headers["Authorization"] = f"Bearer {key}"
        self.model = model or default_model
        self._post = post or _post

    def fields(self, text: str) -> dict:
        body = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": PROMPT.format(text=text[:12000])}],
        }
        data = self._post(self.url, self.headers, body)
        return json.loads(data["choices"][0]["message"]["content"])


def _post(url: str, headers: dict, body: dict) -> dict:
    import requests

    resp = requests.post(url, headers=headers, json=body, timeout=60)
    resp.raise_for_status()
    return resp.json()


def _num(v) -> float:
    try:
        return round(float(str(v).replace(",", "")), 2)
    except (TypeError, ValueError):
        return 0.0


def merge(inv: Invoice, llm_fields: dict) -> Invoice:
    """Fill only what the rules left empty; keep provenance in `extractor`."""
    filled = 0
    for key in ("supplier_name", "supplier_gstin", "buyer_name", "buyer_gstin",
                "place_of_supply", "invoice_no"):  # fmt: skip
        if not getattr(inv, key) and llm_fields.get(key):
            setattr(inv, key, str(llm_fields[key]).strip().upper() if "gstin" in key
                    else str(llm_fields[key]).strip())  # fmt: skip
            filled += 1
    if not inv.invoice_date and llm_fields.get("invoice_date"):
        inv.invoice_date = parse_date(str(llm_fields["invoice_date"]))
        filled += bool(inv.invoice_date)
    for key in ("taxable_value", "cgst", "sgst", "igst", "round_off", "total"):
        if not getattr(inv, key) and _num(llm_fields.get(key)):
            setattr(inv, key, _num(llm_fields[key]))
            filled += 1
    if not inv.items and llm_fields.get("items"):
        inv.items = [
            LineItem(
                description=str(it.get("description", "")),
                hsn=str(it.get("hsn", "")),
                qty=_num(it.get("qty")) or 1.0,
                unit_price=_num(it.get("unit_price")),
                taxable_value=_num(it.get("taxable_value")),
                gst_rate=_num(it.get("gst_rate")),
            )
            for it in llm_fields["items"]
            if isinstance(it, dict)
        ]
        filled += 1
    if filled:
        inv.extractor = "rules+llm"
    inv.confidence = confidence(inv)
    return inv
