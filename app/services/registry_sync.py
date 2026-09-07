"""
Registry sync — mirrors on-chain AgentRegistry entries into the marketplace.

Closes the registry split-brain (story 1.02): GET /api/agents served only the
in-memory seeded catalog, so an agent registered on-chain — the product's
entire permissionless-marketplace claim — was invisible to the console, the
planner, and the metrics. This module is the missing read path: a background
loop (started from the app lifespan) plus an on-demand `sync_once` that pull
`list_ids` + `get` from the registry contract and upsert the results into
`state.agents`, provenance-tagged `source="onchain"`.

Design notes, each deliberate:

  - Reads are DIRECT and SEQUENTIAL — no `stellar.cache`, no gather. The
    registry is the source of truth being mirrored, so a stale cached read
    only delays the mirror it exists to provide; and each read occupies a
    thread in the shared 8-thread executor, so fanning out one read per agent
    would starve the money-moving paths that share it.
  - The gate reads `settings.stellar_agent_registry` LIVE on every pass and
    never `sc.contract_ids()` — that helper is lru_cached, so it would pin
    whatever id (or blank) it saw first for the life of the process and
    defeat both runtime reconfiguration and hermetic tests.
  - Known ids are re-read every pass, not only new ones: an operator's
    on-chain reprice or delist must propagate to the marketplace — that is
    what makes story 1.08's delist real rather than cosmetic.
  - On-chain ids in the `agt_` namespace are SKIPPED: that namespace is the
    seeded catalog, and `state.add_agent` is an upsert, so indexing one would
    clobber a worker-backed agent with a chain record that has no worker.
  - The loop fails OPEN and never dies: a bad pass logs and waits for the
    next tick. Failures coalesce to ONE warning per outage (then DEBUG, then
    an INFO on recovery) — the `reputation_svc._log_degraded` discipline; a
    15s loop against a downed RPC must not flood the log with warnings.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from ..config import settings
from ..schemas import Agent
from ..state import state
from ..stellar import client as sc

logger = logging.getLogger(__name__)

# Floor on the loop cadence — a misconfigured REGISTRY_SYNC_SECONDS of 0 (or
# negative) must degrade to a slow poll, not a hot loop against the RPC.
_MIN_INTERVAL_SECONDS = 5.0

# Single-flight guard shared by the loop and on-demand callers: overlapping
# passes would race identical reads through the shared executor for no gain.
_lock = asyncio.Lock()

# Handle on the background loop; start()/stop() own its lifecycle.
_task: asyncio.Task | None = None

# Once-per-process log guards. The disabled notice would otherwise repeat
# every tick on a deployment that simply has no registry configured, and a
# squatted agt_ id would re-warn on every pass for as long as it exists
# on-chain.
_disabled_logged = False
_skipped_agt_ids: set[str] = set()

# True while the loop is inside a failing streak — flips the pass-failure
# log level from WARNING (first failure) to DEBUG (consecutive), and arms
# the INFO "recovered" line for the next success.
_failing = False


def _describe(e: BaseException) -> str:
    """Compact "Type: message" description, bare type when there is no
    message (asyncio.TimeoutError carries none)."""
    text = str(e)
    return f"{type(e).__name__}: {text}" if text else type(e).__name__


def _to_agent(raw: dict[str, Any]) -> Agent:
    """Map one on-chain registry record to the marketplace Agent shape.

    Price arrives as an i128 in stroops (7 decimals). `rep` is the smoothed
    reputation PRIOR on the 0–5 scale (7000 bps → 3.5), not 0: this field
    feeds the metrics trust blend and renders as stars in the console, so a
    zero would both distort the average and paint every newly indexed agent
    as ★0.00 — the opposite of the cold-start policy reputation_svc applies
    everywhere else. `runs` starts at 0 (no execution history is on-chain)
    and `real` stays False: an indexed agent has no in-process worker.
    """
    return Agent(
        id=raw["id"],
        name=raw["name"],
        skills=list(raw["skills"]),
        price=raw["price"] / 1e7,
        rep=settings.reputation_prior_bps / 2000,
        status="online" if raw["active"] else "offline",
        runs=0,
        real=False,
        owner=raw["owner"],
        source="onchain",
    )


async def sync_once() -> int:
    """Run one full sync pass; returns the number of agents upserted.

    Raises on a failed `list_ids` (unknown contract, RPC outage) — the pass
    has nothing to iterate, and the caller owns the failure policy (the loop
    coalesces and survives; an on-demand caller gets the error). A failed
    `get` for ONE id is logged and skipped so a single bad record never
    kills the rest of the pass.
    """
    global _disabled_logged
    async with _lock:
        contract_id = settings.stellar_agent_registry
        if not contract_id:
            if not _disabled_logged:
                _disabled_logged = True
                logger.info("registry sync disabled — STELLAR_AGENT_REGISTRY not set")
            return 0

        ids = await asyncio.to_thread(sc.simulate_read, contract_id, "list_ids", [])
        synced = 0
        for agent_id in ids:
            if agent_id.startswith("agt_"):
                # Seeded namespace: add_agent is an upsert, so indexing this
                # id would clobber a worker-backed catalog agent.
                if agent_id not in _skipped_agt_ids:
                    _skipped_agt_ids.add(agent_id)
                    logger.warning(
                        "registry sync: skipping on-chain id %r — the agt_ namespace is the "
                        "seeded catalog, and upserting it would clobber a worker-backed agent",
                        agent_id,
                    )
                continue
            try:
                raw = await asyncio.to_thread(sc.simulate_read, contract_id, "get", [sc.sym(agent_id)])
                state.add_agent(_to_agent(raw))
                synced += 1
            except Exception as e:
                logger.warning("registry sync: failed to index %r: %s", agent_id, _describe(e))
        return synced


async def _sync_loop() -> None:
    """Background loop: sync, wait, repeat — forever.

    Belt over braces: `sync_once` already contains per-id failures, so the
    except here only sees pass-level failures (list_ids, RPC down) — and the
    task must survive those too, because a loop that dies during an outage
    never mirrors the recovery. Consecutive failures coalesce: WARNING once,
    DEBUG until the streak ends, INFO when a pass next succeeds.
    """
    global _failing
    while True:
        try:
            await sync_once()
        except Exception as e:
            if _failing:
                logger.debug("registry sync still failing: %s", _describe(e))
            else:
                _failing = True
                logger.warning(
                    "registry sync pass failed: %s — will keep retrying (coalescing to DEBUG until it recovers)",
                    _describe(e),
                )
        else:
            if _failing:
                _failing = False
                logger.info("registry sync recovered")
        await asyncio.sleep(max(_MIN_INTERVAL_SECONDS, settings.registry_sync_seconds))


def _on_task_done(task: asyncio.Task) -> None:
    # Mirrors execution_svc: a task that dies with an exception would
    # otherwise vanish silently (nothing awaits it).
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("registry sync loop died: %s", exc, exc_info=exc)


def start() -> None:
    """Start the background sync loop. Idempotent — a live loop is kept."""
    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_sync_loop())
    _task.add_done_callback(_on_task_done)


async def stop() -> None:
    """Cancel the loop and wait for it to unwind (shutdown path)."""
    global _task
    if _task is None:
        return
    _task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _task
    _task = None
