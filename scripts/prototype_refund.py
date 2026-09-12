#!/usr/bin/env python3
"""Run a real settler-funded partial-credit refund on testnet (story 4.01).

    python scripts/prototype_refund.py --buyer <G...> --amount 0.054

Requires the testnet ``STELLAR_SIGNING_KEY`` (the settler, funded via friendbot)
set in the environment/.env. Prints the refund tx hash — capture it on Stellar
Expert for the D3 evidence bundle. This is the acceptance criterion "a real
refund has landed on testnet", which CI cannot run because it needs a signed
settler transaction. The mechanism itself is unit-tested in
``tests/test_refund_svc.py``.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Make `python scripts/prototype_refund.py` work from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import refund_svc  # noqa: E402  (after the sys.path bootstrap above)


def main() -> int:
    p = argparse.ArgumentParser(description="Settler-funded partial-credit refund (story 4.01).")
    p.add_argument("--buyer", required=True, help="buyer G-address to credit")
    p.add_argument("--amount", required=True, type=float, help="USDC amount to credit")
    args = p.parse_args()

    result = asyncio.run(refund_svc.execute_refund(args.buyer, args.amount))
    tx = result.get("hash")
    status = result.get("status")
    print(f"\n  refund: {args.amount} USDC -> {args.buyer}")
    print(f"  status: {status}")
    print(f"  tx:     {tx}")
    if tx:
        print(f"  expert: https://stellar.expert/explorer/testnet/tx/{tx}")
    print()
    return 0 if status == "SUCCESS" and tx else 1


if __name__ == "__main__":
    sys.exit(main())
