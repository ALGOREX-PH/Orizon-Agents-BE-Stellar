"""Settings validators, in two families.

Fail-fast: half-flipped or unsafe configs must refuse to boot instead of
running open. Report-only: values that are merely wrong log a named, actionable
line at startup and still boot — this service is live on mainnet with
autoDeploy on, so a wrong rejection would take the product down.

Constructed with _env_file=None so the local .env can never leak into
assertions."""

from __future__ import annotations

import logging

import pytest
from pydantic import ValidationError

from app.config import MAINNET_PASSPHRASE, PDAX_ENVIRONMENTS, Settings

CONFIG_LOGGER = "app.config"


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def _errors(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == CONFIG_LOGGER and r.levelno >= logging.ERROR]


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


# ── PDAX_ENVIRONMENT typo ───────────────────────────────────────
# app/pdax/config.py:base_url() raises lazily on the first client build, so a
# typo boots clean and 500s every PDAX route. Reported at startup; never fatal.


def test_pdax_environment_constant_matches_the_module_that_resolves_it():
    # app/config.py cannot import BASE_URLS (circular), so this pins the copy
    # to the source of truth instead.
    from app.pdax.config import BASE_URLS

    assert set(PDAX_ENVIRONMENTS) == set(BASE_URLS)


def test_unknown_pdax_environment_is_reported_and_still_boots(caplog):
    with caplog.at_level(logging.ERROR, logger=CONFIG_LOGGER):
        s = _settings(pdax_environment="produciton")
    assert s.pdax_environment == "produciton"  # boots — never fatal
    assert any("PDAX_ENVIRONMENT" in m and "produciton" in m for m in _errors(caplog))


def test_known_pdax_environments_are_quiet(caplog):
    with caplog.at_level(logging.ERROR, logger=CONFIG_LOGGER):
        for environment in PDAX_ENVIRONMENTS:
            extra = {"pdax_webhook_secret": "whsec"} if environment == "production" else {}
            _settings(pdax_environment=environment, **extra)
    assert _errors(caplog) == []


def test_pdax_environment_casing_and_whitespace_are_accepted(caplog):
    # base_url() strips and lowercases before lookup; the report must agree.
    with caplog.at_level(logging.ERROR, logger=CONFIG_LOGGER):
        _settings(pdax_environment="  UAT ")
    assert _errors(caplog) == []


def test_empty_pdax_environment_is_quiet(caplog):
    # base_url() falls back to DEFAULT_ENVIRONMENT when unset.
    with caplog.at_level(logging.ERROR, logger=CONFIG_LOGGER):
        _settings(pdax_environment="")
    assert _errors(caplog) == []


# ── PDAX_OTP_SECRET malformed ───────────────────────────────────
# app/pdax/totp.py base32-decodes the seed at the first MFA challenge.
# Reported at startup; never fatal, and the seed itself is never echoed.

_VALID_OTP_SECRET = "JBSWY3DPEHPK3PXP"


def test_malformed_otp_secret_is_reported_and_still_boots(caplog):
    with caplog.at_level(logging.ERROR, logger=CONFIG_LOGGER):
        s = _settings(pdax_otp_secret="not-base32!!")
    assert s.pdax_otp_secret == "not-base32!!"  # boots — never fatal
    assert any("PDAX_OTP_SECRET" in m for m in _errors(caplog))


def test_malformed_otp_secret_report_never_echoes_the_seed(caplog):
    with caplog.at_level(logging.ERROR, logger=CONFIG_LOGGER):
        _settings(pdax_otp_secret="not-base32!!")
    assert _errors(caplog)
    assert all("not-base32" not in m for m in _errors(caplog))


def test_valid_otp_secret_is_quiet(caplog):
    with caplog.at_level(logging.ERROR, logger=CONFIG_LOGGER):
        _settings(pdax_otp_secret=_VALID_OTP_SECRET)
    assert _errors(caplog) == []


def test_otp_secret_padding_matches_the_totp_module(caplog):
    # An unpadded, lowercased, space-separated seed is what a console copy
    # looks like; totp.py accepts it, so the startup report must too.
    from app.pdax.totp import totp_now

    unpadded = "jbsw y3dp ehpk 3pxp"
    with caplog.at_level(logging.ERROR, logger=CONFIG_LOGGER):
        _settings(pdax_otp_secret=unpadded)
    assert _errors(caplog) == []
    assert totp_now(unpadded, timestamp=0) == totp_now(_VALID_OTP_SECRET, timestamp=0)


def test_unset_otp_secret_is_quiet(caplog):
    with caplog.at_level(logging.ERROR, logger=CONFIG_LOGGER):
        _settings(pdax_otp_secret="")
    assert _errors(caplog) == []


def test_demo_defaults_report_nothing(caplog):
    with caplog.at_level(logging.ERROR, logger=CONFIG_LOGGER):
        s = _settings()
    assert _errors(caplog) == []
    assert s.pdax_environment == "uat"
