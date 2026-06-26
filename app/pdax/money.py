"""
Decimal money helpers.

Outbound PDAX amounts (what we send: order/withdraw/deposit quantities) must
never be formatted from a binary float — `17.18` can serialize as
`17.179999999999998` and trip PDAX's step/precision validation. These helpers
keep amounts as `Decimal` and emit a clean fixed-point string.
"""
from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal, InvalidOperation

# Normalize to this precision when formatting, to erase binary-float noise
# (e.g. 17.179999999999998 → 17.18). Well below any crypto precision (8 dp).
_FORMAT_PRECISION = Decimal("1.0000000000")  # 10 dp


def to_decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as e:
        raise ValueError(f"invalid amount: {value!r}") from e


def quantize(amount: object, step: str = "0.00000001") -> Decimal:
    """Round an amount DOWN to a quantity step (never over-spend / over-send)."""
    d = to_decimal(amount)
    s = to_decimal(step)
    if s <= 0:
        return d
    return (d / s).to_integral_value(rounding=ROUND_DOWN) * s


def format_amount(amount: object) -> str:
    """Canonical fixed-point string: float noise erased, no exponent, trailing
    zeros trimmed."""
    d = to_decimal(amount).quantize(_FORMAT_PRECISION, rounding=ROUND_HALF_EVEN)
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"
