"""PdaxClient._parse: error payloads become PdaxError with fields populated
(read-only coverage — no network)."""

from __future__ import annotations

import httpx
import pytest

from app.pdax.client import _parse
from app.pdax.errors import PdaxError

_REQ = httpx.Request("GET", "https://pdax.test/api")


def test_parse_error_payload_populates_fields():
    resp = httpx.Response(
        422,
        json={
            "message": "Malformed parameters.",
            "code": "OT010026",
            "name": "MalformedParameters",
            "requestId": "req-123",
        },
        request=_REQ,
    )
    with pytest.raises(PdaxError) as exc:
        _parse(resp)
    e = exc.value
    assert e.message == "Malformed parameters."
    assert e.code == "OT010026"
    assert e.name == "MalformedParameters"
    assert e.http_status == 422
    assert e.request_id == "req-123"
    assert e.raw["code"] == "OT010026"


def test_parse_snake_case_request_id():
    resp = httpx.Response(400, json={"message": "x", "request_id": "rq-9"}, request=_REQ)
    with pytest.raises(PdaxError) as exc:
        _parse(resp)
    assert exc.value.request_id == "rq-9"


def test_parse_non_json_error_body():
    resp = httpx.Response(502, text="upstream fell over", request=_REQ)
    with pytest.raises(PdaxError) as exc:
        _parse(resp)
    assert exc.value.message == "upstream fell over"
    assert exc.value.http_status == 502
    assert exc.value.code is None


def test_parse_error_without_message_uses_status_fallback():
    resp = httpx.Response(500, json={}, request=_REQ)
    with pytest.raises(PdaxError) as exc:
        _parse(resp)
    assert "500" in exc.value.message


def test_parse_success_returns_payload():
    resp = httpx.Response(200, json={"data": [1, 2]}, request=_REQ)
    assert _parse(resp) == {"data": [1, 2]}


def test_parse_empty_success_body():
    resp = httpx.Response(204, request=_REQ)
    assert _parse(resp) == {}
