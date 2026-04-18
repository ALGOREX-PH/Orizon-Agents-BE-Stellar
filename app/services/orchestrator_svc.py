from __future__ import annotations

import json
import secrets

from ..agents.orchestrator import orchestrator_agent
from ..schemas import DecomposeResponse, Plan, PlanStep, StoredPlan
from ..state import state


def _registry_prompt_fragment() -> str:
    lines = ["AVAILABLE_AGENTS:"]
    for a in state.list_agents():
        lines.append(
            f"- id={a.id} name={a.name} price={a.price:.3f} rep={a.rep:.2f} "
            f"skills={','.join(a.skills)}"
        )
    return "\n".join(lines)


async def decompose(intent: str) -> DecomposeResponse:
    prompt = f"""{_registry_prompt_fragment()}

USER_INTENT: {intent}

Return the Plan."""
    result = await orchestrator_agent.arun(prompt)
    plan: Plan = result.content  # type: ignore[assignment]

    # Clamp to known agents; backfill names + snap price to registry truth.
    cleaned: list[PlanStep] = []
    for step in plan.steps:
        agent = state.agents.get(step.agent_id)
        if not agent:
            # Drop unknown ids silently — the model sometimes invents.
            continue
        cleaned.append(
            PlanStep(
                agent_id=agent.id,
                agent_name=agent.name,
                rationale=step.rationale.strip(),
                est_price_usdc=agent.price,
                est_eta_seconds=max(0.3, min(step.est_eta_seconds, 3.0)),
            )
        )

    if not cleaned:
        # Fall back to a minimal safe plan so the UI never gets stuck.
        copy_agent = state.agents["agt_01h8"]
        cleaned = [
            PlanStep(
                agent_id=copy_agent.id,
                agent_name=copy_agent.name,
                rationale="fallback: generate copy for the intent",
                est_price_usdc=copy_agent.price,
                est_eta_seconds=0.8,
            )
        ]

    plan_id = f"pln_{secrets.token_hex(4)}"
    total_price = sum(s.est_price_usdc for s in cleaned)
    total_eta = sum(s.est_eta_seconds for s in cleaned)

    stored = StoredPlan(
        id=plan_id,
        intent=intent,
        plan=Plan(steps=cleaned),
        total_usdc=total_price,
        total_eta=total_eta,
    )
    state.plans[plan_id] = stored

    return DecomposeResponse(
        plan_id=plan_id,
        intent=intent,
        steps=cleaned,
        total_usdc=round(total_price, 4),
        total_eta=round(total_eta, 2),
    )
