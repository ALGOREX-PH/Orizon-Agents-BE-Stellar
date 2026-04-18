"""
Thin wrapper around stellar-sdk for talking to the four Orizon contracts.

Design: everything reads via Soroban RPC (no signing). For *writes* we expose
two helpers:

  - `build_invoke_xdr(...)` → returns an unsigned base64 XDR that the frontend
    hands to Freighter for the user to sign. The user's wallet is the payer.

  - `invoke_with_server_key(...)` → signs with the backend's STELLAR_SIGNING_KEY
    (the `settler` / `sealer` / `scorer` role). Used for charge / seal / rate.

All amounts are i128 with Stellar's 7-decimal convention (0.012 USDC → 120000).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from stellar_sdk import (
    Address,
    Keypair,
    Network,
    SorobanServer,
    TransactionBuilder,
    scval,
)
from stellar_sdk.exceptions import PrepareTransactionException
from stellar_sdk.soroban_rpc import GetTransactionStatus, SendTransactionStatus

from ..config import settings


@dataclass
class ContractIds:
    agent_registry: str
    reputation_ledger: str
    payment_escrow: str
    attestation_registry: str
    asset_sac: str


def contract_ids() -> ContractIds:
    return ContractIds(
        agent_registry=settings.stellar_agent_registry,
        reputation_ledger=settings.stellar_reputation_ledger,
        payment_escrow=settings.stellar_payment_escrow,
        attestation_registry=settings.stellar_attestation_registry,
        asset_sac=settings.stellar_asset_sac,
    )


def network_passphrase() -> str:
    return settings.stellar_network_passphrase or Network.TESTNET_NETWORK_PASSPHRASE


def _server() -> SorobanServer:
    return SorobanServer(settings.stellar_rpc_url)


# ── reads ──────────────────────────────────────────────────────────────
def simulate_read(
    contract_id: str,
    function_name: str,
    args: list[Any] | None = None,
    source: str | None = None,
) -> Any:
    """
    Simulate a view-style call — no signature, no fees, no state change.

    `args` must be stellar_sdk.scval values (built via `scval.to_*`).
    """
    server = _server()
    src_addr = source or settings.stellar_admin_address
    if not src_addr:
        raise RuntimeError("no source address; set STELLAR_ADMIN_ADDRESS")

    account = server.load_account(src_addr)
    tx = (
        TransactionBuilder(
            source_account=account,
            network_passphrase=network_passphrase(),
            base_fee=100,
        )
        .append_invoke_contract_function_op(
            contract_id=contract_id,
            function_name=function_name,
            parameters=args or [],
        )
        .set_timeout(30)
        .build()
    )
    sim = server.simulate_transaction(tx)
    if sim.error:
        raise RuntimeError(f"simulate failed: {sim.error}")
    # Latest successful result is in `results[0].xdr` (base64). For convenience,
    # decode with scval helpers at the call site.
    if not sim.results:
        return None
    return scval.to_native(sim.results[0].xdr)


# ── writes (backend-signed) ─────────────────────────────────────────────
def invoke_with_server_key(
    contract_id: str,
    function_name: str,
    args: list[Any],
) -> dict[str, Any]:
    """Sign + submit a contract invocation with the backend's STELLAR_SIGNING_KEY."""
    secret = settings.stellar_signing_key
    if not secret:
        raise RuntimeError("STELLAR_SIGNING_KEY is empty")
    kp = Keypair.from_secret(secret)
    server = _server()
    account = server.load_account(kp.public_key)

    tx = (
        TransactionBuilder(
            source_account=account,
            network_passphrase=network_passphrase(),
            base_fee=100,
        )
        .append_invoke_contract_function_op(
            contract_id=contract_id,
            function_name=function_name,
            parameters=args,
        )
        .set_timeout(30)
        .build()
    )
    try:
        tx = server.prepare_transaction(tx)
    except PrepareTransactionException as e:
        raise RuntimeError(f"prepare failed: {e.simulate_transaction_response.error}") from e
    tx.sign(kp)

    sent = server.send_transaction(tx)
    if sent.status != SendTransactionStatus.PENDING:
        raise RuntimeError(f"submit failed: {sent.error_result_xdr}")

    # Poll briefly for final status.
    import time
    for _ in range(30):
        status = server.get_transaction(sent.hash)
        if status.status in (GetTransactionStatus.SUCCESS, GetTransactionStatus.FAILED):
            return {
                "hash": sent.hash,
                "status": status.status.value,
                "ledger": status.ledger,
                "result": scval.to_native(status.return_value) if status.return_value else None,
            }
        time.sleep(1)
    return {"hash": sent.hash, "status": "timeout"}


# ── writes (user-signed via Freighter) ──────────────────────────────────
def build_invoke_xdr(
    contract_id: str,
    function_name: str,
    args: list[Any],
    source: str,
) -> str:
    """
    Build an UNSIGNED, prepared transaction XDR for the frontend to hand to
    Freighter. After Freighter returns the signed XDR, submit it with
    `submit_signed_xdr(signed_xdr)`.
    """
    server = _server()
    account = server.load_account(source)
    tx = (
        TransactionBuilder(
            source_account=account,
            network_passphrase=network_passphrase(),
            base_fee=100,
        )
        .append_invoke_contract_function_op(
            contract_id=contract_id,
            function_name=function_name,
            parameters=args,
        )
        .set_timeout(300)
        .build()
    )
    prepared = server.prepare_transaction(tx)
    return prepared.to_xdr()


def submit_signed_xdr(signed_xdr: str) -> dict[str, Any]:
    """Submit a user-signed (via Freighter) prepared transaction."""
    from stellar_sdk import TransactionEnvelope

    server = _server()
    env = TransactionEnvelope.from_xdr(signed_xdr, network_passphrase())
    sent = server.send_transaction(env)
    if sent.status != SendTransactionStatus.PENDING:
        raise RuntimeError(f"submit failed: {sent.error_result_xdr}")

    import time
    for _ in range(30):
        status = server.get_transaction(sent.hash)
        if status.status in (GetTransactionStatus.SUCCESS, GetTransactionStatus.FAILED):
            return {
                "hash": sent.hash,
                "status": status.status.value,
                "ledger": status.ledger,
                "return_value": scval.to_native(status.return_value)
                if status.return_value
                else None,
            }
        time.sleep(1)
    return {"hash": sent.hash, "status": "timeout"}


# ── helpers for arg encoding ────────────────────────────────────────────
def sym(s: str):
    return scval.to_symbol(s)


def addr(a: str):
    return scval.to_address(Address(a))


def i128(v: int):
    return scval.to_int128(v)


def u64(v: int):
    return scval.to_uint64(v)


def u32(v: int):
    return scval.to_uint32(v)


def bytes16(b: bytes):
    assert len(b) == 16
    return scval.to_bytes(b)


def bytes32(b: bytes):
    assert len(b) == 32
    return scval.to_bytes(b)


def usdc_to_i128(amount_usdc: float) -> int:
    """0.012 → 120_000 (Stellar uses 7 decimals)."""
    return round(amount_usdc * 10_000_000)
