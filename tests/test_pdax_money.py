"""Decimal money helpers: float noise must never leak into outbound PDAX
amount strings."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.pdax.money import format_amount, quantize, quantize_up, to_decimal


def test_format_amount_erases_float_noise():
    # The docstring's own example: 17.18 must never serialize with noise.
    assert format_amount(17.179999999999998) == "17.18"
    assert format_amount(0.1 + 0.2) == "0.3"


def test_format_amount_no_exponent_or_trailing_zeros():
    assert format_amount(1e-8) == "0.00000001"
    assert format_amount("5.500") == "5.5"
    assert format_amount(5) == "5"
    assert format_amount("0") == "0"


def test_to_decimal_rejects_garbage():
    with pytest.raises(ValueError):
        to_decimal("lots")
    assert to_decimal("1.5") == Decimal("1.5")


def test_quantize_rounds_down_to_step():
    # Never over-send: 1.239 at a 0.01 step is 1.23, not 1.24.
    assert quantize("1.239", "0.01") == Decimal("1.23")
    assert quantize("1.23456789123", "0.00000001") == Decimal("1.23456789")


def test_quantize_up_rounds_up_to_step():
    # Funding quotes round UP so the buyer always covers the target.
    assert quantize_up("101.2", "1") == Decimal("102")
    assert quantize_up("101.0", "1") == Decimal("101")


def test_quantize_nonpositive_step_is_identity():
    assert quantize("1.2345", "0") == Decimal("1.2345")
    assert quantize_up("1.2345", "-1") == Decimal("1.2345")
