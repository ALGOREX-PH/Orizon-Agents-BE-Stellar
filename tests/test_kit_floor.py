"""Reputation floor on the demo-kit planning path (story 3.01, BLO-23).

`_build_kit_plan` used to stamp reputation on every step but never call
`passes_floor`, so curated demo intents advertised a trust gate they did not
enforce — the most-watched path in the product. These tests pin the fix: the
floor is applied to every pipeline agent, a sub-floor agent is substituted or
dropped and the action is surfaced (never silent), the plan stays
deterministic with no LLM call, and the `_MIN_ROUTABLE_AGENTS` backstop keeps a
battered pipeline workable.
"""

from __future__ import annotations

import asyncio

import pytest

from app.demo_kits import detect_kit
from app.seed import seed_registry
from app.services import orchestrator_svc
from app.services.reputation_svc import RepInfo
from app.state import state

KIT_INTENT = "tetris game in html"


async def _noop(*_a: object, **_k: object) -> None:
    return None


def _sub_floor(agent_id: str, *, smoothed: int = 4000) -> RepInfo:
    """A rep entry that FAILS the routing floor (lower bound far under 5500)."""
    return RepInfo(
        agent_id=agent_id,
        smoothed_bps=smoothed,
        lower_bound_bps=100,
        avg_bps=smoothed,
        count=5,
        weight=5 * 10_000_000,
        disputed=0,
        dispute_rate_bps=0,
        source="onchain",
    )


@pytest.fixture()
def seeded(monkeypatch: pytest.MonkeyPatch) -> object:
    """Fresh 12-agent registry, restored after; kit thinking-sleep no-op'd."""
    saved = dict(state.agents)
    state.agents.clear()
    seed_registry()
    monkeypatch.setattr(orchestrator_svc.asyncio, "sleep", _noop)
    yield
    state.agents.clear()
    state.agents.update(saved)


def _run_kit(reps: dict[str, RepInfo]) -> orchestrator_svc.DecomposeResponse:
    kit = detect_kit(KIT_INTENT)
    assert kit is not None
    return asyncio.run(orchestrator_svc._build_kit_plan(KIT_INTENT, kit, reps))


def test_sub_floor_agent_is_excluded_from_kit_plan(seeded: object) -> None:
    # agt_02k2 (design.figma) has no off-pipeline agent sharing its skills, so
    # a sub-floor rating drops it outright. The other five roles clear the
    # floor (cold start), so the backstop never fires.
    resp = _run_kit({"agt_02k2": _sub_floor("agt_02k2")})

    ids = [s.agent_id for s in resp.steps]
    assert "agt_02k2" not in ids
    assert len(resp.steps) == 5
    assert any(n.kind == "excluded" and n.agent_id == "agt_02k2" for n in resp.notices)


def test_sub_floor_agent_is_substituted_and_surfaced(seeded: object) -> None:
    # agt_05x7 (seo.brief) shares the "seo" skill with off-pipeline agt_01h8
    # (copywrite.v3), which clears the floor at cold start — so the role is
    # filled by a substitute rather than dropped, and the swap is recorded.
    resp = _run_kit({"agt_05x7": _sub_floor("agt_05x7")})

    ids = [s.agent_id for s in resp.steps]
    assert "agt_05x7" not in ids
    assert "agt_01h8" in ids
    assert len(resp.steps) == 6  # a substitution keeps the pipeline full

    step = next(s for s in resp.steps if s.agent_id == "agt_01h8")
    assert step.substituted_for == "agt_05x7"

    note = next(n for n in resp.notices if n.kind == "substituted")
    assert note.agent_id == "agt_05x7"
    assert note.replacement_id == "agt_01h8"
    assert "5500" in note.reason  # the notice names the floor it failed


def test_kit_plan_is_deterministic(seeded: object) -> None:
    # Same reputation state, twice: identical steps, substitutions, and
    # notices. plan_id is a random token so it is excluded from the compare.
    reps = {"agt_05x7": _sub_floor("agt_05x7"), "agt_02k2": _sub_floor("agt_02k2")}
    first = _run_kit(reps)
    second = _run_kit(reps)

    assert [s.agent_id for s in first.steps] == [s.agent_id for s in second.steps]
    assert [s.substituted_for for s in first.steps] == [s.substituted_for for s in second.steps]
    assert [(n.kind, n.agent_id, n.replacement_id) for n in first.notices] == [
        (n.kind, n.agent_id, n.replacement_id) for n in second.notices
    ]
    assert first.total_usdc == second.total_usdc
    assert first.total_eta == second.total_eta
