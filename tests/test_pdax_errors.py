"""Curated PDAX error envelope: clients get stable snake_case codes, never
the raw upstream message; upstream 5xx/auth failures collapse to 502."""

from __future__ import annotations

import logging

from app.pdax.errors import ERROR_CODES, ORIZON_CODES, PdaxError, orizon_code
from app.routers.pdax import _fail


def test_every_documented_code_has_an_orizon_code():
    assert set(ERROR_CODES) == set(ORIZON_CODES)
    for slug in ORIZON_CODES.values():
        assert slug == slug.lower()
        assert " " not in slug


def test_orizon_code_lookup_and_fallback():
    assert orizon_code("OT010006") == "insufficient_balance"
    assert orizon_code("AccountLocked") == "account_locked"
    assert orizon_code("TotallyUnknown") == "pdax_error"
    assert orizon_code(None) == "pdax_error"


def test_fail_maps_client_input_4xx_through():
    exc = _fail(PdaxError("Malformed parameters.", code="OT010026", http_status=422))
    assert exc.status_code == 422
    assert exc.detail == "malformed_parameters"


def test_fail_unknown_code_uses_fallback():
    exc = _fail(PdaxError("weird", code="XX999", http_status=400))
    assert exc.status_code == 400
    assert exc.detail == "pdax_error"


def test_fail_collapses_upstream_auth_to_502():
    for status in (401, 403):
        exc = _fail(PdaxError("token rejected", code="PAP0401", http_status=status))
        assert exc.status_code == 502
        assert exc.detail == "upstream_unavailable"


def test_fail_collapses_5xx_and_transport_to_502():
    exc = _fail(PdaxError("boom", code="PAP0500", http_status=500))
    assert exc.status_code == 502
    assert exc.detail == "upstream_unavailable"
    exc = _fail(PdaxError("PDAX transport error: timeout"))  # no http_status
    assert exc.status_code == 502
    assert exc.detail == "upstream_unavailable"


def test_fail_never_leaks_upstream_message(caplog):
    secret_message = "internal ledger id 12345 rejected by core"
    with caplog.at_level(logging.WARNING, logger="app.routers.pdax"):
        exc = _fail(PdaxError(secret_message, code="OT010006", http_status=400, request_id="rq-9"))
    assert secret_message not in str(exc.detail)
    assert exc.detail == "insufficient_balance"
    # ...but the full upstream envelope IS logged for operators.
    assert any(secret_message in r.getMessage() for r in caplog.records)
    assert any("rq-9" in r.getMessage() for r in caplog.records)


def test_route_level_curated_envelope(client, monkeypatch):
    async def failing_balances(client_, currency=None):
        raise PdaxError("Insufficient balance.", code="OT010006", http_status=400)

    monkeypatch.setattr("app.routers.pdax.get_pdax_client", lambda: object())
    monkeypatch.setattr("app.pdax.balances.get_balances", failing_balances)
    r = client.get("/api/pdax/balances")
    assert r.status_code == 400
    assert r.json()["detail"] == "insufficient_balance"
