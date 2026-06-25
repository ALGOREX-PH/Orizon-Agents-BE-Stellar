"""
PDAX trade endpoints — indicative price, firm quote (v1/v2), and orders.

Each function takes a `PdaxClient` and returns a typed model. Firm quotes
expire in ~15s; pass the resulting `quote_id` to `place_order` to execute.
"""
from __future__ import annotations

from .client import PdaxClient
from .models.trade import (
    FirmQuoteRequest,
    FirmQuoteV2Request,
    IndicativePriceParams,
    IndicativePriceV2Params,
    Order,
    OrderRequest,
    Quote,
)


async def indicative_price(client: PdaxClient, params: IndicativePriceParams) -> Quote:
    data = await client.request(
        "GET", "pdax-institution/v1/trade/price", params=params.model_dump()
    )
    return Quote(**data["data"])


async def firm_quote(client: PdaxClient, req: FirmQuoteRequest) -> Quote:
    data = await client.request(
        "POST", "pdax-institution/v1/trade/quote", json=req.model_dump()
    )
    return Quote(**data["data"])


async def indicative_price_v2(client: PdaxClient, params: IndicativePriceV2Params) -> Quote:
    data = await client.request(
        "GET", "pdax-institution/v2/trade/price", params=params.model_dump()
    )
    return Quote(**data["data"])


async def firm_quote_v2(client: PdaxClient, req: FirmQuoteV2Request) -> Quote:
    data = await client.request(
        "POST", "pdax-institution/v2/trade/quote", json=req.model_dump()
    )
    return Quote(**data["data"])


async def place_order(client: PdaxClient, req: OrderRequest) -> Order:
    data = await client.request("POST", "pdax-institution/v1/trade", json=req.model_dump())
    return Order(**data["data"])


async def get_order(client: PdaxClient, order_id: int | str) -> Order:
    data = await client.request("GET", f"pdax-institution/v1/orders/{order_id}")
    return Order(**data["data"])


async def list_orders(
    client: PdaxClient,
    *,
    page: int = 1,
    page_size: int = 10,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[Order]:
    data = await client.request(
        "GET",
        "pdax-institution/v1/orders",
        params={
            "page": page,
            "pageSize": page_size,
            "startDate": start_date,
            "endDate": end_date,
        },
    )
    return [Order(**o) for o in data.get("data", [])]
