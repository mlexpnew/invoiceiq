"""GSTIN validation: format, state code and the official mod-36 check digit.

A GSTIN is 15 characters: 2-digit state code, 10-character PAN, entity number,
the letter Z, and a check digit computed over the first 14 characters.
"""

from __future__ import annotations

import re

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")

STATES: dict[str, str] = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab",
    "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana", "07": "Delhi",
    "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
    "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur", "15": "Mizoram",
    "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh",
    "24": "Gujarat", "26": "Dadra and Nagar Haveli and Daman and Diu",
    "27": "Maharashtra", "29": "Karnataka", "30": "Goa", "31": "Lakshadweep",
    "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman and Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh",
    "38": "Ladakh", "97": "Other Territory", "99": "Centre Jurisdiction",
}  # fmt: skip


def check_digit(first14: str) -> str:
    """Mod-36 check digit with alternating weights 1, 2 (GSTN specification)."""
    total = 0
    for i, ch in enumerate(first14.upper()):
        product = ALPHABET.index(ch) * (1 if i % 2 == 0 else 2)
        total += product // 36 + product % 36
    return ALPHABET[(36 - total % 36) % 36]


def problems(gstin: str | None) -> list[str]:
    """Empty list means valid. Each entry is a short reason a reviewer can act on."""
    if not gstin:
        return ["missing"]
    g = gstin.strip().upper()
    if not GSTIN_RE.match(g):
        return ["format: expected 2 digits + PAN + entity + Z + check digit"]
    out = []
    if g[:2] not in STATES:
        out.append(f"unknown state code {g[:2]}")
    if check_digit(g[:14]) != g[14]:
        out.append(f"check digit should be {check_digit(g[:14])}, found {g[14]}")
    return out


def is_valid(gstin: str | None) -> bool:
    return not problems(gstin)


def state_code(gstin: str | None) -> str | None:
    return gstin[:2] if gstin and len(gstin) >= 2 and gstin[:2].isdigit() else None


def pan(gstin: str) -> str:
    return gstin[2:12]


def make(state: str, pan_: str, entity: str = "1") -> str:
    """Build a valid GSTIN (used by the synthetic data generator and tests)."""
    body = f"{state}{pan_.upper()}{entity}Z"
    return body + check_digit(body)
