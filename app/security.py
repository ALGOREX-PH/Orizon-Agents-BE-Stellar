"""
Lightweight, dependency-free hardening primitives.

- `require_api_key` — optional FastAPI dependency. When `settings.api_key`
  is unset (the default for the public demo) it is a no-op; when set, the
  request must carry a matching `X-API-Key` header or it is rejected 401.
- `RateLimitMiddleware` — per-client-IP sliding-window rate limiter as a
  pure ASGI middleware (no external deps). Window/limit come from settings;
  liveness paths and CORS preflights are exempt. Rate-limited responses
  carry `X-RateLimit-Limit` / `X-RateLimit-Remaining` headers.
- `BodyLimitMiddleware` — pure ASGI request-body size cap. Rejects declared
  Content-Length over the limit up front and counts streamed (chunked)
  bodies as the app reads them, answering 413 either way. Per-path
  overrides tighten the budget for routes that buffer the whole body.
- `RequestContextMiddleware` — pure ASGI request-id propagation + one-line
  INFO access log per request (method, path, status, duration, id).
"""

from __future__ import annotations

import contextvars
import json
import logging
import math
import re
import secrets
import time
import uuid
from collections import deque
from typing import Any

from fastapi import Header, HTTPException

from .config import settings

logger = logging.getLogger(__name__)

# Paths that must never be throttled (probes + root ping), and that stay out
# of the access log. `/api/health` is the SAME liveness probe re-served under
# the frontend proxy's `/api` prefix (routers/health.py): it must be exempt
# identically, or an uptime monitor polling through the proxy would burn the
# shared per-IP budget — every browser behind that egress IP pays for it —
# and would flood the log with probe noise.
EXEMPT_PATHS = frozenset({"/", "/health", "/readiness", "/api/health"})

# Current request's id — set by RequestContextMiddleware, readable from any
# code running in the request's task context (error handlers, log records).
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


# Credential-bearing query values (the SSE routes take `?token=`) must not
# reach the access log; only the parameter name survives.
_TOKEN_QUERY_RE = re.compile(r"(^|&)([^&=]*token)=[^&]*")


def _redacted_target(scope: dict) -> str:
    """Path plus query string, with any `*token=` values masked for logging."""
    path = scope.get("path", "-")
    query = (scope.get("query_string") or b"").decode("latin-1")
    if not query:
        return str(path)
    return f"{path}?{_TOKEN_QUERY_RE.sub(r'\1\2=***', query)}"


class RequestIdLogFilter(logging.Filter):
    """Stamp every LogRecord with the current request id ("-" outside a
    request) so formatters can correlate service logs with access lines."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def client_key(scope: dict) -> str:
    """Resolve the client key used for rate limiting and access logs.

    Keys on the LAST X-Forwarded-For hop: proxies append, so the leftmost
    entries are client-controlled — trusting them would let a caller rotate
    fake IPs to bypass the limiter and bloat the bucket table.
    """
    headers = dict(scope.get("headers") or [])
    fwd = headers.get(b"x-forwarded-for")
    if fwd:
        last = fwd.decode("latin-1").split(",")[-1].strip()
        if last:
            return last
    client = scope.get("client")
    return client[0] if client else "unknown"


async def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    """No-op unless API_KEY is configured; then enforce the X-API-Key header."""
    expected = settings.api_key
    if not expected:
        return
    # Compare utf-8 bytes, not str: compare_digest raises TypeError on
    # non-ASCII str input (Starlette decodes headers latin-1), which would
    # turn a bad key into a 500 instead of a 401.
    if x_api_key is None or not secrets.compare_digest(x_api_key.encode("utf-8", "ignore"), expected.encode("utf-8")):
        raise HTTPException(status_code=401, detail="invalid_api_key")


class RequestContextMiddleware:
    """Request-id + access-log middleware (pure ASGI, no external deps).

    Takes the caller's `X-Request-ID` (or generates a short one), echoes it
    on the response so clients can quote it, and logs one INFO line per
    request — method, path, status, duration, id — so any response can be
    correlated with server logs. Probe paths (EXEMPT_PATHS) still get the
    header but are not logged, to keep the log free of health-check noise.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        request_id = (headers.get(b"x-request-id") or b"").decode("latin-1").strip()[:64]
        if not request_id:
            request_id = uuid.uuid4().hex[:16]

        # Deliberately never reset: the 500 handler runs on the outermost
        # ServerErrorMiddleware layer AFTER this frame has unwound, so a
        # finally-reset would erase the id before that handler reads it.
        # Each request runs in its own task context, so nothing leaks across
        # requests.
        request_id_var.set(request_id)
        # Also visible to route handlers as request.state.request_id.
        scope.setdefault("state", {})["request_id"] = request_id

        method = scope.get("method", "-")
        path = scope.get("path", "-")
        started = time.monotonic()

        async def send_with_context(message: dict) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers") or []) + [
                    (b"x-request-id", request_id.encode("latin-1")),
                ]
                if path not in EXEMPT_PATHS:
                    duration_ms = (time.monotonic() - started) * 1000.0
                    logger.info(
                        "%s %s -> %s in %.1fms [%s] client=%s",
                        method,
                        # Path + query with token values masked: SSE auth
                        # tokens ride in the query string and must not be
                        # recoverable from logs.
                        _redacted_target(scope),
                        message.get("status"),
                        duration_ms,
                        request_id,
                        # Same key the rate limiter buckets on, so a 429 in
                        # the log can be traced to the client that caused it.
                        client_key(scope),
                    )
            await send(message)

        await self.app(scope, receive, send_with_context)


class _BodyTooLarge(Exception):
    """Internal signal: a streamed request body crossed the size limit."""


class BodyLimitMiddleware:
    """Cap request-body size (pure ASGI, no deps). Nothing else in the stack
    limits bodies — uvicorn and Starlette accept arbitrarily large uploads —
    so without this a single request can exhaust worker memory (the PDAX
    webhook route, for one, buffers the whole body before its HMAC check).

    A declared Content-Length above the limit is refused immediately with
    413; chunked/streamed bodies are counted as the app reads them and
    aborted at the limit. 413 bodies use the app's unified error envelope.
    """

    DEFAULT_LIMIT = 1_048_576  # 1 MiB — comfortably above any legitimate payload
    # Routes that buffer the entire body up front get a tighter budget.
    PATH_LIMITS: dict[str, int] = {"/api/pdax/webhooks/receive": 65_536}

    def __init__(
        self,
        app: Any,
        limit: int | None = None,
        path_limits: dict[str, int] | None = None,
    ) -> None:
        self.app = app
        self.limit = self.DEFAULT_LIMIT if limit is None else limit
        self.path_limits = dict(self.PATH_LIMITS) if path_limits is None else path_limits

    @staticmethod
    async def _send_413(send: Any) -> None:
        body = json.dumps(
            {
                # Same envelope the app's exception handlers emit.
                "detail": "request_too_large",
                "error": {
                    "code": "request_too_large",
                    "message": "request body exceeds the size limit",
                    "request_id": request_id_var.get(),
                },
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = self.path_limits.get(scope.get("path", ""), self.limit)
        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > limit:
                    await self._send_413(send)
                    return
            except ValueError:
                pass  # malformed length — the server rejects it downstream

        # Chunked (or lying) bodies: meter the bytes the app actually reads.
        received = 0
        response_started = False

        async def receive_limited() -> dict:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _BodyTooLarge  # unwinds the endpoint mid-read
            return message

        async def send_tracking(message: dict) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive_limited, send_tracking)
        except _BodyTooLarge:
            if response_started:
                raise  # too late for a 413 — let the server drop the connection
            await self._send_413(send)


class RateLimitMiddleware:
    """Sliding-window per-client-IP limiter. In-process only (single worker).

    Timestamps per IP live in a dict of deques; old entries are pruned on
    each hit and the whole table is swept periodically so idle IPs don't
    accumulate. All mutation happens synchronously between awaits, so it is
    safe under a single asyncio event loop without locks.
    """

    _SWEEP_EVERY = 1024  # requests between full-table sweeps

    def __init__(
        self,
        app: Any,
        limit: int | None = None,
        window_seconds: float = 60.0,
    ) -> None:
        self.app = app
        self.limit = settings.rate_limit_per_minute if limit is None else limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._since_sweep = 0

    def _sweep(self, now: float) -> None:
        cutoff = now - self.window
        stale = [ip for ip, dq in self._hits.items() if not dq or dq[-1] < cutoff]
        for ip in stale:
            del self._hits[ip]

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if (
            scope["type"] != "http"
            or self.limit <= 0
            or scope.get("method") == "OPTIONS"
            or scope.get("path") in EXEMPT_PATHS
        ):
            await self.app(scope, receive, send)
            return

        now = time.monotonic()
        key = client_key(scope)
        dq = self._hits.setdefault(key, deque())
        cutoff = now - self.window
        while dq and dq[0] <= cutoff:
            dq.popleft()

        self._since_sweep += 1
        if self._since_sweep >= self._SWEEP_EVERY:
            self._since_sweep = 0
            self._sweep(now)

        limit_header = str(self.limit).encode()

        if len(dq) >= self.limit:
            retry_after = max(1, math.ceil(dq[0] + self.window - now))
            body = json.dumps(
                {
                    # Same envelope the app's exception handlers emit: legacy
                    # "detail" plus the structured "error" object.
                    "detail": "rate_limited",
                    "error": {
                        "code": "rate_limited",
                        "message": "too many requests",
                        "request_id": request_id_var.get(),
                    },
                }
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                        (b"retry-after", str(retry_after).encode()),
                        (b"x-ratelimit-limit", limit_header),
                        (b"x-ratelimit-remaining", b"0"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        dq.append(now)
        # Quota headers reflect the window as admitted — the budget left
        # after counting this request.
        remaining = str(max(0, self.limit - len(dq))).encode()

        async def send_with_quota(message: dict) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers") or []) + [
                    (b"x-ratelimit-limit", limit_header),
                    (b"x-ratelimit-remaining", remaining),
                ]
            await send(message)

        await self.app(scope, receive, send_with_quota)
