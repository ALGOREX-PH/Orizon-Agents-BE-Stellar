"""Shared test setup — force a hermetic, offline configuration before the app
is imported so tests never touch OpenAI, PDAX, or the real signing key."""
from __future__ import annotations

import os

os.environ.setdefault("OPENAI_API_KEY", "sk-test")

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


@pytest.fixture(autouse=True)
def hermetic_settings():
    """Neutralize anything secret/live that .env may have provided, and
    restore every setting mutated by a test."""
    saved = {
        "stellar_signing_key": settings.stellar_signing_key,
        "api_key": settings.api_key,
        "max_charge_usdc": settings.max_charge_usdc,
    }
    settings.stellar_signing_key = ""
    settings.api_key = ""
    yield settings
    for k, v in saved.items():
        setattr(settings, k, v)


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c
