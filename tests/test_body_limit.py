"""Request-body size limits: declared Content-Length, streamed chunked
bodies, per-path overrides, and the 413 error envelope."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.security import BodyLimitMiddleware


def _echo_app() -> Any:
    """Raw ASGI app reading the whole body — mirrors the real stack, where
    BodyLimitMiddleware sits inside ServerErrorMiddleware, so a limit breach
    raised from `receive` propagates straight up to the middleware."""

    async def echo(scope: dict, receive: Any, send: Any) -> None:
        total, more = 0, True
        while more:
            message = await receive()
            total += len(message.get("body", b""))
            more = message.get("more_body", False)
        body = str(total).encode()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": body})

    return echo


def test_oversized_content_length_is_413():
    c = TestClient(BodyLimitMiddleware(_echo_app(), limit=100))
    r = c.post("/echo", content=b"x" * 101)
    assert r.status_code == 413
    body = r.json()
    assert body["detail"] == "request_too_large"
    assert body["error"]["code"] == "request_too_large"
    assert body["error"]["message"] == "request body exceeds the size limit"
    assert "request_id" in body["error"]


def test_oversized_chunked_body_is_413():
    c = TestClient(BodyLimitMiddleware(_echo_app(), limit=100))
    # An iterator body is sent without Content-Length (chunked), so only the
    # streamed byte counting can catch it.
    r = c.post("/echo", content=iter([b"x" * 40, b"y" * 40, b"z" * 40]))
    assert r.status_code == 413
    assert r.json()["detail"] == "request_too_large"


def test_body_at_limit_passes():
    c = TestClient(BodyLimitMiddleware(_echo_app(), limit=100))
    r = c.post("/echo", content=b"x" * 100)
    assert r.status_code == 200
    assert r.text == "100"


def test_per_path_override_tightens_limit():
    c = TestClient(BodyLimitMiddleware(_echo_app(), limit=1000, path_limits={"/echo": 10}))
    assert c.post("/echo", content=b"x" * 11).status_code == 413
    assert c.post("/echo", content=b"x" * 10).status_code == 200


def test_app_rejects_oversized_body_with_context_headers(client):
    r = client.post(
        "/api/agents",
        content=b"x" * (1_048_576 + 1),
        headers={"content-type": "application/octet-stream", "X-Request-ID": "big-body-1"},
    )
    assert r.status_code == 413
    # The 413 short-circuits inside the header/request-id layers, so it still
    # carries the hardening headers and the caller's request id.
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-request-id"] == "big-body-1"
    assert r.json()["error"]["request_id"] == "big-body-1"


def test_pdax_webhook_path_has_tighter_limit(client):
    r = client.post("/api/pdax/webhooks/receive", content=b"x" * 65_537)
    assert r.status_code == 413
    assert r.json()["detail"] == "request_too_large"


def test_normal_requests_unaffected(client):
    assert client.get("/api/agents").status_code == 200
    r = client.post("/api/pdax/webhooks/receive", content=b"{}", headers={"content-type": "application/json"})
    assert r.status_code != 413
