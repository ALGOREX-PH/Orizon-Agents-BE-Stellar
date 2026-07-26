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

import logging
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
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

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContractIds:
    agent_registry: str
    reputation_ledger: str
    payment_escrow: str
    attestation_registry: str
    asset_sac: str


@lru_cache(maxsize=1)
def contract_ids() -> ContractIds:
    return ContractIds(
        agent_registry=settings.stellar_agent_registry,
        reputation_ledger=settings.stellar_reputation_ledger,
        payment_escrow=settings.stellar_payment_escrow,
        attestation_registry=settings.stellar_attestation_registry,
        asset_sac=settings.stellar_asset_sac,
    )


@lru_cache(maxsize=1)
def network_passphrase() -> str:
    return settings.stellar_network_passphrase or Network.TESTNET_NETWORK_PASSPHRASE


def explorer_network() -> str:
    """stellar.expert network segment for the configured network."""
    return "public" if settings.stellar_network in ("mainnet", "public") else settings.stellar_network


_thread_local = threading.local()


def _server() -> SorobanServer:
    """Return this thread's cached SorobanServer.

    stellar-sdk 13.x's SorobanServer defaults to RequestsClient, which holds a
    requests.Session — and requests does not guarantee Session thread safety
    (response cookie-jar updates are unsynchronized). Sharing one instance
    across worker threads is therefore unsafe, so we cache one per thread:
    asyncio.to_thread reuses a small executor pool, so each thread still keeps
    its TCP+TLS connections alive across calls.
    """
    server = getattr(_thread_local, "server", None)
    if server is None:
        server = SorobanServer(settings.stellar_rpc_url)
        _thread_local.server = server
    return server


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
    return _to_jsonable(scval.to_native(sim.results[0].xdr))


def _to_jsonable(value: Any) -> Any:
    """Recursively convert scval natives to JSON-safe values.

    `scval.to_native` yields stellar_sdk `Address` objects and raw `bytes`
    (BytesN fields) — neither survives FastAPI's JSON encoding, which happens
    outside router try/except blocks and so used to surface as a bare 500.
    """
    if isinstance(value, Address):
        return value.address
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    return value


@lru_cache(maxsize=1)
def _signer_keypair() -> Keypair:
    """
    Build a Keypair from STELLAR_SIGNING_KEY, accepting either:
      - an S… secret key (56 chars), OR
      - a 12/24-word BIP-39 mnemonic seed phrase (words separated by spaces).

    Memoized: the signing key is immutable at runtime, so we derive once.
    (lru_cache does not cache exceptions, so an unset key keeps raising.)
    """
    secret = settings.stellar_signing_key or ""
    secret = secret.strip()
    if not secret:
        raise RuntimeError("STELLAR_SIGNING_KEY is empty")

    words = secret.split()
    if len(words) >= 12:
        try:
            return Keypair.from_mnemonic_phrase(" ".join(words))
        except Exception as e:
            raise RuntimeError(
                f"STELLAR_SIGNING_KEY looks like a mnemonic but is invalid: {e}"
            ) from e
    try:
        return Keypair.from_secret(secret)
    except Exception as e:
        raise RuntimeError(
            f"STELLAR_SIGNING_KEY must be an S… secret or a 12/24-word mnemonic ({e})"
        ) from e


def signer_public_key() -> str:
    """Public key (G…) of the backend signing keypair, from the cached Keypair."""
    return _signer_keypair().public_key


# ── writes (backend-signed) ─────────────────────────────────────────────
def invoke_with_server_key(
    contract_id: str,
    function_name: str,
    args: list[Any],
) -> dict[str, Any]:
    """Sign + submit a contract invocation with the backend's STELLAR_SIGNING_KEY."""
    kp = _signer_keypair()
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


def submit_rating(
    agent_id: str,
    job_id: bytes,
    rating_0_to_100: int,
    weight_stroops: int,
    payer: str,
    kind: str = "auto",
) -> dict[str, Any]:
    """ReputationLedger.submit signed by the backend scorer key."""
    return invoke_with_server_key(
        contract_ids().reputation_ledger,
        "submit",
        [
            addr(signer_public_key()),
            sym(agent_id),
            bytes16(job_id),
            u32(rating_0_to_100),
            i128(weight_stroops),
            addr(payer),
            sym(kind),
        ],
    )


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
    try:
        env = TransactionEnvelope.from_xdr(signed_xdr, network_passphrase())
    except Exception as e:
        logger.warning("[stellar.submit] bad XDR: %s", e)
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
        logger.error("[stellar.submit] send failed: %s", detail)
        raise RuntimeError(f"submit failed ({detail})")

    for _ in range(30):
        status = server.get_transaction(sent.hash)
        if status.status in (GetTransactionStatus.SUCCESS, GetTransactionStatus.FAILED):
            rv = _extract_return_value(status.result_meta_xdr)
            if isinstance(rv, (bytes, bytearray)):
                rv = rv.hex()
            diag = _extract_diagnostics(status)
            if status.status == GetTransactionStatus.FAILED:
                logger.error("[stellar.submit] tx %s FAILED · %s", sent.hash, diag)
            return {
                "hash": sent.hash,
                "status": status.status.value,
                "ledger": status.ledger,
                "return_value": rv,
                "diagnostic": diag,
                "explorer": f"https://stellar.expert/explorer/{explorer_network()}/tx/{sent.hash}",
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
        logger.warning("[stellar.submit] meta decode failed: %s", e)
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
