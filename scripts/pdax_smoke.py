"""
Offline self-check for the PDAX integration.

Exercises config resolution, TOTP, model coercion, the reference tables, and
router registration — all without hitting the network. Run after changing any
app/pdax/* module to confirm the package still wires up.

Usage:
    cd ~/Websites-2026/orizon-agents-FE-Stellar/backend
    python3 scripts/pdax_smoke.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# let `import app.*` work when run as a standalone script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.pdax import constants as pc
from app.pdax.config import BASE_URLS, base_url
from app.pdax.models.trade import FirmQuoteRequest, Quote
from app.pdax.totp import totp_now
from app.routers.pdax import router


def main() -> None:
    # 1. environment resolution
    assert base_url() in BASE_URLS.values(), "base_url not in known environments"
    print("base_url:", base_url())

    # 2. TOTP determinism (RFC 6238 test vector seed)
    code = totp_now("JBSWY3DPEHPK3PXP", timestamp=0)
    assert len(code) == 6 and code.isdigit(), "totp must be 6 digits"
    print("totp(t=0):", code)

    # 3. model coercion (string quantity -> float)
    FirmQuoteRequest(quote_currency="USDC", side="sell", base_quantity="100")
    q = Quote(
        quote_currency="USDC", base_currency="PHP", side="sell",
        base_quantity="100", price=55, total_amount=5500,
    )
    assert isinstance(q.base_quantity, float) and q.total_amount == 5500
    print("model coercion: ok")

    # 4. reference tables non-empty + Stellar token present
    assert "USDCXLM" in pc.TOKEN_NETWORKS and pc.TOKEN_NETWORKS["USDCXLM"] == "Stellar"
    assert pc.is_valid_bank_code("BAUBPPH") and pc.is_accepted_country("Philippines")
    print("reference tables:", len(pc.BANK_CODES), "banks,", len(pc.ACCEPTED_COUNTRIES), "countries")

    # 5. router exposes the full surface
    paths = {r.path for r in router.routes}  # type: ignore[attr-defined]
    print("router routes:", len(paths))
    assert "/pdax/balances" in paths and "/pdax/trade/order" in paths

    print("PDAX smoke: ALL OK")


if __name__ == "__main__":
    main()
