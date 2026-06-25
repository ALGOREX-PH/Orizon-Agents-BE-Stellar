"""
PDAX environment resolution.

The PDAX institutions API runs in three environments. The base URL is
selected from `settings.pdax_environment` ("production" | "stage" | "uat").
All endpoint paths are versioned under `/pdax-institution/v1` (a few under
`/v2`); see app/pdax/client.py for how paths are joined.
"""
from __future__ import annotations

from ..config import settings

# Base URLs per environment (see PDAX "Getting Started").
BASE_URLS: dict[str, str] = {
    "production": "https://services.pdax.ph/api/pdax-api",
    "stage": "https://stage.services.sandbox.pdax.ph/api/pdax-api",
    "uat": "https://uat.services.sandbox.pdax.ph/api/pdax-api",
}

DEFAULT_ENVIRONMENT = "uat"


def base_url() -> str:
    """Resolve the PDAX base URL for the configured environment."""
    env = (settings.pdax_environment or DEFAULT_ENVIRONMENT).strip().lower()
    if env not in BASE_URLS:
        raise RuntimeError(
            f"unknown PDAX environment {env!r}; expected one of {list(BASE_URLS)}"
        )
    return BASE_URLS[env]


def is_production() -> bool:
    return (settings.pdax_environment or DEFAULT_ENVIRONMENT).strip().lower() == "production"
