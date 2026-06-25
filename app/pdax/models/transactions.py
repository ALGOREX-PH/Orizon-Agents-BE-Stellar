"""
PDAX transaction-tracking models — fiat and crypto deposit/withdrawal records.

GET /v1/fiat/transactions filters by mode (CashIn/CashOut) and identifier;
GET /v1/crypto/transactions filters by identifier, txn_hash, or type. Both
paginate via page/pageSize.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from .withdrawals import RetryMethod


class FiatTransaction(BaseModel):
    """One fiat deposit/withdrawal record."""

    request_id: str
    transaction_id: int
    amount: str
    fee: str | None = None
    method: str
    mode: str = Field(..., description="CashIn | CashOut")
    reference_number: str
    fulfilled_at: str | None = None
    declined_at: str | None = None
    rejection_reason: str | None = None
    currency: str = "PHP"
    created_at: str | None = None
    updated_at: str | None = None
    status: str
    identifier: str
    fee_type: str | None = None
    retried_methods: list[RetryMethod] = Field(default_factory=list)


class CryptoTransaction(BaseModel):
    """One crypto deposit/withdrawal record."""

    transaction_id: int
    type: str = Field(..., description="crypto_in | crypto_out")
    debit_ccy: str | None = None
    credit_ccy: str | None = None
    debit_amount: str = "0"
    debit_net_amount: str = "0"
    credit_amount: str = "0"
    credit_net_amount: str = "0"
    fee_amount: str = "0"
    status: str
    created_at: str | None = None
    txn_hash: str | None = None
    sender_email: str | None = None
    sender_wallet_address: str | None = None
    sender_wallet_address_tag: str | None = None
    receiver_email: str | None = None
    receiver_wallet_address: str | None = None
    receiver_wallet_address_tag: str | None = None
    identifier: str | None = None
