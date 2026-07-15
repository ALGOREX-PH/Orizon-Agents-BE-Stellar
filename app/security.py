"""
Lightweight, dependency-free hardening primitives.

- `require_api_key` — optional FastAPI dependency. When `settings.api_key`
  is unset (the default for the public demo) it is a no-op; when set, the
  request must carry a matching `X-API-Key` header or it is rejected 401.
- `RateLimitMiddleware` — per-client-IP sliding-window rate limiter as a
  pure ASGI middleware (no external deps). Window/limit come from settings;
  liveness paths and CORS preflights are exempt.
"""
from __future__ import annotations

import json
import math
import secrets
import time
from collections import deque
from typing import Any, Optional

from fastapi import Header, HTTPException

from .config import settings

# Paths that must never be throttled (probes + root ping).
EXEMPT_PATHS = frozenset({"/", "/health", "/readiness"})


async def require_api_key(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> None:
    """No-op unless API_KEY is configured; then enforce the X-API-Key header."""
    expected = settings.api_key
    if not expected:
        return
    if x_api_key is None or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="invalid_api_key")


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
            first = fwd.decode("latin-1").split(",")[0].strip()
            if first:
                return first
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
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        dq.append(now)
        await self.app(scope, receive, send)
