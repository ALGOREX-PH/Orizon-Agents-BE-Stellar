"""
PDAX HTTP transport.

`PdaxClient` owns a long-lived httpx.AsyncClient plus a `PdaxAuth` token
manager. Every authenticated call injects the `access_token` + `id_token`
headers PDAX expects, parses the JSON body, and raises `PdaxError` on any
non-2xx response (preserving code / name / message / requestId).

httpx joins a relative request path onto `base_url` only when the base ends
with "/" and the path has no leading slash — both enforced here, so callers
pass paths like "pdax-institution/v1/balances".
"""
from __future__ import annotations

import time
from typing import Any

import httpx

from ..config import settings
from .auth import PdaxAuth
from .config import base_url
from .errors import PdaxError
from .observability import log_call
from .resilience import RateLimiter, with_retries


class PdaxClient:
    def __init__(self, timeout: float = 30.0) -> None:
        base = base_url().rstrip("/") + "/"
        self._http = httpx.AsyncClient(base_url=base, timeout=timeout)
        self._auth = PdaxAuth()
        self._limiter = RateLimiter(
            settings.pdax_rate_limit_per_sec, settings.pdax_rate_limit_burst
        )
        self._retries = max(1, settings.pdax_max_retries)

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        authenticated: bool = True,
    ) -> Any:
        clean_params = {k: v for k, v in (params or {}).items() if v is not None}
        rel = path.lstrip("/")

        async def _send(attempt: int) -> Any:
            await self._limiter.acquire()
            headers: dict[str, str] = {"Content-Type": "application/json"}
            if authenticated:
                headers.update(await self._auth.access_headers(self._http))
            t0 = time.monotonic()
            try:
                resp = await self._http.request(
                    method, rel, params=clean_params or None, json=json, headers=headers
                )
            except httpx.HTTPError as e:
                log_call(method, rel, None, (time.monotonic() - t0) * 1000, attempt=attempt, error=str(e))
                raise PdaxError(f"PDAX transport error: {e}") from e
            log_call(method, rel, resp.status_code, (time.monotonic() - t0) * 1000, attempt=attempt)
            return _parse(resp)

        return await with_retries(_send, attempts=self._retries)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def healthcheck(self) -> None:
        """Verify the PDAX auth handshake (cached when possible). Raises
        PdaxError if credentials, MFA, or connectivity are not in order."""
        await self._auth.access_headers(self._http)


def _parse(resp: httpx.Response) -> Any:
    try:
        data = resp.json() if resp.content else {}
    except ValueError:
        data = {"message": resp.text}
    if resp.status_code >= 400:
        body = data if isinstance(data, dict) else {}
        raise PdaxError(
            body.get("message") or f"PDAX request failed ({resp.status_code})",
            code=body.get("code"),
            name=body.get("name"),
            http_status=resp.status_code,
            request_id=body.get("requestId") or body.get("request_id"),
            raw=data,
        )
    return data


_client: PdaxClient | None = None


def get_pdax_client() -> PdaxClient:
    """Return the process-wide PDAX client (lazily constructed)."""
    global _client
    if _client is None:
        _client = PdaxClient()
    return _client
