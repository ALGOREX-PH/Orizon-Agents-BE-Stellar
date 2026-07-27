"""Fail-fast Settings validators: half-flipped or unsafe configs must refuse
to boot instead of running open. Constructed with _env_file=None so the local
.env can never leak into assertions."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import MAINNET_PASSPHRASE, Settings


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_defaults_are_safe_and_timeouts_declared():
    s = _settings()
    assert s.pdax_allow_unsigned_webhooks is False
    assert s.llm_timeout_seconds == 120.0
    assert s.decompose_timeout_seconds == 90.0


def test_mainnet_requires_mainnet_passphrase():
    with pytest.raises(ValidationError, match="STELLAR_NETWORK_PASSPHRASE"):
        _settings(stellar_network="mainnet")
    s = _settings(stellar_network="mainnet", stellar_network_passphrase=MAINNET_PASSPHRASE)
    assert s.stellar_network == "mainnet"


def test_production_rejects_unsigned_webhook_escape_hatch():
    with pytest.raises(ValidationError, match="PDAX_ALLOW_UNSIGNED_WEBHOOKS"):
        _settings(
            pdax_environment="production",
            pdax_webhook_secret="whsec",
            pdax_allow_unsigned_webhooks=True,
        )


def test_production_requires_webhook_secret():
    with pytest.raises(ValidationError, match="PDAX_WEBHOOK_SECRET"):
        _settings(pdax_environment="production", pdax_webhook_secret="")


def test_production_with_secret_and_signing_enforced_boots():
    s = _settings(pdax_environment="production", pdax_webhook_secret="whsec")
    assert s.pdax_webhook_secret == "whsec"


def test_non_production_environments_keep_the_escape_hatch():
    s = _settings(pdax_environment="uat", pdax_allow_unsigned_webhooks=True)
    assert s.pdax_allow_unsigned_webhooks is True
