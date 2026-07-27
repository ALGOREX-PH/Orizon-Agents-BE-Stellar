"""Shared OpenAIChat factory — every Agno agent's model is built here.

Centralizes the client budget: `timeout` caps a single OpenAI HTTP attempt
(the SDK default is 600 s) and `max_retries=1` caps the SDK's internal retry
loop (default 2 extra attempts), so a hung upstream can't pin one request
for ~30 minutes. End-to-end bounds (e.g. decompose_timeout_seconds) are
enforced with asyncio.wait_for at the call sites.
"""
from __future__ import annotations

from agno.models.openai import OpenAIChat

from ..config import settings


def build_openai_chat(model_id: str) -> OpenAIChat:
    """OpenAIChat with the shared api key, request timeout, and retry cap."""
    return OpenAIChat(
        id=model_id,
        api_key=settings.openai_api_key,
        timeout=settings.llm_timeout_seconds,
        max_retries=1,
    )
