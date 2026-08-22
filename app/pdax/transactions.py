"""
PDAX transaction-tracking endpoints — fiat and crypto histories.

Both return enveloped lists and paginate via page/pageSize. Fiat filters by
mode (CashIn/CashOut) + identifier; crypto filters by identifier, txn_hash,
or type.
"""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from .client import PdaxClient
from .errors import PdaxError
from .models.transactions import CryptoTransaction, FiatTransaction

_M = TypeVar("_M", bound=BaseModel)


def _unwrap_list(data: Any, model: type[_M]) -> list[_M]:
    """Parse an enveloped PDAX list body into `model`s, folding malformed
    upstream shapes into a PdaxError.

    The list counterpart of `trade._unwrap`, with the same contract: a body
    that is not an object, a `data` envelope that is not a list of objects, or
    an entry carrying fields the model rejects must surface as a PdaxError —
    never a bare AttributeError/TypeError/ValidationError, which no route
    catches and every caller would see as an unhandled 500.
    """
    try:
        return [model(**item) for item in data.get("data", [])]
    except (TypeError, AttributeError, ValidationError) as e:
        raise PdaxError("malformed PDAX response", code="bad_upstream_shape") from e


async def fiat_transactions(
    client: PdaxClient,
    *,
    mode: str | None = None,
    identifier: str | None = None,
    page: int = 1,
    page_size: int = 10,
) -> list[FiatTransaction]:
    data = await client.request(
        "GET",
        "pdax-institution/v1/fiat/transactions",
        params={
            "mode": mode,
            "identifier": identifier,
            "page": page,
            "pageSize": page_size,
        },
    )
    return _unwrap_list(data, FiatTransaction)


async def crypto_transactions(
    client: PdaxClient,
    *,
    identifier: str | None = None,
    txn_hash: str | None = None,
    type: str | None = None,
    page: int = 1,
    page_size: int = 10,
) -> list[CryptoTransaction]:
    data = await client.request(
        "GET",
        "pdax-institution/v1/crypto/transactions",
        params={
            "identifier": identifier,
            "txn_hash": txn_hash,
            "type": type,
            "page": page,
            "pageSize": page_size,
        },
    )
    return _unwrap_list(data, CryptoTransaction)
