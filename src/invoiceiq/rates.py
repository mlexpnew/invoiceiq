"""GST rate regimes.

GST 2.0 (effective 22 Sep 2025) moved most goods to two slabs, 5% and 18%, with 40% for
luxury and sin goods. 12% and 28% were folded in, though a few items (for example tobacco,
until compensation cess ends) still carry 28%. So an old slab on a new invoice is a
warning for review, not an automatic error.
"""

from __future__ import annotations

from datetime import date

GST2_EFFECTIVE = date(2025, 9, 22)

# Special rates that exist in both regimes: nil, rough diamonds, gold/silver, etc.
SPECIAL = {0.0, 0.1, 0.25, 1.5, 3.0}
LEGACY = SPECIAL | {5.0, 12.0, 18.0, 28.0}
GST2 = SPECIAL | {5.0, 18.0, 40.0}
RETIRED_IN_GST2 = {12.0, 28.0}


def check_rate(rate: float, on: date | None) -> str | None:
    """Return 'invalid', 'retired' or None (fine) for a rate on an invoice date."""
    r = round(float(rate), 2)
    if on is None or on < GST2_EFFECTIVE:
        return None if r in LEGACY else "invalid"
    if r in GST2:
        return None
    if r in RETIRED_IN_GST2:
        return "retired"
    return "invalid"
