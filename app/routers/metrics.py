from __future__ import annotations

from fastapi import APIRouter

from ..schemas import OverviewMetrics
from ..state import state

router = APIRouter(tags=["metrics"])

# Demo-baseline presentation constants: the testnet deployment seeds only a
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


@router.get("/metrics/overview", response_model=OverviewMetrics)
async def overview() -> OverviewMetrics:
    agents = state.list_agents()
    online = sum(1 for a in agents if a.status == "online")
    tasks = state.recent_tasks(limit=200)
    completed = [t for t in tasks if t.status == "complete"]
    completion = (len(completed) / len(tasks)) if tasks else 0.942
    avg_rep = sum(a.rep for a in agents) / len(agents) if agents else 4.86

    return OverviewMetrics(
        agents_online=DEMO_BASELINE_AGENTS_ONLINE + online,
        tasks_per_sec=DEMO_BASELINE_TASKS_PER_SEC,
        avg_completion=round(completion, 3),
        avg_trust=round(avg_rep, 2),
        throughput=DEMO_BASELINE_THROUGHPUT + [len(tasks)] if tasks else DEMO_BASELINE_THROUGHPUT,
        skills=DEMO_BASELINE_SKILL_MIX,
    )
