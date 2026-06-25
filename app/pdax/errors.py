"""
PDAX error handling.

`PdaxError` wraps any non-2xx response (or a documented error envelope) from
the PDAX API. The raw `code`, `name`, `message`, and `request_id` are kept so
the router can surface them to the frontend; `http_status` is the upstream
status PDAX returned. ERROR_CODES is the documented reference table.
"""
from __future__ import annotations

from typing import Any


class PdaxError(Exception):
    """A typed error raised for any failed PDAX API call."""

    def __init__(
        self,
        message: str,
        *,
        code: str | int | None = None,
        name: str | None = None,
        http_status: int | None = None,
        request_id: str | None = None,
        raw: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.name = name
        self.http_status = http_status
        self.request_id = request_id
        self.raw = raw

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "message": self.message,
            "http_status": self.http_status,
            "request_id": self.request_id,
        }

    def __str__(self) -> str:
        bits = [self.message]
        if self.code is not None:
            bits.append(f"code={self.code}")
        if self.http_status is not None:
            bits.append(f"http={self.http_status}")
        return " ".join(bits)


# Documented PDAX error codes (OTC + Payment + auth). Reference only —
# the live `message` from the API is always preferred when present.
ERROR_CODES: dict[str, str] = {
    # ── Auth ──
    "InvalidCredentials": "Incorrect username or password.",
    "AccountLocked": "Account is locked.",
    "ExpiredTemporaryPassword": "Temporary password has expired.",
    "InvalidMfaCode": "Invalid MFA session or OTP code.",
    "NotAuthorizedException": "Invalid or mismatched refresh token.",
    "BadRequestException": "Malformed request body.",
    # ── OTC / Trade ──
    "OT000000": "Something went wrong.",
    "OT010003": "Resource cannot be found or has been expired.",
    "OT010006": "Insufficient balance.",
    "OT010008": "Cannot hold specified amounts.",
    "OT010016": "Asset unavailable.",
    "OT010019": "Minimum quantity limit reached.",
    "OT010020": "Maximum quantity limit reached.",
    "OT010022": "Withdrawal limit reached.",
    "OT010026": "Malformed parameters.",
    "OT010027": "Order quantity is less than minimum required quantity.",
    "OT010028": "Order quantity is greater than maximum required quantity.",
    "OT010029": "Invalid quantity step.",
    "OT010030": "Invalid price step.",
    "ServerError": "Server error (duplicate request or invalid idempotency id).",
    # ── Payments (fiat) ──
    "PAP0001": "Transaction identifier already exists.",
    "PAP0002": "Field validation error.",
    "PAP0004": "Travel-rule data required for amounts ≥ 50,000 PHP.",
    "PAP0007": "Amount exceeds the allowed limit.",
    "PAP0010": "Bank code is invalid or not supported.",
    "PAP0012": "Payment method is not supported.",
    "PAP0013": "Insufficient balance to complete transaction.",
    "PAP0400": "Bad request.",
    "PAP0401": "Unauthorized.",
    "PAP0500": "Internal server error.",
    "PAP0503": "Service unavailable.",
    "FailedRetrievingWallet": "Failed retrieving wallet for the currency.",
    "FeeCalculatorError": "Amount is outside the allowed fee limits.",
    "LimitsValidationError": "Transaction limit exceeded.",
}
