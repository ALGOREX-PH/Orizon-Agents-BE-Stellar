"""RFC 6238 conformance for the stdlib TOTP generator (SHA-1 test vectors,
Appendix B — secret is the ASCII seed "12345678901234567890")."""

from __future__ import annotations

import pytest

from app.pdax.totp import totp_now

# base32 of b"12345678901234567890"
RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"

RFC_VECTORS = [
    (59, "94287082"),
    (1111111109, "07081804"),
    (1111111111, "14050471"),
    (1234567890, "89005924"),
    (2000000000, "69279037"),
]


@pytest.mark.parametrize(("timestamp", "expected"), RFC_VECTORS)
def test_rfc6238_sha1_vectors(timestamp, expected):
    assert totp_now(RFC_SECRET, timestamp=timestamp, digits=8) == expected


def test_default_six_digits_truncates_rfc_vector():
    # 6-digit code is the 8-digit RFC value mod 10^6, zero-padded.
    assert totp_now(RFC_SECRET, timestamp=59) == "287082"


def test_deterministic_within_period():
    a = totp_now(RFC_SECRET, timestamp=60)
    b = totp_now(RFC_SECRET, timestamp=89)  # same 30s window
    c = totp_now(RFC_SECRET, timestamp=90)  # next window
    assert a == b
    assert a != c


def test_secret_normalization_spaces_case_padding():
    # Lowercase, spaced, unpadded input must resolve to the same key.
    messy = "gezd gnbv gy3t qojq gezd gnbv gy3t qojq"
    assert totp_now(messy, timestamp=59, digits=8) == "94287082"


def test_unpadded_secret_length_multiple_fixed():
    # 10-char secret (not a multiple of 8) exercises the padding helper.
    code = totp_now("GEZDGNBVGY", timestamp=59)
    assert len(code) == 6
    assert code.isdigit()
