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
        "stellar_reputation_ledger": settings.stellar_reputation_ledger,
        "stellar_admin_address": settings.stellar_admin_address,
    }
    settings.stellar_signing_key = ""
    settings.api_key = ""
    # Reads need a source address to build a simulation envelope, and the
    # default is "" — so without this the suite only passes on a machine whose
    # gitignored .env happens to supply one, and fails in CI with
    # "no source address; set STELLAR_ADMIN_ADDRESS". Pinning a known-valid
    # public key here keeps the suite hermetic; it is an identifier, not a
    # secret, and nothing in the suite reaches the network.
    settings.stellar_admin_address = "GA7AI5TAJEZA27I666DSJC4MUJYBEWUYNNZWPU7R2ONA7IZQVO6R5OQV"
    # A live ledger id in .env would make reputation reads hit testnet RPC —
    # tests must stay offline, so force the prior-fallback path.
    settings.stellar_reputation_ledger = ""
    yield settings
    for k, v in saved.items():
        setattr(settings, k, v)


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c
