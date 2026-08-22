"""PDAX health routes: the public probe is non-actuating (settings only);
the real handshake probe lives on the API-key-guarded /health/deep route —
and is skipped, not performed, while API_KEY is unset (the guard is a no-op
then, so an anonymous caller could otherwise drive real PDAX logins)."""

from __future__ import annotations

from app.config import settings
from app.pdax.errors import PdaxError


def _configure_creds(monkeypatch, username="acct@example.com", password="pw"):
    monkeypatch.setattr(settings, "pdax_username", username)
    monkeypatch.setattr(settings, "pdax_password", password)


def test_public_health_never_dials_pdax(client, monkeypatch):
    _configure_creds(monkeypatch)

    def boom():  # any client construction/use means the route actuated
        raise AssertionError("public /health must not touch the PDAX client")

    monkeypatch.setattr("app.routers.pdax.get_pdax_client", boom)

    r = client.get("/api/pdax/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["environment"] == settings.pdax_environment
    assert body["configured"] is True


def test_health_deep_requires_api_key(client, hermetic_settings):
    hermetic_settings.api_key = "secret-key"
    r = client.get("/api/pdax/health/deep")
    assert r.status_code == 401


def test_health_deep_without_api_key_is_skipped_and_never_dials_pdax(client, monkeypatch):
    # api_key is "" (hermetic default), so require_api_key is a no-op and the
    # route answers anonymously — it must then refuse to perform the real
    # login, or anyone could lock the institutional account.
    _configure_creds(monkeypatch)

    def boom():
        raise AssertionError("deep /health must not touch the PDAX client without an API key")

    monkeypatch.setattr("app.routers.pdax.get_pdax_client", boom)

    r = client.get("/api/pdax/health/deep")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "skipped"
    assert body["environment"] == settings.pdax_environment
    assert "API_KEY" in body["reason"]


def test_health_deep_reports_unconfigured(client, hermetic_settings, monkeypatch):
    hermetic_settings.api_key = "secret-key"
    _configure_creds(monkeypatch, username="", password="")
    r = client.get("/api/pdax/health/deep", headers={"X-API-Key": "secret-key"})
    assert r.status_code == 200
    assert r.json()["status"] == "unconfigured"


class _FakeClient:
    def __init__(self, error: PdaxError | None = None) -> None:
        self._error = error

    async def healthcheck(self) -> None:
        if self._error:
            raise self._error


def test_health_deep_reports_ok(client, hermetic_settings, monkeypatch):
    hermetic_settings.api_key = "secret-key"
    _configure_creds(monkeypatch)
    monkeypatch.setattr("app.routers.pdax.get_pdax_client", lambda: _FakeClient())
    r = client.get("/api/pdax/health/deep", headers={"X-API-Key": "secret-key"})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_health_deep_reports_degraded(client, hermetic_settings, monkeypatch):
    hermetic_settings.api_key = "secret-key"
    _configure_creds(monkeypatch)
    err = PdaxError("login failed", code="InvalidCredentials", http_status=401)
    monkeypatch.setattr("app.routers.pdax.get_pdax_client", lambda: _FakeClient(err))
    r = client.get("/api/pdax/health/deep", headers={"X-API-Key": "secret-key"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"
    assert body["code"] == "InvalidCredentials"
