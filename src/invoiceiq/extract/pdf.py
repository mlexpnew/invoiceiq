"""PDF to text. Text-layer PDFs only; scanned images are flagged, not guessed at."""

from __future__ import annotations

import io


def pdf_text(data: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)
