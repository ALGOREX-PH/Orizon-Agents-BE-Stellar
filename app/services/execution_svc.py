from __future__ import annotations

import asyncio
import hashlib
import secrets
import time
from typing import Optional

from ..agents.registry import get_worker
from ..config import settings
from ..schemas import StoredPlan, Task, TraceLine, TraceLevel
from ..state import state
from ..trace_bus import bus


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
        return str(output["summary"])[:140]
    counts = output.get("counts")
    if isinstance(counts, dict):
        return ", ".join(f"{k}={v}" for k, v in counts.items())
    return "done"


async def execute_plan(
    plan: StoredPlan,
    *,
    auth_id_hex: Optional[str] = None,
    payer: Optional[str] = None,
) -> str:
    """Kicks off execution in the background. Returns the new task_id.

    If `auth_id_hex` + `payer` are provided, the backend performs a real
    on-chain `charge` + `seal` at the end of the run and stores the tx
    hashes on the Task.
    """
    task_id = f"tsk_{secrets.token_hex(3)}"
    task = Task(
        id=task_id,
        intent=plan.intent,
        agents=len(plan.plan.steps),
        spent=0.0,
        status="running",
        started="just now",
    )
    state.add_task(task)

    asyncio.create_task(_run(plan, task_id, auth_id_hex=auth_id_hex, payer=payer))
    return task_id


async def _run(
    plan: StoredPlan,
    task_id: str,
    *,
    auth_id_hex: Optional[str] = None,
    payer: Optional[str] = None,
) -> None:
    start = time.monotonic()
    spent = 0.0
    last_artifact: Optional[dict] = None
    onchain = bool(auth_id_hex and payer)

    try:
        await _emit(task_id, start, "input", f"intent received → '{plan.intent}'")
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
                # 120s ceiling — gpt-5.3-codex producing a 400–700 line artifact
                # can legitimately take 30-90s. Enough headroom, still bounded.
                output = await asyncio.wait_for(
                    worker.run(plan.intent, step.rationale), timeout=120.0
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

            # Surface two-pass (gen → critic) activity if the worker reports it.
            if isinstance(output, dict):
                violations = output.get("critic_violations") or []
                notes = output.get("critic_notes") or []
                if violations or notes:
                    await _emit(
                        task_id,
                        start,
                        "exec",
                        f"code.critic: refining draft ({len(violations)} violation{'' if len(violations) == 1 else 's'} flagged)",
                    )
                    if notes:
                        joined = " · ".join(notes)[:140]
                        await _emit(task_id, start, "out", f"code.critic: {joined}")

            # Capture artifact if the worker returned one
            art = output.get("artifact") if isinstance(output, dict) else None
            if art:
                last_artifact = art
                title = art.get("title", "artifact")
                files = art.get("files", [])
                await _emit(
                    task_id,
                    start,
                    "artifact",
                    f"▣ {title} — {len(files)} file(s) · {sum(len(f.get('content', '')) for f in files)} bytes",
                )

        charge_tx: Optional[str] = None
        proof_tx: Optional[str] = None

        if onchain:
            charge_tx, proof_tx = await _settle_onchain(
                task_id, start, plan, payer=payer, auth_id_hex=auth_id_hex, total_usdc=spent
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

        # update task state
        task = state.tasks.get(task_id)
        if task:
            state.tasks[task_id] = task.model_copy(
                update={
                    "status": "complete",
                    "spent": round(spent, 4),
                    "artifact": last_artifact,
                    "charge_tx": charge_tx,
                    "proof_tx": proof_tx,
                }
            )

    finally:
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
) -> tuple[Optional[str], Optional[str]]:
    """Perform the real PaymentEscrow.charge + AttestationRegistry.seal calls.

    Returns (charge_tx, proof_tx); either may be None if that step failed.
    """
    from stellar_sdk import Keypair, scval as _sv

    from ..stellar import client as sc

    charge_tx: Optional[str] = None
    proof_tx: Optional[str] = None

    if not settings.stellar_signing_key:
        await _emit(
            task_id,
            start,
            "error",
            "STELLAR_SIGNING_KEY not set — skipping on-chain charge/seal",
        )
        return (None, None)

    try:
        settler = Keypair.from_secret(settings.stellar_signing_key).public_key
        auth_id = bytes.fromhex(auth_id_hex)
        job_id = secrets.token_bytes(16)

        total_i128 = sc.usdc_to_i128(max(total_usdc, 0.000001))

        # 1. charge
        charge = await asyncio.to_thread(
            sc.invoke_with_server_key,
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
            return (charge_tx, None)

        # 2. seal
        intent_hash = hashlib.sha256(plan.intent.encode("utf-8")).digest()
        agents_sym = _sv.to_vec([sc.sym(s.agent_id) for s in plan.plan.steps])
        receipts_vec = _sv.to_vec([])

        seal = await asyncio.to_thread(
            sc.invoke_with_server_key,
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

    return (charge_tx, proof_tx)
