"""Reputation wiring tests — read endpoints, plan stamping, floor routing,
and the settler's best-effort rating submission."""
from __future__ import annotations

import asyncio
import secrets
import time

from app.config import settings
from app.schemas import Plan, PlanStep, StoredPlan, Task
from app.seed import seed_registry
from app.services import execution_svc, orchestrator_svc
from app.services.reputation_svc import RepInfo
from app.state import state
from app.stellar import client as sc


def _info(agent_id: str, *, smoothed: int, lower: int) -> RepInfo:
    return RepInfo(
        agent_id=agent_id,
        smoothed_bps=smoothed,
        lower_bound_bps=lower,
        avg_bps=smoothed,
        count=3,
        weight=5 * 10_000_000,
        disputed=0,
        dispute_rate_bps=0,
        source="onchain",
    )


# ── read endpoints ──────────────────────────────────────────────


def test_reputation_batch_covers_every_seeded_agent(client):
    r = client.get("/api/stellar/reputation")
    assert r.status_code == 200
    body = r.json()

    seeded = {a.id for a in state.list_agents()}
    assert seeded, "registry must be seeded"
    assert set(body["reputations"]) == seeded
    assert body["floor_bps"] == settings.reputation_floor_bps
    assert body["prior_bps"] == settings.reputation_prior_bps
    # Hermetic tests have no chain configured → every entry is the prior.
    for info in body["reputations"].values():
        assert info["source"] == "prior"
        assert info["smoothed_bps"] == settings.reputation_prior_bps


def test_reputation_single_agent_shape(client):
    r = client.get("/api/stellar/reputation/agt_01h8")
    assert r.status_code == 200
    body = r.json()
    assert body["agent_id"] == "agt_01h8"
    assert body["source"] == "prior"
    assert body["smoothed_bps"] == settings.reputation_prior_bps
    assert body["count"] == 0
    assert body["lower_bound_bps"] >= settings.reputation_floor_bps


# ── decompose stamping ──────────────────────────────────────────


def test_kit_decompose_stamps_reputation_fields(client):
    r = client.post(
        "/api/orchestrator/decompose", json={"intent": "tetris game in html"}
    )
    assert r.status_code == 200
    steps = r.json()["steps"]
    assert steps
    for step in steps:
        assert step["rep_bps"] == settings.reputation_prior_bps
        assert step["rep_source"] == "prior"


# ── routing floor ───────────────────────────────────────────────


def test_floor_omits_low_reputation_agent():
    seed_registry()
    agents = state.list_agents()
    reps = {a.id: _info(a.id, smoothed=8000, lower=8000) for a in agents}
    bad = agents[0].id
    reps[bad] = _info(bad, smoothed=3000, lower=1000)  # below the 5500 floor

    fragment = orchestrator_svc._registry_prompt_fragment(reps)

    assert f"id={bad} " not in fragment
    for a in agents[1:]:
        assert f"id={a.id} " in fragment


def test_floor_never_shrinks_below_three_agents():
    seed_registry()
    agents = state.list_agents()
    # Every agent fails the floor, with distinct smoothed scores.
    reps = {
        a.id: _info(a.id, smoothed=1000 + i * 10, lower=100)
        for i, a in enumerate(agents)
    }

    fragment = orchestrator_svc._registry_prompt_fragment(reps)

    listed = [ln for ln in fragment.splitlines() if ln.startswith("- id=")]
    assert len(listed) == 3
    top3 = sorted(agents, key=lambda a: reps[a.id].smoothed_bps, reverse=True)[:3]
    for a in top3:
        assert f"id={a.id} " in fragment


# ── settler rating submission ──────────────────────────────────


def test_submit_ratings_is_best_effort(monkeypatch):
    monkeypatch.setattr(settings, "reputation_enabled", True)
    monkeypatch.setattr(settings, "stellar_reputation_ledger", "CFAKELEDGER")
    monkeypatch.setattr(settings, "stellar_signing_key", "SFAKEKEY")

    calls: list[tuple] = []

    def fake_submit(agent_id, job_id, rating, weight, payer, kind="auto"):
        calls.append((agent_id, job_id, rating, weight, payer, kind))
        if agent_id == "agt_bad":
            raise RuntimeError("sequence collision")
        return {"hash": "deadbeefcafe0123", "status": "SUCCESS"}

    monkeypatch.setattr(sc, "submit_rating", fake_submit)

    steps = [
        PlanStep(
            agent_id="agt_ok",
            agent_name="w.ok",
            rationale="r",
            est_price_usdc=0.05,
            est_eta_seconds=1.0,
        ),
        PlanStep(
            agent_id="agt_bad",
            agent_name="w.bad",
            rationale="r",
            est_price_usdc=0.05,
            est_eta_seconds=1.0,
        ),
    ]
    plan = StoredPlan(
        id="pln_test",
        intent="test intent",
        plan=Plan(steps=steps),
        total_usdc=0.1,
        total_eta=2.0,
    )
    task_id = f"tsk_{secrets.token_hex(3)}"
    state.add_task(
        Task(
            id=task_id,
            intent="test intent",
            agents=2,
            spent=0.0,
            status="running",
            started="just now",
        )
    )
    # Context keys are worker names — w.ok delivered a clean artifact (95),
    # w.bad has no output (20) and its submit raises.
    context = {"w.ok": {"artifact": {"title": "x"}, "critic_violations": []}}

    # Must never raise, even with a failing submit in the middle.
    asyncio.run(
        execution_svc._submit_ratings(
            task_id,
            time.monotonic(),
            plan,
            context,
            payer="G" + "A" * 55,
            job_id=b"\x01" * 16,
        )
    )

    assert len(calls) == 2  # one submit per plan step
    assert all(c[1] == b"\x01" * 16 for c in calls)
    assert all(c[5] == "auto" for c in calls)
    assert calls[0][2] == 95 and calls[1][2] == 20

    lines = state.traces[task_id]
    proofs = [ln for ln in lines if ln.level == "proof"]
    errors = [ln for ln in lines if ln.level == "error"]
    assert len(proofs) == 1
    assert "w.ok rated 95/100" in proofs[0].msg
    assert len(errors) == 1
    assert "reputation submit failed for w.bad" in errors[0].msg


def test_submit_ratings_skips_when_not_configured(monkeypatch):
    # Hermetic default: no signing key → the gate must short-circuit
    # without touching the stellar client at all.
    monkeypatch.setattr(settings, "reputation_enabled", True)
    monkeypatch.setattr(settings, "stellar_reputation_ledger", "CFAKELEDGER")
    monkeypatch.setattr(settings, "stellar_signing_key", "")

    def boom(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("submit_rating called despite missing key")

    monkeypatch.setattr(sc, "submit_rating", boom)

    plan = StoredPlan(
        id="pln_skip",
        intent="x",
        plan=Plan(
            steps=[
                PlanStep(
                    agent_id="agt_ok",
                    agent_name="w.ok",
                    rationale="r",
                    est_price_usdc=0.01,
                    est_eta_seconds=1.0,
                )
            ]
        ),
        total_usdc=0.01,
        total_eta=1.0,
    )
    asyncio.run(
        execution_svc._submit_ratings(
            "tsk_none",
            time.monotonic(),
            plan,
            {},
            payer="G" + "A" * 55,
            job_id=b"\x02" * 16,
        )
    )
    assert "tsk_none" not in state.traces
