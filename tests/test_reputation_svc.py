"""Unit tests for the reputation smoothing service."""
from __future__ import annotations

import asyncio

from app.config import settings
from app.services import reputation_svc as rep

USDC = rep.STROOPS_PER_USDC


def _sum_w(mean_bps: int, weight: int) -> int:
    """Build a sum_w accumulator that yields the given raw mean."""
    return mean_bps * weight


def test_smoothed_is_prior_with_no_evidence():
    assert rep.smoothed_bps(0, 0) == settings.reputation_prior_bps


def test_smoothed_moves_toward_evidence_as_weight_grows():
    prior = settings.reputation_prior_bps
    light = rep.smoothed_bps(_sum_w(9500, 1 * USDC), 1 * USDC)
    heavy = rep.smoothed_bps(_sum_w(9500, 100 * USDC), 100 * USDC)
    assert prior < light < heavy < 9500 or heavy == 9500
    # Heavy evidence should sit within 5% of the raw mean.
    assert heavy > 9000


def test_heavy_negative_evidence_sinks_below_floor():
    # 20 USDC of settled work rated 10/100 must not survive the floor.
    weight = 20 * USDC
    smoothed = rep.smoothed_bps(_sum_w(1000, weight), weight)
    lb = rep.lower_bound_bps(smoothed, weight)
    assert lb < settings.reputation_floor_bps


def test_lower_bound_below_mean_and_tightens_with_evidence():
    smoothed = rep.smoothed_bps(_sum_w(8000, 5 * USDC), 5 * USDC)
    lb_small = rep.lower_bound_bps(smoothed, 5 * USDC)
    lb_big = rep.lower_bound_bps(smoothed, 500 * USDC)
    assert lb_small < smoothed
    assert lb_small < lb_big <= smoothed


def test_prior_only_agent_passes_default_floor():
    # Cold start: a brand-new agent must be routable.
    info = rep._prior_info("agt_new")
    assert info.source == "prior"
    assert rep.passes_floor(info)


def test_passes_floor_none_is_permissive():
    assert rep.passes_floor(None)


def test_synthetic_rating_baked_artifact():
    rating, weight = rep.synthetic_rating({"source": "baked"}, 0.054)
    assert rating == 95
    assert weight == round(0.054 * USDC)


def test_synthetic_rating_failed_step():
    rating, weight = rep.synthetic_rating(None, 0.18)
    assert rating == 20
    assert weight == round(0.18 * USDC)


def test_synthetic_rating_clean_artifact_beats_violations():
    clean, _ = rep.synthetic_rating(
        {"artifact": {"title": "x"}, "critic_violations": []}, 0.05
    )
    dirty, _ = rep.synthetic_rating(
        {"artifact": {"title": "x"}, "critic_violations": ["a", "b", "c"]}, 0.05
    )
    assert clean == 95
    assert dirty < clean
    assert 0 <= dirty <= 100


def test_rating_weight_capped_and_floored():
    cap = settings.reputation_max_rating_weight_usdc
    assert rep.rating_weight_stroops(cap * 10) == round(cap * USDC)
    assert rep.rating_weight_stroops(0.0) == 1


def test_fetch_rep_prior_fallback_without_contract():
    # Hermetic env has no reputation ledger id → prior path, no RPC call.
    info = asyncio.run(rep.fetch_rep("agt_01h8"))
    assert info.source == "prior"
    assert info.smoothed_bps == settings.reputation_prior_bps
    assert info.count == 0


def test_fetch_reps_returns_entry_per_agent():
    ids = ["agt_01h8", "agt_02k2", "agt_03d9"]
    infos = asyncio.run(rep.fetch_reps(ids))
    assert set(infos) == set(ids)
    assert all(i.source == "prior" for i in infos.values())


def test_info_from_state_math():
    weight = 10 * USDC
    info = rep._info_from_state(
        "agt_04m1",
        {"sum_w": _sum_w(9000, weight), "weight": weight, "count": 4, "disputed": 1},
    )
    assert info.source == "onchain"
    assert info.avg_bps == 9000
    assert settings.reputation_prior_bps < info.smoothed_bps < 9000
    assert info.dispute_rate_bps == 2500
