from __future__ import annotations

import logging
import time

from fastapi import APIRouter

from ..schemas import Agent, OverviewMetrics
from ..services import reputation_svc
from ..state import state

logger = logging.getLogger(__name__)

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

# The dashboard polls this route every few seconds and an RPC outage lasts
# minutes, so the fallback is logged on a duty cycle: every transition
# (measured → fallback and back) is logged immediately, and a steady degraded
# state repeats at most this often. One line per poll would bury the log on a
# free-tier instance; no line at all is what hid the problem in the first
# place.
_TRUST_LOG_INTERVAL_SECONDS = 300.0
_trust_degraded: bool | None = None  # None = nothing observed yet
_trust_logged_at = 0.0


def _note_trust_source(degraded: bool, reason: str, exc_info: bool = False) -> None:
    """Rate-limited record of where avg_trust came from.

    Without this the value silently alternated between the on-chain average
    and the seeded 4.86 baseline with nothing in the log to explain which one
    the dashboard was showing, or why it changed.
    """
    global _trust_degraded, _trust_logged_at
    changed = degraded != _trust_degraded
    if not degraded:
        if changed and _trust_degraded is not None:
            logger.info("avg_trust recovered to live on-chain reputation")
        _trust_degraded = False
        return
    now = time.monotonic()
    if changed or now - _trust_logged_at >= _TRUST_LOG_INTERVAL_SECONDS:
        logger.warning(
            "avg_trust fell back to the seeded registry average (%.2f): %s — the dashboard is "
            "showing a presentation baseline, not measured trust",
            DEMO_FALLBACK_TRUST,
            reason,
            exc_info=exc_info,
        )
        _trust_logged_at = now
    _trust_degraded = True


async def _avg_trust(agents: list[Agent]) -> float:
    """Average trust on the 0–5 scale, sourced from live smoothed reputation.

    Agents rated on-chain contribute smoothed_bps / 2000 (bps of a 0..10_000
    scale mapped onto 0..5). fetch_reps never raises and carries its own
    timeout + read cache, so this stays fast; when no on-chain evidence is
    readable (chain down, reputation disabled, nothing rated yet) every entry
    degrades to the prior — fall back to the seeded registry average rather
    than presenting the flat prior as measured trust.

    Every fallback path is reported through `_note_trust_source`, which
    distinguishes the benign cases (reputation not deployed, nothing rated
    yet) from a live degradation: reputation_svc marks a prior it produced
    because the ledger was unreadable with `degraded=True`.
    """
    if not agents:
        _note_trust_source(True, "the registry is empty")
        return DEMO_FALLBACK_TRUST
    seeded = sum(a.rep for a in agents) / len(agents)
    try:
        infos = await reputation_svc.fetch_reps([a.id for a in agents])
    except Exception as e:
        # Defensive: the dashboard must never 500 over trust. fetch_reps is
        # documented never to raise, so reaching this is a bug worth a
        # traceback, not a silent `return seeded`.
        _note_trust_source(True, f"reputation batch read raised {type(e).__name__}", exc_info=True)
        return seeded
    onchain = [info.smoothed_bps for info in infos.values() if info.source == "onchain"]
    if not onchain:
        degraded = sum(1 for info in infos.values() if info.degraded)
        if degraded:
            # The ledger is deployed but unreadable — reputation_svc has
            # already logged the read failure itself; this names the
            # user-visible consequence.
            _note_trust_source(True, f"{degraded}/{len(infos)} reputation reads degraded to the prior")
        else:
            _note_trust_source(True, "no agent has on-chain rating evidence yet")
        return seeded
    _note_trust_source(False, "")
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
        # Whether this number is measured or a baseline is NOT reported here:
        # the response shape is pinned by the frontend's `Overview` type and
        # by test_metrics_api.test_overview_response_shape_is_stable, and the
        # frontend can already tell from GET /api/stellar/reputation, whose
        # per-agent `source` is "onchain" exactly when trust is measured.
        # Server-side, `_note_trust_source` above is the record of which one
        # was served.
        avg_trust=round(await _avg_trust(agents), 2),
        # The sparkline is a rate series; the retained-task count (monotonic
        # up to the store cap) is not a rate, so no live point is appended.
        throughput=DEMO_BASELINE_THROUGHPUT,
        skills=DEMO_BASELINE_SKILL_MIX,
    )
