"""
Lightweight structured logging for PDAX calls.

Every outbound request logs method, path, status, and latency; failures log the
attempt number so retries are visible. Named `observability` (not `logging`) to
avoid shadowing the stdlib module within the package.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("orizon.pdax")


def log_call(
    method: str,
    path: str,
    status: int | None,
    latency_ms: float,
    *,
    attempt: int = 1,
    error: str | None = None,
) -> None:
    if error is not None:
        logger.warning(
            "pdax %s /%s failed in %.0fms (attempt %d): %s",
            method, path, latency_ms, attempt, error,
        )
    else:
        logger.info("pdax %s /%s -> %s in %.0fms", method, path, status, latency_ms)
