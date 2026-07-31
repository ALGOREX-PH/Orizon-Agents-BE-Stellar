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


# ── API_KEY vs money-capable credentials ────────────────────────
# An empty API_KEY makes require_api_key a no-op, which is fine for the open
# demo and fatal once the process can sign mainnet transactions or move real
# fiat. These pin both halves: refuse the unsafe combinations, keep every
# demo/dev/read-only combination bootable.

_MAINNET = {"stellar_network": "mainnet", "stellar_network_passphrase": MAINNET_PASSPHRASE}
_SIGNER = "S" + "A" * 55


def test_mainnet_signer_without_api_key_refuses_to_boot():
    with pytest.raises(ValidationError, match="API_KEY is required"):
        _settings(**_MAINNET, stellar_signing_key=_SIGNER)


def test_mainnet_signer_with_api_key_boots():
    s = _settings(**_MAINNET, stellar_signing_key=_SIGNER, api_key="k")
    assert s.api_key == "k"


def test_public_network_alias_is_covered():
    # STELLAR_NETWORK=public is the same live network under another name.
    with pytest.raises(ValidationError, match="API_KEY is required"):
        _settings(
            stellar_network="public",
            stellar_network_passphrase=MAINNET_PASSPHRASE,
            stellar_signing_key=_SIGNER,
        )


def test_readonly_mainnet_without_signer_stays_open():
    # No signing key → /server/charge and /server/seal cannot sign anything,
    # so the open demo default is still safe.
    s = _settings(**_MAINNET)
    assert s.api_key == ""


def test_testnet_signer_does_not_require_api_key():
    # Local dev signs testnet play money; requiring a key here would break it.
    s = _settings(stellar_signing_key=_SIGNER)
    assert s.stellar_network == "testnet"
    assert s.api_key == ""


def test_production_pdax_credentials_without_api_key_refuse_to_boot():
    with pytest.raises(ValidationError, match="API_KEY is required"):
        _settings(
            pdax_environment="production",
            pdax_webhook_secret="whsec",
            pdax_username="ops@example.com",
            pdax_password="pw",
        )


def test_production_pdax_credentials_with_api_key_boot():
    s = _settings(
        pdax_environment="production",
        pdax_webhook_secret="whsec",
        pdax_username="ops@example.com",
        pdax_password="pw",
        api_key="k",
    )
    assert s.pdax_environment == "production"


def test_stage_pdax_credentials_do_not_require_api_key():
    s = _settings(pdax_environment="stage", pdax_username="ops@example.com", pdax_password="pw")
    assert s.api_key == ""


def test_error_names_every_exposure():
    with pytest.raises(ValidationError) as info:
        _settings(
            **_MAINNET,
            stellar_signing_key=_SIGNER,
            pdax_environment="production",
            pdax_webhook_secret="whsec",
            pdax_username="ops@example.com",
            pdax_password="pw",
        )
    message = str(info.value)
    assert "STELLAR_SIGNING_KEY" in message
    assert "PDAX" in message


def test_demo_defaults_still_boot_without_an_api_key():
    assert _settings().api_key == ""
