from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import time
from typing import Any

from ..agents.registry import get_worker
from ..config import settings
from ..demo_kits import detect_kit
from ..schemas import StoredPlan, Task, TaskStatus, TraceLevel, TraceLine
from ..state import state
from ..trace_bus import bus

logger = logging.getLogger(__name__)

# Strong references to in-flight background runs — asyncio.create_task alone
# only keeps a weak reference, so an un-referenced task can be garbage
# collected mid-run. Tasks remove themselves on completion.
_background_tasks: set[asyncio.Task] = set()


def _track_background_task(task: asyncio.Task) -> None:
    _background_tasks.add(task)
    task.add_done_callback(_on_background_task_done)


def _on_background_task_done(task: asyncio.Task) -> None:
    _background_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("background execution task failed: %s", exc, exc_info=exc)


def _now_ts(start: float) -> str:
    elapsed = time.monotonic() - start
    seconds = int(elapsed)
    hundredths = int((elapsed - seconds) * 1000)
    return f"{seconds:02d}.{hundredths:03d}"


async def _emit(task_id: str, start: float, level: TraceLevel, msg: str) -> TraceLine:
    line = TraceLine(t=_now_ts(start), level=level, msg=msg)
    state.append_trace(task_id, line)
    await bus.publish(task_id, line)
    return line


def _summarize(output: dict) -> str:
    if "summary" in output:
        return str(output["summary"])[:180]
    counts = output.get("counts")
    if isinstance(counts, dict):
        return ", ".join(f"{k}={v}" for k, v in counts.items())
    return "done"


async def execute_plan(
    plan: StoredPlan,
    *,
    auth_id_hex: str | None = None,
    payer: str | None = None,
) -> str:
    """Kicks off execution in the background. Returns the new task_id.

    If `auth_id_hex` + `payer` are provided, the backend performs a real
    on-chain `charge` + `seal` at the end of the run and stores the tx
    hashes on the Task.
    """
    task_id = f"tsk_{secrets.token_hex(8)}"
    task = Task(
        id=task_id,
        intent=plan.intent,
        agents=len(plan.plan.steps),
        spent=0.0,
        status="running",
        started="just now",
    )
    state.add_task(task)

    _track_background_task(
        asyncio.create_task(_run(plan, task_id, auth_id_hex=auth_id_hex, payer=payer))
    )
    return task_id


async def _run(
    plan: StoredPlan,
    task_id: str,
    *,
    auth_id_hex: str | None = None,
    payer: str | None = None,
) -> None:
    start = time.monotonic()
    spent = 0.0
    last_artifact: dict | None = None
    charge_tx: str | None = None
    proof_tx: str | None = None
    onchain = bool(auth_id_hex and payer)

    # Accumulate prior step outputs so later steps can build on them.
    # The kit (if any) is seeded into context up-front so EVERY worker
    # in the pipeline can short-circuit deterministically.
    kit = detect_kit(plan.intent)
    context: dict[str, Any] = {
        "kit": kit.model_dump() if kit is not None else None,
        "intent": plan.intent,
    }

    try:
        await _emit(task_id, start, "input", f"intent received → '{plan.intent}'")
        if kit is not None:
            await _emit(
                task_id,
                start,
                "exec",
                f"kit detected: {kit.kit_id} → {kit.brand.name} "
                f"({len(kit.features)} features locked)",
            )
        await _emit(
            task_id,
            start,
            "exec",
            f"orchestrator: decompose → [{', '.join(s.agent_id for s in plan.plan.steps)}]",
        )
        if onchain:
            await _emit(
                task_id,
                start,
                "exec",
                f"x402 authorized on-chain by {payer[:4]}…{payer[-4:]} (auth {auth_id_hex[:8]}…)",
            )

        for step in plan.plan.steps:
            worker = get_worker(step.agent_id)
            if worker is None:
                await _emit(task_id, start, "error", f"unknown agent: {step.agent_id}")
                continue

            await _emit(
                task_id,
                start,
                "exec",
                f"match agent: {worker.name} ({step.agent_id}) — {step.rationale}",
            )

            try:
                # 120s ceiling — gpt-5.3-codex producing a 600–1000 line artifact
                # can legitimately take 30–90s. Enough headroom, still bounded.
                output = await asyncio.wait_for(
                    worker.run(plan.intent, step.rationale, context=context),
                    timeout=120.0,
                )
            except asyncio.TimeoutError:
                await _emit(task_id, start, "error", f"{worker.name} timed out")
                continue
            except Exception as e:  # pragma: no cover
                await _emit(task_id, start, "error", f"{worker.name} failed: {e}")
                continue

            spent += step.est_price_usdc
            if not onchain:
                await _emit(
                    task_id,
                    start,
                    "cost",
                    f"x402 payment → {step.agent_id} :: {step.est_price_usdc:.3f} USDC (simulated)",
                )
            await _emit(task_id, start, "out", f"{worker.name}: {_summarize(output)}")

            # Surface critic notes / violations if the worker reports them.
            if isinstance(output, dict):
                violations = output.get("critic_violations") or []
                if violations:
                    joined = " · ".join(violations)[:180]
                    await _emit(task_id, start, "exec", f"{worker.name}: violations → {joined}")
                notes = output.get("critic_notes") or []
                if notes:
                    joined = " · ".join(notes)[:180]
                    await _emit(task_id, start, "exec", f"{worker.name}: {joined}")
                # Some workers (deploy.v0) attach a synthetic preview URL —
                # surface it so the demo viewer sees the "ship" moment.
                preview_url = output.get("preview_url")
                if preview_url:
                    await _emit(
                        task_id,
                        start,
                        "out",
                        f"{worker.name}: preview → {preview_url}",
                    )

            # Capture artifact if the worker returned one. Later steps may
            # overwrite this (e.g. code.critic refines code.gen's draft).
            art = output.get("artifact") if isinstance(output, dict) else None
            if art:
                last_artifact = art
                title = art.get("title", "artifact")
                files = art.get("files", [])
                total_bytes = sum(len(f.get("content", "")) for f in files)
                total_lines = sum(f.get("content", "").count("\n") + 1 for f in files)
                await _emit(
                    task_id,
                    start,
                    "artifact",
                    f"▣ {title} — {len(files)} file(s) · "
                    f"{total_lines:,} lines · {total_bytes:,} bytes",
                )

            # Persist this step's output under the agent name so later workers
            # can read it. e.g. context["code.gen"] = {...}.
            if isinstance(output, dict):
                context[worker.name] = output

        if onchain:
            charge_tx, proof_tx, job_id = await _settle_onchain(
                task_id, start, plan, payer=payer, auth_id_hex=auth_id_hex, total_usdc=spent
            )
            if charge_tx and job_id:
                await _submit_ratings(
                    task_id, start, plan, context, payer=payer, job_id=job_id
                )
        else:
            sim_hash = "0x" + secrets.token_hex(16)
            await _emit(task_id, start, "proof", f"ERC-8004 attestation: {sim_hash} (simulated)")
            await _emit(
                task_id,
                start,
                "proof",
                f"workflow sealed — {len(plan.plan.steps)} agents · {spent:.3f} USDC · "
                f"{time.monotonic() - start:.2f}s",
            )

        _finalize_task(task_id, "complete", spent, last_artifact, charge_tx, proof_tx)

    except asyncio.CancelledError:
        # Shutdown or external cancel: leave the task terminal instead of
        # "running" forever, tell the stream, and keep the cancellation
        # propagating. shield: a second cancel must not kill the trace line.
        _finalize_task(task_id, "failed", spent, last_artifact, charge_tx, proof_tx)
        await asyncio.shield(_emit(task_id, start, "error", "workflow cancelled"))
        raise
    except Exception as e:
        logger.exception("workflow %s failed", task_id)
        _finalize_task(task_id, "failed", spent, last_artifact, charge_tx, proof_tx)
        await _emit(task_id, start, "error", f"workflow failed: {e}")
    finally:
        # The SSE terminator must reach subscribers even mid-cancellation:
        # run the drain-delay + close shielded so bus.close ALWAYS executes
        # (a bare `await asyncio.sleep` here would swallow the close when a
        # CancelledError landed on it).
        await asyncio.shield(_finish_stream(task_id))


def _finalize_task(
    task_id: str,
    status: TaskStatus,
    spent: float,
    artifact: dict | None,
    charge_tx: str | None,
    proof_tx: str | None,
) -> None:
    """Terminal status write shared by the complete / failed / cancelled paths."""
    task = state.tasks.get(task_id)
    if task is None:
        return
    state.tasks[task_id] = task.model_copy(
        update={
            "status": status,
            "spent": round(spent, 4),
            "artifact": artifact,
            "charge_tx": charge_tx,
            "proof_tx": proof_tx,
        }
    )


async def _finish_stream(task_id: str) -> None:
    """Give SSE subscribers a beat to drain, then end the stream."""
    await asyncio.sleep(0.05)
    await bus.close(task_id)


async def _settle_onchain(
    task_id: str,
    start: float,
    plan: StoredPlan,
    *,
    payer: str,
    auth_id_hex: str,
    total_usdc: float,
) -> tuple[str | None, str | None, bytes | None]:
    """Perform the real PaymentEscrow.charge + AttestationRegistry.seal calls.

    Returns (charge_tx, proof_tx, job_id); either tx may be None if that step
    failed, and job_id is None when the charge failed or was skipped.
    """
    from stellar_sdk import scval as _sv

    from ..stellar import client as sc

    charge_tx: str | None = None
    proof_tx: str | None = None
    settled_job_id: bytes | None = None

    if not settings.stellar_signing_key:
        await _emit(
            task_id,
            start,
            "error",
            "STELLAR_SIGNING_KEY not set — skipping on-chain charge/seal",
        )
        return (None, None, None)

    try:
        settler = sc._signer_keypair().public_key
        auth_id = bytes.fromhex(auth_id_hex)
        job_id = secrets.token_bytes(16)

        total_i128 = sc.usdc_to_i128(max(total_usdc, 0.000001))

        # 1. charge
        charge = await sc.invoke_with_server_key_async(
            sc.contract_ids().payment_escrow,
            "charge",
            [
                sc.addr(settler),
                sc.bytes16(auth_id),
                sc.i128(total_i128),
                sc.bytes16(job_id),
            ],
        )
        charge_tx = charge.get("hash")
        if charge.get("status") == "SUCCESS":
            settled_job_id = job_id
            await _emit(
                task_id,
                start,
                "cost",
                f"x402 charge → {total_usdc:.3f} USDC settled · tx {charge_tx[:10]}…",
            )
        else:
            await _emit(
                task_id,
                start,
                "error",
                f"charge status={charge.get('status')} hash={charge_tx}",
            )
            return (charge_tx, None, None)

        # 2. seal
        intent_hash = hashlib.sha256(plan.intent.encode("utf-8")).digest()
        agents_sym = _sv.to_vec([sc.sym(s.agent_id) for s in plan.plan.steps])
        # charge() returns the on-chain receipt id (BytesN<16>); include it in
        # the attestation when the tx meta decoded cleanly, else seal without.
        receipt_rv = charge.get("return_value")
        receipts = []
        if isinstance(receipt_rv, (bytes, bytearray)) and len(receipt_rv) == 16:
            receipts.append(sc.bytes16(bytes(receipt_rv)))
        receipts_vec = _sv.to_vec(receipts)

        seal = await sc.invoke_with_server_key_async(
            sc.contract_ids().attestation_registry,
            "seal",
            [
                sc.addr(settler),          # caller / sealer
                sc.bytes16(job_id),
                sc.addr(payer),            # orchestrator = the payer for now
                sc.bytes32(intent_hash),
                agents_sym,
                receipts_vec,
                sc.i128(total_i128),
            ],
        )
        proof_tx = seal.get("hash")
        if seal.get("status") == "SUCCESS":
            await _emit(
                task_id,
                start,
                "proof",
                f"ERC-8004 attestation sealed · tx {proof_tx[:10]}…",
            )
            await _emit(
                task_id,
                start,
                "proof",
                f"workflow sealed — {len(plan.plan.steps)} agents · {total_usdc:.3f} USDC · "
                f"{time.monotonic() - start:.2f}s",
            )
        else:
            await _emit(
                task_id,
                start,
                "error",
                f"seal status={seal.get('status')} hash={proof_tx}",
            )
    except Exception as e:
        await _emit(task_id, start, "error", f"on-chain settlement failed: {e}")

    return (charge_tx, proof_tx, settled_job_id)


async def _submit_ratings(
    task_id: str,
    start: float,
    plan: StoredPlan,
    context: dict[str, Any],
    *,
    payer: str,
    job_id: bytes,
) -> None:
    """Submit the settler's synthetic per-step ratings to ReputationLedger.

    Best-effort by design: a failed rating never fails the workflow — each
    step logs its own trace line and the loop moves on.
    """
    if not (
        settings.reputation_enabled
        and settings.stellar_reputation_ledger
        and settings.stellar_signing_key
    ):
        return

    from ..stellar import client as sc
    from . import reputation_svc

    # Sequential on purpose: parallel submits from the one scorer account
    # collide on sequence numbers (each tx consumes the account's next seq).
    for step in plan.plan.steps:
        # Context keys are worker names (e.g. "code.gen"), same as agent_name.
        rating, weight = reputation_svc.synthetic_rating(
            context.get(step.agent_name or ""), step.est_price_usdc
        )
        try:
            result = await asyncio.to_thread(
                sc.submit_rating,
                step.agent_id,
                job_id,
                rating,
                weight,
                payer,
                "auto",
            )
            tx = result.get("hash") or ""
            await _emit(
                task_id,
                start,
                "proof",
                f"reputation → {step.agent_name} rated {rating}/100 · tx {tx[:10]}…",
            )
        except Exception as e:
            await _emit(
                task_id,
                start,
                "error",
                f"reputation submit failed for {step.agent_name}: {e}",
            )
