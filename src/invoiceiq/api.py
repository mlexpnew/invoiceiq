"""HTTP API for accounting tools and internal dashboards.

    uvicorn invoiceiq.api:app --port 8000

Privacy by design: uploaded PDFs are processed in memory and never written to disk.
Set INVOICEIQ_API_KEYS (comma separated) to require an X-API-Key header.
"""

from __future__ import annotations

import base64
import os
import time
from collections import defaultdict, deque

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile

from . import __version__
from .export.excel import workbook
from .export.tally import tally_xml
from .models import Invoice, Issue, ReconRow
from .pipeline import process
from .reconcile import load_gstr2b, summarize

MAX_FILES = 200
MAX_BYTES = 10 * 1024 * 1024  # per PDF
RATE_LIMIT = int(os.getenv("INVOICEIQ_RATE_PER_MIN", "30"))

app = FastAPI(
    title="InvoiceIQ",
    version=__version__,
    description="GST purchase invoice checks and GSTR-2B reconciliation.",
)
_hits: dict[str, deque] = defaultdict(deque)


def auth(x_api_key: str = Header(default="")) -> str:
    keys = {k.strip() for k in os.getenv("INVOICEIQ_API_KEYS", "").split(",") if k.strip()}
    if keys and x_api_key not in keys:
        raise HTTPException(401, "missing or invalid X-API-Key")
    caller = x_api_key or "anonymous"
    now = time.monotonic()
    q = _hits[caller]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        raise HTTPException(429, "rate limit exceeded, retry in a minute")
    q.append(now)
    return caller


async def _read(files: list[UploadFile]) -> list[tuple[str, bytes]]:
    if not files or len(files) > MAX_FILES:
        raise HTTPException(400, f"send 1 to {MAX_FILES} PDF files")
    out = []
    for f in files:
        data = await f.read()
        if len(data) > MAX_BYTES:
            raise HTTPException(413, f"{f.filename} is larger than 10 MB")
        if not data.startswith(b"%PDF"):
            raise HTTPException(415, f"{f.filename} is not a PDF")
        out.append((f.filename or "invoice.pdf", data))
    return out


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.post("/v1/invoices/check")
async def check(
    files: list[UploadFile] = File(...),
    company_gstin: str = Form(""),
    gstr2b: UploadFile | None = File(None),
    _: str = Depends(auth),
) -> dict:
    """Extract and validate invoices; reconcile with GSTR-2B when it is attached."""
    pdfs = await _read(files)
    portal = None
    if gstr2b is not None:
        portal = load_gstr2b(await gstr2b.read(), gstr2b.filename or "")
    res = process(pdfs, company_gstin=company_gstin.strip().upper(), gstr2b=portal)
    blocked = res.blocked_sources()
    body: dict = {
        "invoices": [_inv(i, i.source in blocked) for i in res.invoices],
        "issues": [Issue.model_validate(i).model_dump(mode="json") for i in res.issues],
        "summary": {
            "invoices": len(res.invoices),
            "ready_to_post": len(res.invoices) - len(blocked),
            "blocked": len(blocked),
        },
    }
    if res.recon:
        body["reconciliation"] = {
            "rows": [ReconRow.model_validate(r).model_dump(mode="json") for r in res.recon],
            "summary": summarize(res.recon),
        }
    return body


@app.post("/v1/invoices/export")
async def export(
    files: list[UploadFile] = File(...),
    company_gstin: str = Form(""),
    company_name: str = Form("My Company"),
    gstr2b: UploadFile | None = File(None),
    _: str = Depends(auth),
) -> dict:
    """Review workbook (.xlsx) and Tally XML, base64 encoded for easy transport."""
    pdfs = await _read(files)
    portal = load_gstr2b(await gstr2b.read(), gstr2b.filename or "") if gstr2b else None
    res = process(pdfs, company_gstin=company_gstin.strip().upper(), gstr2b=portal)
    return {
        "xlsx_base64": base64.b64encode(workbook(res)).decode(),
        "tally_xml": tally_xml(res.clean(), company_name),
        "ready_to_post": len(res.clean()),
    }


def _inv(inv: Invoice, blocked: bool) -> dict:
    d = inv.model_dump(mode="json")
    d["status"] = "blocked" if blocked else "ok"
    return d
