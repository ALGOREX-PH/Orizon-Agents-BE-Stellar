"""
/api/pdax/* — surfaces the PDAX institutions API (PHP ↔ crypto on/off-ramp)
to the frontend.

Auth is handled server-side: the backend logs into PDAX with its own
credentials and caches tokens, so the frontend never sees them. Endpoints
mirror the PDAX domains: trade, funding, withdrawals, transactions, balances,
and webhooks. PdaxError is translated to an HTTPException preserving the
upstream status + message.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..config import settings
from ..security import require_api_key
from ..pdax import (
    balances as pb,
    funding as pf,
    ramp as pr,
    trade as pt,
    transactions as ptx,
    webhooks as pw,
    withdrawals as pwd,
)
from ..pdax import base_url, constants as pc, get_pdax_client
from ..pdax.errors import PdaxError
from ..pdax.models.common import Side
from ..pdax.models.funding import FiatDepositRequest
from ..pdax.models.ramp import OffRampRequest, OnRampRequest, _positive_decimal_str
from ..pdax.models.trade import (
    FirmQuoteRequest,
    FirmQuoteV2Request,
    IndicativePriceParams,
    IndicativePriceV2Params,
    OrderRequest,
)
from ..pdax.models.webhooks import WebhookRegisterRequest
from ..pdax.models.withdrawals import CryptoOutRequest, FiatWithdrawRequest

router = APIRouter(prefix="/pdax", tags=["pdax"])

# Money-moving + account-revealing routes require the backend API key
# (a no-op only when API_KEY is unset — the public demo default). The
# genuinely public routes (health, environment, reference tables, and the
# HMAC-authenticated webhook receiver) stay on `router`.
secured = APIRouter(dependencies=[Depends(require_api_key)])


def _fail(e: PdaxError) -> HTTPException:
    status = e.http_status if e.http_status and 400 <= e.http_status < 600 else 502
    return HTTPException(status, detail=str(e))


@router.get("/environment")
async def environment() -> dict:
    """Report the active PDAX environment + base URL (no secrets)."""
    return {
        "environment": settings.pdax_environment,
        "base_url": base_url(),
        "configured": bool(settings.pdax_username and settings.pdax_password),
    }


@router.get("/health")
async def health() -> dict:
    """Liveness + dependency check. Probes the PDAX auth handshake and reports
    ok / degraded / unconfigured — never exposing credentials."""
    if not (settings.pdax_username and settings.pdax_password):
        return {"status": "unconfigured", "environment": settings.pdax_environment}
    try:
        await get_pdax_client().healthcheck()
        return {"status": "ok", "environment": settings.pdax_environment}
    except PdaxError as e:
        return {
            "status": "degraded",
            "environment": settings.pdax_environment,
            "reason": e.message,
            "code": e.code,
        }


# ── trade ───────────────────────────────────────────────────────
@secured.get("/trade/price")
async def trade_price(
    quote_currency: str,
    side: Side,
    base_quantity: str,
    base_currency: str = "PHP",
) -> dict:
    """Indicative (non-binding) price for a pair."""
    try:
        params = IndicativePriceParams(
            quote_currency=quote_currency,
            base_currency=base_currency,
            side=side,
            base_quantity=base_quantity,
        )
        quote = await pt.indicative_price(get_pdax_client(), params)
        return quote.model_dump()
    except PdaxError as e:
        raise _fail(e) from e


@secured.get("/trade/price/v2")
async def trade_price_v2(
    quote_currency: str,
    side: Side,
    currency: str,
    quantity: str,
    base_currency: str = "PHP",
) -> dict:
    """Indicative price (v2 — receive-side currency + quantity)."""
    try:
        params = IndicativePriceV2Params(
            side=side,
            quote_currency=quote_currency,
            base_currency=base_currency,
            currency=currency,
            quantity=quantity,
        )
        quote = await pt.indicative_price_v2(get_pdax_client(), params)
        return quote.model_dump()
    except PdaxError as e:
        raise _fail(e) from e


@secured.post("/trade/quote")
async def trade_quote(req: FirmQuoteRequest) -> dict:
    """Firm quote (expires in ~15s) acceptable via /trade/order."""
    try:
        quote = await pt.firm_quote(get_pdax_client(), req)
        return quote.model_dump()
    except PdaxError as e:
        raise _fail(e) from e


@secured.post("/trade/quote/v2")
async def trade_quote_v2(req: FirmQuoteV2Request) -> dict:
    """Firm quote (v2)."""
    try:
        quote = await pt.firm_quote_v2(get_pdax_client(), req)
        return quote.model_dump()
    except PdaxError as e:
        raise _fail(e) from e


@secured.post("/trade/order")
async def trade_order(req: OrderRequest) -> dict:
    """Accept a firm quote and execute the trade."""
    try:
        order = await pt.place_order(get_pdax_client(), req)
        return order.model_dump()
    except PdaxError as e:
        raise _fail(e) from e


@secured.get("/trade/orders/{order_id}")
async def trade_order_details(order_id: int) -> dict:
    try:
        order = await pt.get_order(get_pdax_client(), order_id)
        return order.model_dump()
    except PdaxError as e:
        raise _fail(e) from e


@secured.get("/trade/orders")
async def trade_orders(
    page: int = 1,
    page_size: int = Query(10, alias="pageSize"),
    start_date: str | None = Query(None, alias="startDate"),
    end_date: str | None = Query(None, alias="endDate"),
) -> dict:
    try:
        orders = await pt.list_orders(
            get_pdax_client(),
            page=page,
            page_size=page_size,
            start_date=start_date,
            end_date=end_date,
        )
        return {"orders": [o.model_dump() for o in orders]}
    except PdaxError as e:
        raise _fail(e) from e


# ── funding (deposits) ──────────────────────────────────────────
@secured.get("/crypto/deposit")
async def crypto_deposit(currency: str) -> dict:
    """Wallet address to deposit a crypto token, e.g. currency=USDCXLM."""
    try:
        addr = await pf.crypto_deposit_address(get_pdax_client(), currency)
        return addr.model_dump()
    except PdaxError as e:
        raise _fail(e) from e


@secured.post("/fiat/deposit")
async def fiat_deposit(req: FiatDepositRequest) -> dict:
    """Initiate a PHP cash-in; returns a payment_checkout_url."""
    try:
        result = await pf.fiat_deposit(get_pdax_client(), req)
        return result.model_dump()
    except PdaxError as e:
        raise _fail(e) from e


# ── withdrawals ─────────────────────────────────────────────────
@secured.post("/fiat/withdraw")
async def fiat_withdraw(req: FiatWithdrawRequest) -> dict:
    """Withdraw PHP to a bank / e-wallet beneficiary."""
    try:
        result = await pwd.fiat_withdraw(get_pdax_client(), req)
        return result.model_dump()
    except PdaxError as e:
        raise _fail(e) from e


@secured.post("/fiat/user-info-upload")
async def fiat_user_info_upload(req: FiatWithdrawRequest) -> dict:
    """Upload sender/beneficiary travel-rule data for a fiat withdrawal."""
    try:
        result = await pwd.user_info_upload(get_pdax_client(), req)
        return result.model_dump()
    except PdaxError as e:
        raise _fail(e) from e


@secured.post("/crypto/withdraw")
async def crypto_withdraw(req: CryptoOutRequest) -> dict:
    """Send a crypto token to an external address (e.g. USDCXLM)."""
    try:
        result = await pwd.crypto_out(get_pdax_client(), req)
        return result.model_dump()
    except PdaxError as e:
        raise _fail(e) from e


# ── transaction history ─────────────────────────────────────────
@secured.get("/fiat/transactions")
async def fiat_transactions(
    mode: str | None = None,
    identifier: str | None = None,
    page: int = 1,
    page_size: int = Query(10, alias="pageSize"),
) -> dict:
    """Track PHP cash-in/out by mode (CashIn/CashOut) or identifier."""
    try:
        txns = await ptx.fiat_transactions(
            get_pdax_client(),
            mode=mode,
            identifier=identifier,
            page=page,
            page_size=page_size,
        )
        return {"transactions": [t.model_dump() for t in txns]}
    except PdaxError as e:
        raise _fail(e) from e


@secured.get("/crypto/transactions")
async def crypto_transactions(
    identifier: str | None = None,
    txn_hash: str | None = None,
    type: str | None = None,
    page: int = 1,
    page_size: int = Query(10, alias="pageSize"),
) -> dict:
    """Track crypto deposits/withdrawals by identifier, hash, or type."""
    try:
        txns = await ptx.crypto_transactions(
            get_pdax_client(),
            identifier=identifier,
            txn_hash=txn_hash,
            type=type,
            page=page,
            page_size=page_size,
        )
        return {"transactions": [t.model_dump() for t in txns]}
    except PdaxError as e:
        raise _fail(e) from e


# ── balances ────────────────────────────────────────────────────
@secured.get("/balances")
async def balances(currency: str | None = None) -> dict:
    """View balances for all assets (or a single currency)."""
    try:
        items = await pb.get_balances(get_pdax_client(), currency)
        return {"balances": [b.model_dump() for b in items]}
    except PdaxError as e:
        raise _fail(e) from e


# ── webhooks ────────────────────────────────────────────────────
@secured.post("/webhooks/register")
async def webhook_register(req: WebhookRegisterRequest) -> dict:
    """Register this backend's URL to receive crypto or fiat events."""
    try:
        reg = await pw.register_webhook(get_pdax_client(), req)
        return reg.model_dump()
    except PdaxError as e:
        raise _fail(e) from e


@router.post("/webhooks/receive")
async def webhook_receive(request: Request) -> dict:
    """Inbound endpoint PDAX POSTs crypto/fiat events to. Validates the
    optional HMAC signature, then parses the event into a typed model."""
    raw = await request.body()
    signature = request.headers.get("x-pdax-signature")
    if not pw.verify_signature(raw, signature):
        raise HTTPException(401, detail="invalid webhook signature")
    try:
        payload = await request.json()
    except Exception as e:
        raise HTTPException(400, detail="invalid webhook payload") from e
    # Idempotency — a retried delivery must not advance a ramp twice.
    if not pw.claim_event(pw.event_key(payload)):
        return {"received": True, "duplicate": True}
    event = pw.parse_event(payload)
    # Drive any waiting ramp forward (fiat deposit → buy → withdraw, or
    # crypto deposit → sell → fiat withdraw).
    try:
        advanced = await pr.handle_event(get_pdax_client(), event)
    except PdaxError as e:
        raise _fail(e) from e
    return {
        "received": True,
        "event": event.model_dump(),
        "ramp": advanced.model_dump() if advanced else None,
    }


# ── reference (accepted values for FE dropdowns) ────────────────
# The constant tables are immutable frozensets — sort them once at import
# time instead of on every request.
_SOURCE_OF_FUNDS_SORTED = sorted(pc.SOURCE_OF_FUNDS)
_PURPOSE_SORTED = sorted(pc.PURPOSE)
_RELATIONSHIP_SORTED = sorted(pc.RELATIONSHIP)
_FEE_TYPE_SORTED = sorted(pc.FEE_TYPE)
_SEX_SORTED = sorted(pc.SEX)
_FIAT_WITHDRAWAL_METHODS_SORTED = sorted(pc.FIAT_WITHDRAWAL_METHODS)
_STELLAR_TOKENS_SORTED = sorted(pc.STELLAR_TOKENS)
_ACCEPTED_COUNTRIES_SORTED = sorted(pc.ACCEPTED_COUNTRIES)


@router.get("/reference")
async def reference() -> dict:
    """All PDAX accepted-value tables the frontend forms need."""
    return {
        "source_of_funds": _SOURCE_OF_FUNDS_SORTED,
        "purpose": _PURPOSE_SORTED,
        "relationship": _RELATIONSHIP_SORTED,
        "fee_type": _FEE_TYPE_SORTED,
        "sex": _SEX_SORTED,
        "fiat_deposit_methods": pc.FIAT_DEPOSIT_METHODS,
        "fiat_withdrawal_methods": _FIAT_WITHDRAWAL_METHODS_SORTED,
        "travel_rule_threshold_php": pc.TRAVEL_RULE_THRESHOLD_PHP,
    }


@router.get("/reference/banks")
async def reference_banks() -> dict:
    """Bank / e-wallet display name → PDAX bank code."""
    return {"banks": pc.BANK_NAME_TO_CODE}


@router.get("/reference/tokens")
async def reference_tokens() -> dict:
    """Supported crypto token → network (Stellar tokens flagged)."""
    return {"tokens": pc.TOKEN_NETWORKS, "stellar": _STELLAR_TOKENS_SORTED}


@router.get("/reference/countries")
async def reference_countries() -> dict:
    """Accepted country list (case-sensitive)."""
    return {"countries": _ACCEPTED_COUNTRIES_SORTED}


# ── ramp (PHP <-> USDCXLM orchestration) ────────────────────────
@secured.post("/ramp/estimate")
async def ramp_estimate(
    direction: Literal["onramp", "offramp"],
    amount: str,
    currency: str | None = None,
) -> dict:
    """Indicative conversion preview. `currency` denominates `amount`; pass
    currency=USDC on an on-ramp to price a target USDC amount (workflow cost)."""
    try:
        _positive_decimal_str(amount, "10000000")
    except ValueError as e:
        raise HTTPException(422, detail=str(e)) from e
    try:
        est = await pr.estimate(get_pdax_client(), direction, amount, currency)
        return est.model_dump()
    except PdaxError as e:
        raise _fail(e) from e


@secured.post("/ramp/funding-quote")
async def ramp_funding_quote(usdc: str) -> dict:
    """Pesos to pay to fund a workflow costing `usdc` USDC — buffered + rounded
    up so the amount always covers it."""
    try:
        _positive_decimal_str(usdc, "100000")
    except ValueError as e:
        raise HTTPException(422, detail=str(e)) from e
    try:
        quote = await pr.funding_quote(get_pdax_client(), usdc)
        return quote.model_dump()
    except PdaxError as e:
        raise _fail(e) from e


@secured.post("/ramp/onramp")
async def ramp_onramp(req: OnRampRequest) -> dict:
    """Start a PHP → USDCXLM ramp. Returns a checkout URL for the buyer to pay;
    settlement is completed by the fiat-deposit webhook."""
    try:
        record = await pr.start_onramp(get_pdax_client(), req)
    except PdaxError as e:
        raise _fail(e) from e
    return record.model_dump()


@secured.post("/ramp/offramp")
async def ramp_offramp(req: OffRampRequest) -> dict:
    """Start a USDCXLM → PHP ramp. Returns a deposit address for the agent to
    send USDC to; settlement is completed by the crypto-deposit webhook."""
    try:
        record = await pr.start_offramp(get_pdax_client(), req)
    except PdaxError as e:
        raise _fail(e) from e
    return record.model_dump()


@secured.get("/ramp")
async def ramp_list() -> dict:
    """All ramps tracked this process lifetime."""
    return {"ramps": [r.model_dump() for r in pr.ramp_store.list_all()]}


@secured.get("/ramp/{ramp_id}")
async def ramp_status(ramp_id: str) -> dict:
    """Current state + stage history of a single ramp."""
    record = pr.ramp_store.get(ramp_id)
    if record is None:
        raise HTTPException(404, detail="ramp not found")
    return record.model_dump()


@secured.post("/ramp/{ramp_id}/reconcile")
async def ramp_reconcile(ramp_id: str) -> dict:
    """Check PDAX for settlement and advance the ramp — used by the UI to track
    progress without relying on PDAX's redirect page."""
    try:
        record = await pr.reconcile(get_pdax_client(), ramp_id)
    except PdaxError as e:
        raise _fail(e) from e
    if record is None:
        raise HTTPException(404, detail="ramp not found")
    return record.model_dump()


router.include_router(secured)
