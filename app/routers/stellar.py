"""
/api/stellar/* — surfaces the deployed Soroban contracts to the frontend.

Read routes simulate RPC calls (no signing).
Write routes have two shapes:
  - build-*   → returns unsigned XDR for Freighter to sign
  - submit    → takes Freighter-signed XDR and broadcasts it
"""
from __future__ import annotations

import asyncio
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..config import settings
from ..security import require_api_key
from ..services import reputation_svc
from ..state import state
from ..stellar import cache as rcache
from ..stellar import client as sc

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stellar", tags=["stellar"])

# ── response models (shapes match the existing payloads exactly) ──
class NetworkInfo(BaseModel):
    network: str
    rpc_url: str
    network_passphrase: str
    admin: str
    asset: str
    asset_sac: str
    contracts: dict[str, str]


class AgentRead(BaseModel):
    agent: Any


class ReputationInfo(BaseModel):
    """Smoothed reputation for one agent (mirror of reputation_svc.RepInfo)."""

    agent_id: str
    smoothed_bps: int      # prior-smoothed mean, 0..10_000
    lower_bound_bps: int   # conservative bound used for the routing floor
    avg_bps: int           # unsmoothed decayed on-chain mean (0 = no evidence)
    count: int             # lifetime rating count
    weight: int            # decayed evidence mass, stroops
    disputed: int          # lifetime dispute count
    dispute_rate_bps: int  # disputed / count, in bps
    source: Literal["onchain", "prior"]


class ReputationBatch(BaseModel):
    """Reputation for every registered agent + the routing constants."""

    reputations: dict[str, ReputationInfo]
    floor_bps: int
    prior_bps: int


class ReputationParams(BaseModel):
    """Full parameter set of the reputation system — routing constants applied
    by the backend plus the deployed ledger's on-chain decay constants."""

    enabled: bool
    prior_bps: int                  # Bayesian prior mean, bps of the 0-100 scale
    prior_weight_usdc: float        # evidence mass of the prior, USDC
    floor_bps: int                  # routing floor on the Wilson lower bound
    max_rating_weight_usdc: float   # per-rating weight cap
    read_ttl_seconds: float         # cache TTL for on-chain rep_state reads
    wilson_z: float                 # z of the one-sided lower confidence bound
    epoch_seconds: int              # on-chain decay epoch length
    decay_bps_per_epoch: int        # evidence retained per epoch, bps
    max_decay_epochs: int           # full-forget horizon
    contract_id: str                # deployed ReputationLedger id ("" if unset)
    network: str


class AttestationRead(BaseModel):
    attestation: Any


class XdrResponse(BaseModel):
    xdr: str


class AuthorizeXdrResponse(BaseModel):
    xdr: str
    expires_at: int


class NewIdResponse(BaseModel):
    id_hex: str


# FE polls the read routes; identical simulate calls within this window are
# served from a tiny in-process cache instead of re-hitting Soroban RPC.
READ_TTL_SECONDS = 3.0


# ── meta ────────────────────────────────────────────────────────
@router.get("/network", response_model=NetworkInfo)
async def network() -> NetworkInfo:
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
@router.get("/agent/{agent_id}", response_model=AgentRead)
async def read_agent(agent_id: str) -> AgentRead:
    """Read an Agent from AgentRegistry.get(id)."""
    try:
        async def _fetch():
            return await asyncio.to_thread(
                sc.simulate_read,
                sc.contract_ids().agent_registry,
                "get",
                [sc.sym(agent_id)],
            )

        result = await rcache.get_or_set(f"agent:{agent_id}", READ_TTL_SECONDS, _fetch)
        return {"agent": result}
    except Exception as e:
        logger.exception("agent read failed for %s", agent_id)
        raise HTTPException(404, "agent_read_failed") from e


@router.get("/reputation", response_model=ReputationBatch)
async def read_reputations() -> ReputationBatch:
    """Smoothed reputation for every registered agent, plus the routing
    floor and prior. Never fails: agents without on-chain evidence (or with
    the chain unreachable) come back as the prior, marked source="prior".
    """
    infos = await reputation_svc.fetch_reps([a.id for a in state.list_agents()])
    return {
        "reputations": {aid: info.model_dump() for aid, info in infos.items()},
        "floor_bps": settings.reputation_floor_bps,
        "prior_bps": settings.reputation_prior_bps,
    }


# Declared BEFORE the dynamic /reputation/{agent_id} route — FastAPI matches
# routes in declaration order, so this must come first or "params" would be
# read as an agent id.
@router.get("/reputation/params", response_model=ReputationParams)
async def reputation_params() -> ReputationParams:
    """The reputation system's parameter set — pure config, no RPC call."""
    return {
        "enabled": settings.reputation_enabled,
        "prior_bps": settings.reputation_prior_bps,
        "prior_weight_usdc": settings.reputation_prior_weight_usdc,
        "floor_bps": settings.reputation_floor_bps,
        "max_rating_weight_usdc": settings.reputation_max_rating_weight_usdc,
        "read_ttl_seconds": settings.reputation_read_ttl_seconds,
        "wilson_z": reputation_svc.WILSON_Z,
        "epoch_seconds": reputation_svc.EPOCH_SECONDS,
        "decay_bps_per_epoch": reputation_svc.DECAY_BPS_PER_EPOCH,
        "max_decay_epochs": reputation_svc.MAX_DECAY_EPOCHS,
        "contract_id": settings.stellar_reputation_ledger,
        "network": settings.stellar_network,
    }


@router.get("/reputation/{agent_id}", response_model=ReputationInfo)
async def read_reputation(agent_id: str) -> ReputationInfo:
    """Smoothed reputation for one agent — cached ReputationLedger.rep_state
    read with Bayesian prior smoothing; prior fallback on any failure.
    """
    info = await reputation_svc.fetch_rep(agent_id)
    return info.model_dump()


@router.get("/attestation/{job_id_hex}", response_model=AttestationRead)
async def read_attestation(job_id_hex: str) -> AttestationRead:
    """Read an on-chain Attestation by hex-encoded 16-byte job_id."""
    try:
        jid = bytes.fromhex(job_id_hex)
        if len(jid) != 16:
            raise ValueError("job_id must be 32 hex chars (16 bytes)")

        async def _fetch():
            return await asyncio.to_thread(
                sc.simulate_read,
                sc.contract_ids().attestation_registry,
                "get",
                [sc.bytes16(jid)],
            )

        result = await rcache.get_or_set(
            f"attestation:{job_id_hex}", READ_TTL_SECONDS, _fetch
        )
        return {"attestation": result}
    except Exception as e:
        logger.exception("attestation read failed for %s", job_id_hex)
        raise HTTPException(400, "attestation_read_failed") from e


# ── writes (user signs via Freighter) ───────────────────────────
class RegisterAgentReq(BaseModel):
    owner: str = Field(
        ..., pattern=r"^G[A-Z2-7]{55}$", description="G... address of the agent owner"
    )
    agent_id: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=100)
    skills: list[str] = Field(default_factory=list, max_length=16)
    price_usdc: float = Field(..., gt=0, le=10_000, allow_inf_nan=False)


@router.post("/build/register-agent", response_model=XdrResponse)
async def build_register_agent(req: RegisterAgentReq) -> XdrResponse:
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
        xdr = await asyncio.to_thread(
            sc.build_invoke_xdr,
            sc.contract_ids().agent_registry,
            "register",
            args,
            source=req.owner,
        )
        return {"xdr": xdr}
    except Exception as e:
        logger.exception("register-agent build failed")
        raise HTTPException(400, "build_failed") from e


class AuthorizeReq(BaseModel):
    payer: str = Field(..., pattern=r"^G[A-Z2-7]{55}$")
    agent_id: str = Field(..., min_length=1, max_length=32)
    max_amount_usdc: float = Field(..., gt=0, le=10_000, allow_inf_nan=False)
    ttl_seconds: int = Field(default=300, ge=30, le=3600)


@router.post("/build/authorize", response_model=AuthorizeXdrResponse)
async def build_authorize(req: AuthorizeReq) -> AuthorizeXdrResponse:
    """Build unsigned XDR for PaymentEscrow.authorize (x402 pre-auth)."""
    try:
        expires_at = int(time.time()) + req.ttl_seconds
        args = [
            sc.addr(req.payer),
            sc.sym(req.agent_id),
            sc.i128(sc.usdc_to_i128(req.max_amount_usdc)),
            sc.u64(expires_at),
        ]
        xdr = await asyncio.to_thread(
            sc.build_invoke_xdr,
            sc.contract_ids().payment_escrow,
            "authorize",
            args,
            source=req.payer,
        )
        return {"xdr": xdr, "expires_at": expires_at}
    except Exception as e:
        logger.exception("authorize build failed")
        raise HTTPException(400, "build_failed") from e


class SubmitReq(BaseModel):
    signed_xdr: str


@router.post("/submit")
async def submit_signed(req: SubmitReq) -> dict:
    """Submit a Freighter-signed transaction XDR."""
    try:
        result = await asyncio.to_thread(sc.submit_signed_xdr, req.signed_xdr)
    except Exception as e:
        logger.exception("signed xdr submit failed")
        raise HTTPException(400, "submit_failed") from e
    # Don't turn a FAILED tx into an HTTP error — the FE needs the hash + diagnostic.
    return result


# ── writes (backend signs with STELLAR_SIGNING_KEY) ──────────────
class ChargeReq(BaseModel):
    auth_id_hex: str = Field(..., pattern=r"^[0-9a-fA-F]{32}$")
    amount_usdc: float = Field(..., gt=0, le=10_000, allow_inf_nan=False)
    job_id_hex: str = Field(..., pattern=r"^[0-9a-fA-F]{32}$")


@router.post("/server/charge", dependencies=[Depends(require_api_key)])
async def server_charge(req: ChargeReq) -> dict:
    """Backend-signed PaymentEscrow.charge (the backend is the `settler` role)."""
    if not settings.stellar_signing_key:
        raise HTTPException(503, "backend signing key not configured")
    if not (0 < req.amount_usdc <= settings.max_charge_usdc):
        raise HTTPException(400, "amount_exceeds_charge_cap")
    try:
        aid = bytes.fromhex(req.auth_id_hex)
        jid = bytes.fromhex(req.job_id_hex)
        if len(aid) != 16 or len(jid) != 16:
            raise ValueError("ids must be 32 hex chars")

        caller = sc._signer_keypair().public_key

        args = [
            sc.addr(caller),
            sc.bytes16(aid),
            sc.i128(sc.usdc_to_i128(req.amount_usdc)),
            sc.bytes16(jid),
        ]
        return await asyncio.to_thread(
            sc.invoke_with_server_key,
            sc.contract_ids().payment_escrow,
            "charge",
            args,
        )
    except Exception as e:
        logger.exception("server charge failed")
        raise HTTPException(400, "charge_failed") from e


class SealReq(BaseModel):
    job_id_hex: str = Field(..., pattern=r"^[0-9a-fA-F]{32}$")
    orchestrator: str = Field(
        ..., pattern=r"^G[A-Z2-7]{55}$"
    )  # G-address of the workflow owner
    intent_hash_hex: str = Field(..., pattern=r"^[0-9a-fA-F]{64}$")
    agents: list[str] = Field(..., max_length=32)
    receipts_hex: list[str] = Field(..., max_length=32)  # each 32 hex chars
    total_spent_usdc: float = Field(..., ge=0, le=100_000, allow_inf_nan=False)


@router.post("/server/seal", dependencies=[Depends(require_api_key)])
async def server_seal(req: SealReq) -> dict:
    """Backend-signed AttestationRegistry.seal (backend is the `sealer` role)."""
    if not settings.stellar_signing_key:
        raise HTTPException(503, "backend signing key not configured")
    try:
        from stellar_sdk import scval as _sv

        caller = sc._signer_keypair().public_key
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
        return await asyncio.to_thread(
            sc.invoke_with_server_key,
            sc.contract_ids().attestation_registry,
            "seal",
            args,
        )
    except Exception as e:
        logger.exception("server seal failed")
        raise HTTPException(400, "seal_failed") from e


# ── handy: new 16-byte id ──────────────────────────────────────
@router.get("/new-id", response_model=NewIdResponse)
async def new_id() -> NewIdResponse:
    """Produce a random 16-byte id (hex) — useful for job_id / auth_id."""
    return {"id_hex": secrets.token_hex(16)}
