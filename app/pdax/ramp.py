"""
Ramp orchestration — PHP ↔ USDCXLM over PDAX.

Composes the trade / funding / withdrawals primitives into two flows and tracks
them as `RampRecord`s:

  start_onramp  → fiat deposit (returns a checkout URL the buyer pays)
  advance_onramp (on FiatEvent DEPOSIT COMPLETED) → buy USDC → withdraw USDCXLM
  start_offramp → returns a USDCXLM deposit address
  advance_offramp (on CryptoEvent DEPOSIT completed) → sell USDC → fiat withdraw

`handle_event` is the webhook entry point: it matches an inbound settlement
event to a waiting ramp and advances it. The relevant Stellar asset is USDCXLM.
"""
from __future__ import annotations

import uuid

from . import funding, ramp_store, trade, withdrawals
from .client import PdaxClient
from .errors import PdaxError
from .models.funding import FiatDepositRequest
from .models.ramp import (
    OffRampRequest,
    OnRampRequest,
    RampDirection,
    RampEstimate,
    RampRecord,
)
from .models.trade import FirmQuoteV2Request, IndicativePriceV2Params, OrderRequest
from .models.webhooks import CryptoEvent, FiatEvent
from .models.withdrawals import CryptoOutRequest, FiatWithdrawRequest

USDC = "USDC"
USDCXLM = "USDCXLM"
PHP = "PHP"


def _num(x: float) -> str:
    """PDAX amounts are strings; trim a float to a clean representation."""
    return f"{x:.8f}".rstrip("0").rstrip(".")


async def estimate(client: PdaxClient, direction: RampDirection, amount: str) -> RampEstimate:
    """Indicative conversion preview. `amount` is PHP for on-ramp, USDC for
    off-ramp. `currency` denominates `quantity` (per the firm-quote v2 sample)."""
    if direction == "onramp":
        params = IndicativePriceV2Params(
            side="buy", quote_currency=USDC, base_currency=PHP, currency=PHP, quantity=amount
        )
        q = await trade.indicative_price_v2(client, params)
        return RampEstimate(
            direction="onramp",
            php_amount=q.total_amount or float(amount),
            usdc_amount=q.base_quantity,
            price=q.price,
        )
    params = IndicativePriceV2Params(
        side="sell", quote_currency=USDC, base_currency=PHP, currency=USDC, quantity=amount
    )
    q = await trade.indicative_price_v2(client, params)
    return RampEstimate(
        direction="offramp",
        php_amount=q.total_amount,
        usdc_amount=q.base_quantity or float(amount),
        price=q.price,
    )


async def start_onramp(client: PdaxClient, req: OnRampRequest) -> RampRecord:
    """Create the fiat deposit and a ramp record awaiting the buyer's payment."""
    record = RampRecord(
        ramp_id=ramp_store.new_id(),
        direction="onramp",
        status="quoted",
        created_at=ramp_store.now_iso(),
        php_amount=float(req.php_amount),
        stellar_address=req.stellar_address,
        identifier=req.identifier,
    )
    # Best-effort indicative preview (non-fatal if PDAX is unreachable).
    try:
        est = await estimate(client, "onramp", req.php_amount)
        record.usdc_amount, record.price = est.usdc_amount, est.price
        ramp_store.add_stage(record, "estimate", "success", f"{est.usdc_amount} USDC @ {est.price}")
    except PdaxError as e:
        ramp_store.add_stage(record, "estimate", "failed", str(e))

    deposit = FiatDepositRequest(
        amount=req.php_amount,
        method=req.method,
        identifier=req.identifier,
        currency=PHP,
        sender_first_name=req.sender_first_name,
        sender_last_name=req.sender_last_name,
        sender_country_origin=req.sender_country_origin,
        source_of_funds=req.source_of_funds,
        beneficiary_first_name=req.beneficiary_first_name,
        beneficiary_last_name=req.beneficiary_last_name,
        purpose=req.purpose,
        relationship_of_sender_to_beneficiary=req.relationship_of_sender_to_beneficiary,
    )
    try:
        result = await funding.fiat_deposit(client, deposit)
        record.checkout_url = result.payment_checkout_url
        record.reference_number = result.reference_number
        record.status = "awaiting_payment"
        ramp_store.add_stage(record, "fiat_deposit", "success", result.reference_number)
    except PdaxError as e:
        record.status = "failed"
        record.error = str(e)
        ramp_store.add_stage(record, "fiat_deposit", "failed", str(e))
    return ramp_store.save(record)


async def advance_onramp(client: PdaxClient, record: RampRecord) -> RampRecord:
    """PHP has landed — buy USDC then withdraw USDCXLM to the Stellar address."""
    record.status = "converting"
    try:
        quote = await trade.firm_quote_v2(
            client,
            FirmQuoteV2Request(
                side="buy", quote_currency=USDC, base_currency=PHP,
                currency=PHP, quantity=_num(record.php_amount),
            ),
        )
        order = await trade.place_order(
            client, OrderRequest(quote_id=quote.quote_id, side="buy", idempotency_id=str(uuid.uuid4()))
        )
        record.order_id = order.order_id
        record.usdc_amount = order.base_quantity
        record.price = order.price
        ramp_store.add_stage(record, "buy_usdc", "success", f"order {order.order_id}")
    except PdaxError as e:
        record.status, record.error = "failed", str(e)
        ramp_store.add_stage(record, "buy_usdc", "failed", str(e))
        return ramp_store.save(record)

    record.status = "settling"
    try:
        out = await withdrawals.crypto_out(
            client,
            CryptoOutRequest(
                identifier=f"{record.identifier}-out",
                currency=USDCXLM,
                amount=_num(record.usdc_amount),
                address=record.stellar_address or "",
            ),
        )
        record.crypto_tx_id = out.transaction_id
        record.status = "completed"
        ramp_store.add_stage(record, "withdraw_usdcxlm", "success", str(out.transaction_id))
    except PdaxError as e:
        record.status, record.error = "failed", str(e)
        ramp_store.add_stage(record, "withdraw_usdcxlm", "failed", str(e))
    return ramp_store.save(record)


async def start_offramp(client: PdaxClient, req: OffRampRequest) -> RampRecord:
    """Return a USDCXLM deposit address; the agent sends USDC to it next."""
    record = RampRecord(
        ramp_id=ramp_store.new_id(),
        direction="offramp",
        status="quoted",
        created_at=ramp_store.now_iso(),
        usdc_amount=float(req.usdc_amount),
        identifier=req.identifier,
    )
    try:
        est = await estimate(client, "offramp", req.usdc_amount)
        record.php_amount, record.price = est.php_amount, est.price
        ramp_store.add_stage(record, "estimate", "success", f"{est.php_amount} PHP @ {est.price}")
    except PdaxError as e:
        ramp_store.add_stage(record, "estimate", "failed", str(e))

    try:
        addr = await funding.crypto_deposit_address(client, USDCXLM)
        record.deposit_address = addr.address
        record.deposit_tag = addr.tag
        record.status = "awaiting_payment"
        ramp_store.add_stage(record, "deposit_address", "success", addr.address)
    except PdaxError as e:
        record.status, record.error = "failed", str(e)
        ramp_store.add_stage(record, "deposit_address", "failed", str(e))
    # Stash the beneficiary payout details for the advance step.
    _PAYOUTS[record.ramp_id] = req
    return ramp_store.save(record)


async def advance_offramp(client: PdaxClient, record: RampRecord) -> RampRecord:
    """USDC has arrived — sell it for PHP then withdraw to the bank account."""
    payout = _PAYOUTS.get(record.ramp_id)
    if payout is None:
        record.status, record.error = "failed", "missing payout details"
        return ramp_store.save(record)

    record.status = "converting"
    try:
        quote = await trade.firm_quote_v2(
            client,
            FirmQuoteV2Request(
                side="sell", quote_currency=USDC, base_currency=PHP,
                currency=USDC, quantity=_num(record.usdc_amount),
            ),
        )
        order = await trade.place_order(
            client, OrderRequest(quote_id=quote.quote_id, side="sell", idempotency_id=str(uuid.uuid4()))
        )
        record.order_id = order.order_id
        record.php_amount = order.total_amount
        record.price = order.price
        ramp_store.add_stage(record, "sell_usdc", "success", f"order {order.order_id}")
    except PdaxError as e:
        record.status, record.error = "failed", str(e)
        ramp_store.add_stage(record, "sell_usdc", "failed", str(e))
        return ramp_store.save(record)

    record.status = "settling"
    try:
        result = await withdrawals.fiat_withdraw(
            client,
            FiatWithdrawRequest(
                identifier=f"{payout.identifier}-payout",
                amount=_num(record.php_amount),
                currency=PHP,
                method=payout.method,
                fee_type=payout.fee_type,
                sender_first_name=payout.sender_first_name,
                sender_last_name=payout.sender_last_name,
                sender_country_origin=payout.sender_country_origin,
                source_of_funds=payout.source_of_funds,
                beneficiary_first_name=payout.beneficiary_first_name,
                beneficiary_last_name=payout.beneficiary_last_name,
                beneficiary_bank_code=payout.beneficiary_bank_code,
                beneficiary_account_name=payout.beneficiary_account_name,
                beneficiary_account_number=payout.beneficiary_account_number,
                purpose=payout.purpose,
                relationship_of_sender_to_beneficiary=payout.relationship_of_sender_to_beneficiary,
            ),
        )
        record.withdraw_request_id = result.request_id
        record.status = "completed" if result.status != "FAILED" else "failed"
        ramp_store.add_stage(record, "fiat_withdraw", "success", result.status)
    except PdaxError as e:
        record.status, record.error = "failed", str(e)
        ramp_store.add_stage(record, "fiat_withdraw", "failed", str(e))
    return ramp_store.save(record)


async def handle_event(client: PdaxClient, event: CryptoEvent | FiatEvent) -> RampRecord | None:
    """Webhook entry point — match a settlement event to a waiting ramp and
    advance it. Returns the advanced record, or None if nothing matched."""
    if isinstance(event, FiatEvent):
        if "DEPOSIT" not in event.transaction_type.upper():
            return None
        if str(event.status).upper() != "COMPLETED" or not event.identifier:
            return None
        record = ramp_store.find_by_identifier(event.identifier)
        if record and record.direction == "onramp" and record.status == "awaiting_payment":
            record.status = "funded"
            return await advance_onramp(client, record)
        return None

    # CryptoEvent — match an off-ramp by its USDCXLM deposit address.
    if "DEPOSIT" not in event.transaction_type.upper():
        return None
    if str(event.status).lower() != "completed":
        return None
    for record in ramp_store.list_all():
        if (
            record.direction == "offramp"
            and record.status == "awaiting_payment"
            and record.deposit_address
            and record.deposit_address == event.destination_address
        ):
            record.status = "funded"
            return await advance_offramp(client, record)
    return None


# Beneficiary payout details for in-flight off-ramps (kept beside the store).
_PAYOUTS: dict[str, OffRampRequest] = {}
