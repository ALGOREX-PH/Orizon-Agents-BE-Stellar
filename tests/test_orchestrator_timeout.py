"""Decompose LLM budget: a hung orchestrator model maps to 504, not a hang."""

from __future__ import annotations

import asyncio

from app.services import orchestrator_svc


def test_slow_decompose_llm_returns_504(client, hermetic_settings, monkeypatch):
    async def slow_arun(prompt):
        await asyncio.sleep(30)

    # Free-form intent (no demo-kit trigger) so the LLM path is taken.
    monkeypatch.setattr(orchestrator_svc.orchestrator_agent, "arun", slow_arun)
    monkeypatch.setattr(hermetic_settings, "decompose_timeout_seconds", 0.05)

    r = client.post(
        "/api/orchestrator/decompose",
        json={"intent": "write a haiku about databases"},
    )
    assert r.status_code == 504
    assert r.json()["detail"] == "decompose_timeout"
