from __future__ import annotations

from fastapi import APIRouter

from ..schemas import Agent, OverviewMetrics
from ..services import reputation_svc
from ..state import state

router = APIRouter(tags=["metrics"])

# Demo-baseline presentation constants: the seeded registry holds only a
# dozen agents, so the dashboard blends real counters with these baselines to
# read like a populated network. Real values are layered on top below.
DEMO_BASELINE_AGENTS_ONLINE = 2481
DEMO_BASELINE_TASKS_PER_SEC = 1.284
DEMO_BASELINE_THROUGHPUT = [22, 18, 24, 20, 28, 26, 34, 30, 40, 36, 48, 46, 58, 54, 64, 70, 66, 74]
DEMO_BASELINE_SKILL_MIX = [
    {"name": "content", "pct": 38, "tone": "violet"},
    {"name": "code", "pct": 26, "tone": "cyan"},
    {"name": "research", "pct": 14, "tone": "magenta"},
    {"name": "design", "pct": 12, "tone": "violet"},
    {"name": "ops", "pct": 10, "tone": "cyan"},
]
DEMO_FALLBACK_COMPLETION = 0.942
DEMO_FALLBACK_TRUST = 4.86


async def _avg_trust(agents: list[Agent]) -> float:
    """Average trust on the 0–5 scale, sourced from live smoothed reputation.

    Agents rated on-chain contribute smoothed_bps / 2000 (bps of a 0..10_000
    scale mapped onto 0..5). fetch_reps never raises and carries its own
    timeout + read cache, so this stays fast; when no on-chain evidence is
    readable (chain down, reputation disabled, nothing rated yet) every entry
    degrades to the prior — fall back to the seeded registry average rather
    than presenting the flat prior as measured trust.
    """
    if not agents:
        return DEMO_FALLBACK_TRUST
    seeded = sum(a.rep for a in agents) / len(agents)
    try:
        infos = await reputation_svc.fetch_reps([a.id for a in agents])
    except Exception:  # defensive: the dashboard must never 500 over trust
        return seeded
    onchain = [info.smoothed_bps for info in infos.values() if info.source == "onchain"]
    if not onchain:
        return seeded
    return sum(onchain) / len(onchain) / 2000.0


@router.get("/metrics/overview", response_model=OverviewMetrics, summary="Dashboard overview metrics")
async def overview() -> OverviewMetrics:
    """Blended dashboard metrics: live counters (agents online, completion,
    trust) layered onto demo presentation baselines."""
    agents = state.list_agents()
    online = sum(1 for a in agents if a.status == "online")
    tasks = state.recent_tasks(limit=200)
    # Completion is a rate over decided (terminal) tasks only — pending and
    # running tasks are not failures and must not drag the rate down.
    terminal = [t for t in tasks if t.status in ("complete", "failed")]
    completed = sum(1 for t in terminal if t.status == "complete")
    completion = (completed / len(terminal)) if terminal else DEMO_FALLBACK_COMPLETION

    return OverviewMetrics(
        agents_online=DEMO_BASELINE_AGENTS_ONLINE + online,
        tasks_per_sec=DEMO_BASELINE_TASKS_PER_SEC,
        avg_completion=round(completion, 3),
        avg_trust=round(await _avg_trust(agents), 2),
        # The sparkline is a rate series; the retained-task count (monotonic
        # up to the store cap) is not a rate, so no live point is appended.
        throughput=DEMO_BASELINE_THROUGHPUT,
        skills=DEMO_BASELINE_SKILL_MIX,
    )
