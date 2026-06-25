"""
Shared PDAX models — response envelope, pagination, and common literals.

Most PDAX endpoints wrap their payload in `{ "data": ..., "status": "success" }`.
`Envelope` captures that shape; domain models describe the inner `data`.
"""
from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel

T = TypeVar("T")

Side = Literal["buy", "sell"]
TradeStatus = Literal["successful", "failed", "IN PROGRESS", "SUCCESSFUL", "FAILED"]
TxStatus = Literal["pending", "completed", "failed", "PENDING", "COMPLETED", "FAILED"]
AssetType = Literal["FIAT", "CRYPTO", "fiat", "crypto"]


class Envelope(BaseModel, Generic[T]):
    """The standard `{ data, status }` PDAX response wrapper."""

    data: T
    status: str = "success"


class Pagination(BaseModel):
    """Common pagination query for list endpoints."""

    page: int = 1
    page_size: int = 10
