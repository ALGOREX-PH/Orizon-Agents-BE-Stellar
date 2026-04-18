"""
/api/stellar/* — surfaces the deployed Soroban contracts to the frontend.

Read routes simulate RPC calls (no signing).
Write routes have two shapes:
  - build-*   → returns unsigned XDR for Freighter to sign
  - submit    → takes Freighter-signed XDR and broadcasts it
"""
from __future__ import annotations

import secrets
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import settings
from ..stellar import client as sc

router = APIRouter(prefix="/stellar", tags=["stellar"])


# ── meta ────────────────────────────────────────────────────────
@router.get("/network")
async def network() -> dict:
    ids = sc.contract_ids()
    return {
        "network": settings.stellar_network,
        "rpc_url": settings.stellar_rpc_url,
        "network_passphrase": sc.network_passphrase(),
        "admin": settings.stellar_admin_address,
        "asset": "native",
        "asset_sac": ids.asset_sac,
        "contracts": {
            "agent_registry": ids.agent_registry,
            "reputation_ledger": ids.reputation_ledger,
            "payment_escrow": ids.payment_escrow,
            "attestation_registry": ids.attestation_registry,
        },
    }


# ── reads ───────────────────────────────────────────────────────
@router.get("/agent/{agent_id}")
async def read_agent(agent_id: str) -> dict:
    """Read an Agent from AgentRegistry.get(id)."""
    try:
        result = sc.simulate_read(
            sc.contract_ids().agent_registry,
            "get",
            [sc.sym(agent_id)],
        )
        return {"agent": result}
    except Exception as e:
        raise HTTPException(404, f"agent read failed: {e}") from e


@router.get("/reputation/{agent_id}")
async def read_reputation(agent_id: str) -> dict:
    """Read ReputationLedger.avg_bps(id) + .score(id)."""
    try:
        ids = sc.contract_ids()
        avg = sc.simulate_read(ids.reputation_ledger, "avg_bps", [sc.sym(agent_id)])
        score = sc.simulate_read(ids.reputation_ledger, "score", [sc.sym(agent_id)])
        return {"avg_bps": avg, "score": score}
    except Exception as e:
        raise HTTPException(502, f"reputation read failed: {e}") from e


@router.get("/attestation/{job_id_hex}")
async def read_attestation(job_id_hex: str) -> dict:
    """Read an on-chain Attestation by hex-encoded 16-byte job_id."""
    try:
        jid = bytes.fromhex(job_id_hex)
        if len(jid) != 16:
            raise ValueError("job_id must be 32 hex chars (16 bytes)")
        result = sc.simulate_read(
            sc.contract_ids().attestation_registry,
            "get",
            [sc.bytes16(jid)],
        )
        return {"attestation": result}
    except Exception as e:
        raise HTTPException(400, f"attestation read failed: {e}") from e


# ── writes (user signs via Freighter) ───────────────────────────
class RegisterAgentReq(BaseModel):
    owner: str = Field(..., description="G... address of the agent owner")
    agent_id: str
    name: str
    skills: list[str] = Field(default_factory=list)
    price_usdc: float


@router.post("/build/register-agent")
async def build_register_agent(req: RegisterAgentReq) -> dict:
    """Build unsigned XDR for AgentRegistry.register. Owner signs via Freighter."""
    try:
        from stellar_sdk import scval as _sv
        args = [
            sc.addr(req.owner),
            sc.sym(req.agent_id),
            _sv.to_string(req.name),
            _sv.to_vec([sc.sym(s) for s in req.skills]),
            sc.i128(sc.usdc_to_i128(req.price_usdc)),
        ]
        xdr = sc.build_invoke_xdr(
            sc.contract_ids().agent_registry,
            "register",
            args,
            source=req.owner,
        )
        return {"xdr": xdr}
    except Exception as e:
        raise HTTPException(400, f"build failed: {e}") from e


class AuthorizeReq(BaseModel):
    payer: str
    agent_id: str
    max_amount_usdc: float
    ttl_seconds: int = 300


@router.post("/build/authorize")
async def build_authorize(req: AuthorizeReq) -> dict:
    """Build unsigned XDR for PaymentEscrow.authorize (x402 pre-auth)."""
    try:
        expires_at = int(time.time()) + req.ttl_seconds
        args = [
            sc.addr(req.payer),
            sc.sym(req.agent_id),
            sc.i128(sc.usdc_to_i128(req.max_amount_usdc)),
            sc.u64(expires_at),
        ]
        xdr = sc.build_invoke_xdr(
            sc.contract_ids().payment_escrow,
            "authorize",
            args,
            source=req.payer,
        )
        return {"xdr": xdr, "expires_at": expires_at}
    except Exception as e:
        raise HTTPException(400, f"build failed: {e}") from e


class SubmitReq(BaseModel):
    signed_xdr: str


@router.post("/submit")
async def submit_signed(req: SubmitReq) -> dict:
    """Submit a Freighter-signed transaction XDR."""
    try:
        result = sc.submit_signed_xdr(req.signed_xdr)
    except Exception as e:
        raise HTTPException(400, f"submit failed: {e}") from e
    # Don't turn a FAILED tx into an HTTP error — the FE needs the hash + diagnostic.
    return result


# ── writes (backend signs with STELLAR_SIGNING_KEY) ──────────────
class ChargeReq(BaseModel):
    auth_id_hex: str  # 32 hex chars
    amount_usdc: float
    job_id_hex: str   # 32 hex chars


@router.post("/server/charge")
async def server_charge(req: ChargeReq) -> dict:
    """Backend-signed PaymentEscrow.charge (the backend is the `settler` role)."""
    if not settings.stellar_signing_key:
        raise HTTPException(503, "backend signing key not configured")
    try:
        aid = bytes.fromhex(req.auth_id_hex)
        jid = bytes.fromhex(req.job_id_hex)
        if len(aid) != 16 or len(jid) != 16:
            raise ValueError("ids must be 32 hex chars")

        from stellar_sdk import Keypair
        caller = Keypair.from_secret(settings.stellar_signing_key).public_key

        args = [
            sc.addr(caller),
            sc.bytes16(aid),
            sc.i128(sc.usdc_to_i128(req.amount_usdc)),
            sc.bytes16(jid),
        ]
        return sc.invoke_with_server_key(
            sc.contract_ids().payment_escrow,
            "charge",
            args,
        )
    except Exception as e:
        raise HTTPException(400, f"charge failed: {e}") from e


class SealReq(BaseModel):
    job_id_hex: str
    orchestrator: str  # G-address of the workflow owner
    intent_hash_hex: str  # 64 hex chars
    agents: list[str]
    receipts_hex: list[str]  # each 32 hex chars
    total_spent_usdc: float


@router.post("/server/seal")
async def server_seal(req: SealReq) -> dict:
    """Backend-signed AttestationRegistry.seal (backend is the `sealer` role)."""
    if not settings.stellar_signing_key:
        raise HTTPException(503, "backend signing key not configured")
    try:
        from stellar_sdk import Keypair, scval as _sv

        caller = Keypair.from_secret(settings.stellar_signing_key).public_key
        jid = bytes.fromhex(req.job_id_hex)
        ih = bytes.fromhex(req.intent_hash_hex)
        if len(jid) != 16 or len(ih) != 32:
            raise ValueError("bad id lengths")

        receipts = []
        for rh in req.receipts_hex:
            rb = bytes.fromhex(rh)
            if len(rb) != 16:
                raise ValueError(f"bad receipt_id: {rh}")
            receipts.append(sc.bytes16(rb))

        args = [
            sc.addr(caller),
            sc.bytes16(jid),
            sc.addr(req.orchestrator),
            sc.bytes32(ih),
            _sv.to_vec([sc.sym(a) for a in req.agents]),
            _sv.to_vec(receipts),
            sc.i128(sc.usdc_to_i128(req.total_spent_usdc)),
        ]
        return sc.invoke_with_server_key(
            sc.contract_ids().attestation_registry,
            "seal",
            args,
        )
    except Exception as e:
        raise HTTPException(400, f"seal failed: {e}") from e


# ── handy: new 16-byte id ──────────────────────────────────────
@router.get("/new-id")
async def new_id() -> dict:
    """Produce a random 16-byte id (hex) — useful for job_id / auth_id."""
    return {"id_hex": secrets.token_hex(16)}
