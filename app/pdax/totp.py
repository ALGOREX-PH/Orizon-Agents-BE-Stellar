"""
Minimal RFC 6238 TOTP generator (stdlib only).

Used to answer a PDAX SOFTWARE_TOKEN_MFA challenge automatically when
`PDAX_OTP_SECRET` (the base32 seed) is configured. No third-party dependency.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import struct


def totp_now(secret_base32: str, *, timestamp: int, period: int = 30, digits: int = 6) -> str:
    """Compute the TOTP code for `timestamp` (seconds). Caller passes the time
    explicitly so the value is deterministic and testable."""
    key = base64.b32decode(_pad(secret_base32.strip().replace(" ", "").upper()))
    counter = int(timestamp // period)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % (
        10**digits
    )
    return str(code_int).zfill(digits)


def _pad(secret: str) -> str:
    """Base32 requires the input length to be a multiple of 8."""
    remainder = len(secret) % 8
    return secret + ("=" * (8 - remainder)) if remainder else secret
