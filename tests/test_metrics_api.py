"""API tests for /api/metrics/overview: completion computed over terminal
tasks only, trust sourced from live reputation with a seeded fallback, and a
throughput sparkline free of the retained-count point."""

from __future__ import annotations

import pytest

from app.main import app
from app.routers import metrics as metrics_router
from app.schemas import Task
from app.security import RateLimitMiddleware
from app.services.reputation_svc import RepInfo
from app.state import state


def _clear_rate_limiter() -> None:
    """Drop the app-wide sliding-window hit table. The limiter instance lives
    for the whole pytest process, so this file's extra requests would otherwise
    eat into the shared per-minute budget and 429 later test files."""
    node = getattr(app, "middleware_stack", None)
    while node is not None and not isinstance(node, RateLimitMiddleware):
        node = getattr(node, "app", None)
    if node is not None:
        node._hits.clear()


@pytest.fixture(autouse=True)
def budget_neutral_rate_limit():
    _clear_rate_limiter()
    yield
    _clear_rate_limiter()


@pytest.fixture(autouse=True)
def clean_tasks():
    saved_tasks = dict(state.tasks)
    saved_order = list(state.task_order)
    state.tasks.clear()
    state.task_order.clear()
    yield
    state.tasks.clear()
    state.task_order.clear()
    state.tasks.update(saved_tasks)
    state.task_order.extend(saved_order)


def _add_tasks(statuses: list[str]) -> None:
    for i, status in enumerate(statuses):
        state.add_task(Task(id=f"mt{i}", intent="demo", agents=1, spent=0.0, status=status, started="just now"))


def _info(agent_id: str, smoothed_bps: int, source: str) -> RepInfo:
    onchain = source == "onchain"
    return RepInfo(
        agent_id=agent_id,
        smoothed_bps=smoothed_bps,
        lower_bound_bps=0,
        avg_bps=smoothed_bps if onchain else 0,
        count=1 if onchain else 0,
        weight=10_000_000 if onchain else 0,
        disputed=0,
        dispute_rate_bps=0,
        source=source,
    )


def _fake_reps(source: str, smoothed_bps: int):
    async def fake(agent_ids: list[str], timeout_seconds: float = 2.5) -> dict[str, RepInfo]:
        return {a: _info(a, smoothed_bps, source) for a in agent_ids}

    return fake


# ── (a) completion over terminal tasks only ─────────────────────
def test_completion_counts_terminal_tasks_only(client):
    _add_tasks(["complete", "failed", "running", "running", "pending"])
    r = client.get("/api/metrics/overview")
    assert r.status_code == 200
    # 1 complete of 2 decided; the 3 undecided tasks must not drag the rate.
    assert r.json()["avg_completion"] == 0.5


def test_completion_falls_back_when_no_terminal_tasks(client):
    _add_tasks(["running", "pending"])
    assert client.get("/api/metrics/overview").json()["avg_completion"] == 0.942


def test_completion_falls_back_when_no_tasks(client):
    assert client.get("/api/metrics/overview").json()["avg_completion"] == 0.942


# ── (b) trust sourced from live reputation ──────────────────────
def test_avg_trust_sourced_from_onchain_reputation(client, monkeypatch):
    monkeypatch.setattr("app.services.reputation_svc.fetch_reps", _fake_reps("onchain", 9000))
    assert client.get("/api/metrics/overview").json()["avg_trust"] == 4.5


def test_avg_trust_averages_only_onchain_evidence(client, monkeypatch):
    async def fake(agent_ids: list[str], timeout_seconds: float = 2.5) -> dict[str, RepInfo]:
        infos = {a: _info(a, 7000, "prior") for a in agent_ids}
        infos[agent_ids[0]] = _info(agent_ids[0], 8000, "onchain")
        return infos

    monkeypatch.setattr("app.services.reputation_svc.fetch_reps", fake)
    # The flat prior of unrated agents is not evidence — only the rated
    # agent's smoothed score (8000 bps → 4.0) contributes.
    assert client.get("/api/metrics/overview").json()["avg_trust"] == 4.0


def test_avg_trust_falls_back_to_seeded_average_when_reads_degrade(client, monkeypatch):
    monkeypatch.setattr("app.services.reputation_svc.fetch_reps", _fake_reps("prior", 7000))
    agents = state.list_agents()
    seeded = round(sum(a.rep for a in agents) / len(agents), 2)
    body = client.get("/api/metrics/overview").json()
    assert body["avg_trust"] == seeded
    # ...and never the flat 3.5 prior presented as measured trust.
    assert body["avg_trust"] != 3.5


# ── (c) throughput sparkline ────────────────────────────────────
def test_throughput_has_no_retained_count_point(client):
    _add_tasks(["complete"] * 30)
    body = client.get("/api/metrics/overview").json()
    # The retained-task count (monotonic to the store cap) is not a rate and
    # is never appended to the rate sparkline.
    assert body["throughput"] == metrics_router.DEMO_BASELINE_THROUGHPUT
    assert len(body["throughput"]) == len(metrics_router.DEMO_BASELINE_THROUGHPUT)


def test_overview_response_shape_is_stable(client):
    body = client.get("/api/metrics/overview").json()
    assert set(body) == {
        "agents_online",
        "tasks_per_sec",
        "avg_completion",
        "avg_trust",
        "throughput",
        "skills",
    }
    assert all(isinstance(p, int) for p in body["throughput"])
    assert all({"name", "pct", "tone"} <= set(s) for s in body["skills"])
