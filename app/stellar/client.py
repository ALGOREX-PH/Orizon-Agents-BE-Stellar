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
            rv = _extract_return_value(status.result_meta_xdr)
            if isinstance(rv, (bytes, bytearray)):
                rv = rv.hex()
            return {
                "hash": sent.hash,
                "status": status.status.value,
                "ledger": status.ledger,
                "result": rv,
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
    import sys
    import time

    from stellar_sdk import TransactionEnvelope

    server = _server()
    try:
        env = TransactionEnvelope.from_xdr(signed_xdr, network_passphrase())
    except Exception as e:
        print(f"[stellar.submit] bad XDR: {e}", file=sys.stderr)
        raise RuntimeError(
            f"bad signed XDR (likely wrong networkPassphrase or malformed): {e}"
        ) from e

    sent = server.send_transaction(env)
    if sent.status != SendTransactionStatus.PENDING:
        detail = (
            f"status={sent.status} "
            f"error={getattr(sent, 'error_result_xdr', None)} "
            f"hash={sent.hash}"
        )
        print(f"[stellar.submit] send failed: {detail}", file=sys.stderr)
        raise RuntimeError(f"submit failed ({detail})")

    for _ in range(30):
        status = server.get_transaction(sent.hash)
        if status.status in (GetTransactionStatus.SUCCESS, GetTransactionStatus.FAILED):
            rv = _extract_return_value(status.result_meta_xdr)
            if isinstance(rv, (bytes, bytearray)):
                rv = rv.hex()
            diag = _extract_diagnostics(status)
            if status.status == GetTransactionStatus.FAILED:
                print(
                    f"[stellar.submit] tx {sent.hash} FAILED · {diag}",
                    file=sys.stderr,
                )
            return {
                "hash": sent.hash,
                "status": status.status.value,
                "ledger": status.ledger,
                "return_value": rv,
                "diagnostic": diag,
                "explorer": f"https://stellar.expert/explorer/testnet/tx/{sent.hash}",
            }
        time.sleep(1)
    return {"hash": sent.hash, "status": "timeout"}


def _extract_diagnostics(status: Any) -> str:
    """Summarize failure reasons from diagnostic events + result xdr."""
    bits: list[str] = []
    try:
        from stellar_sdk import xdr as _xdr

        for ev_xdr in (getattr(status, "diagnostic_events_xdr", None) or []):
            try:
                ev = _xdr.DiagnosticEvent.from_xdr(ev_xdr)
                # Re-stringify the interesting parts without crashing on exotic shapes.
                s = str(ev)
                # Keep the message terse — drop internal whitespace.
                s = " ".join(s.split())
                if "Error(" in s or "error" in s.lower():
                    bits.append(s[:360])
            except Exception:
                continue
        if not bits:
            rxdr = getattr(status, "result_xdr", None)
            if rxdr:
                bits.append(f"result_xdr={rxdr[:120]}")
    except Exception as e:
        bits.append(f"(diag parse: {e})")
    return " | ".join(bits) if bits else "no diagnostic events"


def _extract_return_value(result_meta_xdr: str | None) -> Any:
    """Pull the Soroban contract return value out of a transaction's meta XDR.

    stellar-sdk 13.x no longer exposes `GetTransactionResponse.return_value`;
    we parse `result_meta_xdr` ourselves.
    """
    if not result_meta_xdr:
        return None
    try:
        from stellar_sdk import xdr as _xdr

        meta = _xdr.TransactionMeta.from_xdr(result_meta_xdr)
        # TransactionMetaV3 has a `soroban_meta.return_value`; v4 has a similar field.
        for attr in ("v3", "v4"):
            v = getattr(meta, attr, None)
            if v is None:
                continue
            soroban = getattr(v, "soroban_meta", None)
            if soroban and getattr(soroban, "return_value", None) is not None:
                return scval.to_native(soroban.return_value)
    except Exception as e:
        import sys
        print(f"[stellar.submit] meta decode failed: {e}", file=sys.stderr)
    return None


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
