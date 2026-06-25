"""
PDAX withdrawal models — fiat withdraw, user-info upload, and crypto out.

Fiat withdrawals route through a bank/e-wallet (`beneficiary_bank_code`) using
PAY-TO-ACCOUNT-REAL-TIME or NON-REAL-TIME; PDAX picks the channel and reports
attempts in `retry_methods`. Crypto out sends a token to an external address;
amounts ≥ 50,000 PHP require beneficiary VASP data (travel rule).
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class FiatWithdrawRequest(BaseModel):
    """Body for POST /v1/fiat/withdraw."""

    identifier: str
    amount: str
    currency: str = Field("PHP", description="PHP only")
    method: str = Field(..., description="PAY-TO-ACCOUNT-REAL-TIME | -NON-REAL-TIME")
    fee_type: str = Field(..., description="Sender | Beneficiary")

    # Sender
    sender_first_name: str
    sender_middle_name: str = "n.a."
    sender_last_name: str
    sender_country_origin: str
    sender_address_line_one: str | None = None
    sender_address_line_two: str | None = None
    sender_city: str | None = None
    sender_province: str | None = None
    sender_country: str | None = None
    sender_zip_code: str | None = None
    sender_phone_number: str | None = None
    sender_nationality: str | None = None
    sender_national_identity_number: str | None = None
    sender_dob: str | None = None
    sender_place_of_birth: str | None = None
    source_of_funds: str
    sender_email: str | None = None

    # Beneficiary
    beneficiary_first_name: str
    beneficiary_middle_name: str = "n.a."
    beneficiary_last_name: str
    beneficiary_sex: str | None = None
    beneficiary_nationality: str | None = None
    beneficiary_dob: str | None = None
    beneficiary_bank_code: str
    beneficiary_account_name: str
    beneficiary_account_number: str
    beneficiary_address_line_one: str | None = None
    beneficiary_address_line_two: str | None = None
    beneficiary_barangay: str | None = None
    beneficiary_city: str | None = None
    beneficiary_province: str | None = None
    beneficiary_country: str | None = None
    beneficiary_zip_code: str | None = None
    beneficiary_government_issued_id: str | None = None
    beneficiary_phone_number: str | None = None

    purpose: str
    relationship_of_sender_to_beneficiary: str
    nature_of_business: str | None = None
    instructions: str | None = None


class RetryMethod(BaseModel):
    """One attempted payment channel within a fiat withdrawal."""

    request_id: str
    channel: str
    status: str
    fail_reason: str = ""
    time: str | None = None


class FiatWithdrawResult(BaseModel):
    """Response from POST /v1/fiat/withdraw."""

    request_id: str | None = None
    identifier: str
    reference_number: str | None = None
    amount: float
    method: str
    retry_methods: list[RetryMethod] = Field(default_factory=list)
    status: str = "PENDING"
    fee: float = 0


class CryptoOutRequest(BaseModel):
    """Body for POST /v1/crypto/withdraw."""

    identifier: str
    currency: str = Field(..., description="Token symbol, e.g. USDCXLM")
    amount: str
    address: str
    tag: str | None = ""
    beneficiary_first_name: str | None = None
    beneficiary_last_name: str | None = None
    beneficiary_exchange: str | None = None
    send_to_self: str | None = "false"
    beneficiary_wallet: str | None = "false"


class CryptoOutResult(BaseModel):
    """Response from POST /v1/crypto/withdraw."""

    identifier: str
    transaction_id: int
    transaction_hash: str = ""
    amount: str
    address: str
    tag: str | None = None
    total: str
    fee: str
    currency: str
    status: str = "IN PROGRESS"
    created_at: str | None = None
