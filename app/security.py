"""
Lightweight, dependency-free hardening primitives.

- `require_api_key` — optional FastAPI dependency. When `settings.api_key`
  is unset (the default for the public demo) it is a no-op; when set, the
  request must carry a matching `X-API-Key` header or it is rejected 401.
- `RateLimitMiddleware` — per-client-IP sliding-window rate limiter as a
  pure ASGI middleware (no external deps). Window/limit come from settings;
  liveness paths and CORS preflights are exempt. Rate-limited responses
  carry `X-RateLimit-Limit` / `X-RateLimit-Remaining` headers.
- `RequestContextMiddleware` — pure ASGI request-id propagation + one-line
  INFO access log per request (method, path, status, duration, id).
"""
from __future__ import annotations

import json
import logging
import math
import secrets
import time
import uuid
from collections import deque
from typing import Any, Optional

from fastapi import Header, HTTPException

from .config import settings

logger = logging.getLogger(__name__)

# Paths that must never be throttled (probes + root ping).
EXEMPT_PATHS = frozenset({"/", "/health", "/readiness"})


async def require_api_key(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> None:
    """No-op unless API_KEY is configured; then enforce the X-API-Key header."""
    expected = settings.api_key
    if not expected:
        return
    # Compare utf-8 bytes, not str: compare_digest raises TypeError on
    # non-ASCII str input (Starlette decodes headers latin-1), which would
    # turn a bad key into a 500 instead of a 401.
    if x_api_key is None or not secrets.compare_digest(
        x_api_key.encode("utf-8", "ignore"), expected.encode("utf-8")
    ):
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
        request_id = (
            (headers.get(b"x-request-id") or b"").decode("latin-1").strip()[:64]
        )
        if not request_id:
            request_id = uuid.uuid4().hex[:16]

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
                        "%s %s -> %s in %.1fms [%s]",
                        method,
                        path,
                        message.get("status"),
                        duration_ms,
                        request_id,
                    )
            await send(message)

        await self.app(scope, receive, send_with_context)


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
        limit: Optional[int] = None,
        window_seconds: float = 60.0,
    ) -> None:
        self.app = app
        self.limit = settings.rate_limit_per_minute if limit is None else limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._since_sweep = 0

    def _client_key(self, scope: dict) -> str:
        headers = dict(scope.get("headers") or [])
        fwd = headers.get(b"x-forwarded-for")
        if fwd:
            # Key on the LAST hop: proxies append, so the leftmost entries
            # are client-controlled — trusting them would let a caller rotate
            # fake IPs to bypass the limiter and bloat the bucket table.
            last = fwd.decode("latin-1").split(",")[-1].strip()
            if last:
                return last
        client = scope.get("client")
        return client[0] if client else "unknown"

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
        key = self._client_key(scope)
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
                {"error": {"code": "rate_limited", "message": "too many requests"}}
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
