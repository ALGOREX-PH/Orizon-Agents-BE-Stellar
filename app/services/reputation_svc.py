"""
Reputation service — Bayesian-smoothed, evidence-weighted agent reputation.

Division of labour (mirrors ERC-8004: raw evidence on-chain, aggregation off):

  - The ReputationLedger contract stores decayed, value-weighted rating
    evidence per agent (`rep_state` → sum_w / weight / count / disputed).
  - This service applies the Bayesian prior (Jøsang-style beta smoothing),
    derives a conservative Wilson-style lower bound for the routing floor,
    and computes the synthetic per-step rating the settler submits after a
    settled workflow.

Score semantics: ratings are 0–100; every *_bps value here is basis points
of that scale (0..10_000). Weights are USDC in stroops (7 decimals) — a
rating earned on a 0.054 USDC step carries less evidence than one earned on
an 0.180 USDC step, so reputation is a record of settled economic history,
not a count of clicks.

Cold start: with no on-chain evidence the smoothed score IS the prior
(default 7000 = 3.5/5) and the lower bound still clears the default floor —
permissionless newcomers are routable, while a few heavily-weighted bad
ratings sink an agent below the floor quickly. Failures never fabricate
evidence: if the chain is unreachable the caller gets the prior, marked
`source="prior"`.
"""
from __future__ import annotations

import asyncio
import logging
import math
from typing import Any, Literal, Optional

from pydantic import BaseModel

from ..config import settings

logger = logging.getLogger(__name__)

STROOPS_PER_USDC = 10_000_000
# One-sided ~84% confidence. Deliberately gentle: paired with the prior mass
# it lets a prior-only newcomer clear the floor, while real negative evidence
# still drags the bound down fast.
WILSON_Z = 1.0

RepSource = Literal["onchain", "prior"]


class RepInfo(BaseModel):
    """Aggregated reputation for one agent, ready for routing and display."""

    agent_id: str
    smoothed_bps: int      # prior-smoothed mean, 0..10_000
    lower_bound_bps: int   # conservative bound used for the routing floor
    avg_bps: int           # unsmoothed decayed on-chain mean (0 = no evidence)
    count: int             # lifetime rating count
    weight: int            # decayed evidence mass, stroops
    disputed: int          # lifetime dispute count
    dispute_rate_bps: int  # disputed / count, in bps
    source: RepSource


def prior_weight_stroops() -> int:
    return round(settings.reputation_prior_weight_usdc * STROOPS_PER_USDC)


def smoothed_bps(sum_w: int, weight: int) -> int:
    """Bayesian smoothed mean: prior mass pulls sparse evidence to the prior."""
    pw = prior_weight_stroops()
    den = pw + weight
    if den <= 0:
        return settings.reputation_prior_bps
    num = pw * settings.reputation_prior_bps + sum_w
    return max(0, min(10_000, num // den))


def lower_bound_bps(mean_bps: int, weight: int) -> int:
    """Wilson-style lower bound on the smoothed mean.

    Effective sample size counts prior mass plus on-chain evidence in units
    of one-USDC jobs, so confidence grows with settled value, not raw count.
    """
    n = (prior_weight_stroops() + max(weight, 0)) / STROOPS_PER_USDC
    if n <= 0:
        return 0
    p = min(max(mean_bps / 10_000, 0.0), 1.0)
    lb = p - WILSON_Z * math.sqrt(p * (1.0 - p) / n)
    return max(0, min(10_000, round(lb * 10_000)))


def passes_floor(info: Optional[RepInfo]) -> bool:
    """Routing-floor check on the conservative lower bound."""
    if info is None:
        return True
    return info.lower_bound_bps >= settings.reputation_floor_bps


def rating_weight_stroops(step_price_usdc: float) -> int:
    """Evidence weight of one rating: the step's settled value, capped."""
    capped = min(max(step_price_usdc, 0.0), settings.reputation_max_rating_weight_usdc)
    return max(1, round(capped * STROOPS_PER_USDC))


def synthetic_rating(
    step_output: Optional[dict[str, Any]],
    step_price_usdc: float,
) -> tuple[int, int]:
    """Derive the settler's synthetic rating for one settled step.

    Returns (rating_0_to_100, weight_stroops). The rating is built from
    verifiable workflow signals (did the worker produce output, did it ship
    an artifact, did the critic find violations) — validation-gated
    reputation rather than opinion. Baked kit artifacts are deterministic
    and pre-validated by design, so they earn a fixed high score.
    """
    weight = rating_weight_stroops(step_price_usdc)

    if not step_output:
        # Timed out / raised — settled money for no delivered work.
        return 20, weight

    if step_output.get("source") == "baked":
        return 95, weight

    rating = 70
    if step_output.get("artifact"):
        rating += 15
    violations = step_output.get("critic_violations") or step_output.get(
        "validator_violations"
    )
    if isinstance(violations, list):
        rating += 10 if not violations else -3 * min(len(violations), 10)
    return max(0, min(100, rating)), weight


def _prior_info(agent_id: str) -> RepInfo:
    prior = settings.reputation_prior_bps
    return RepInfo(
        agent_id=agent_id,
        smoothed_bps=prior,
        lower_bound_bps=lower_bound_bps(prior, 0),
        avg_bps=0,
        count=0,
        weight=0,
        disputed=0,
        dispute_rate_bps=0,
        source="prior",
    )


def _info_from_state(agent_id: str, state: dict[str, Any]) -> RepInfo:
    sum_w = int(state.get("sum_w", 0))
    weight = int(state.get("weight", 0))
    count = int(state.get("count", 0))
    disputed = int(state.get("disputed", 0))
    smoothed = smoothed_bps(sum_w, weight)
    return RepInfo(
        agent_id=agent_id,
        smoothed_bps=smoothed,
        lower_bound_bps=lower_bound_bps(smoothed, weight),
        avg_bps=(sum_w // weight) if weight > 0 else 0,
        count=count,
        weight=weight,
        disputed=disputed,
        dispute_rate_bps=(disputed * 10_000 // count) if count > 0 else 0,
        source="onchain",
    )


async def fetch_rep(agent_id: str) -> RepInfo:
    """Read one agent's decayed rep_state from chain; prior on any failure."""
    if not settings.reputation_enabled or not settings.stellar_reputation_ledger:
        return _prior_info(agent_id)

    from ..stellar import cache as rcache
    from ..stellar import client as sc

    async def _read() -> dict[str, Any]:
        return await asyncio.to_thread(
            sc.simulate_read,
            sc.contract_ids().reputation_ledger,
            "rep_state",
            [sc.sym(agent_id)],
        )

    try:
        state = await rcache.get_or_set(
            f"repstate:{agent_id}", settings.reputation_read_ttl_seconds, _read
        )
        if not isinstance(state, dict):
            return _prior_info(agent_id)
        return _info_from_state(agent_id, state)
    except Exception as e:
        logger.debug("reputation read failed for %s: %s", agent_id, e)
        return _prior_info(agent_id)


async def fetch_reps(
    agent_ids: list[str], timeout_seconds: float = 2.5
) -> dict[str, RepInfo]:
    """Concurrent reads for a set of agents, bounded by one overall timeout.

    Never raises: on timeout or error every missing agent falls back to the
    prior, so decompose latency is capped and routing always has a score.
    """
    try:
        infos = await asyncio.wait_for(
            asyncio.gather(*(fetch_rep(a) for a in agent_ids)),
            timeout=timeout_seconds,
        )
        return {info.agent_id: info for info in infos}
    except (asyncio.TimeoutError, Exception) as e:  # noqa: BLE001
        logger.debug("reputation batch read degraded to prior: %s", e)
        return {a: _prior_info(a) for a in agent_ids}
