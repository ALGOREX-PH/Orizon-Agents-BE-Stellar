#!/usr/bin/env python3
"""Verify a testnet agent registration for the story-1.07 evidence gate.

    python scripts/verify_registration.py --tx <hash> --agent <id> \
        [--owner G...] [--api-base https://...] [--network testnet]

Checks Horizon (the tx exists, succeeded, and was signed by the operator's
wallet) and — when --api-base points at the marketplace API — that the agent is
listed with on-chain provenance owned by that wallet, distinct from the seeded
catalog. Prints a PASS/FAIL report and exits non-zero if any check fails, so it
can gate CI or a reviewer's spot-check. The parsing/assertion logic lives in
app.evidence (unit-tested); this is the thin network wrapper.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make `python scripts/verify_registration.py` work from the repo root: put the
# repo root on sys.path so the `app` package resolves without PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402  (after the sys.path bootstrap above)

from app.evidence import (  # noqa: E402
    Check,
    all_passed,
    check_marketplace_listing,
    check_registration_tx,
)


def _horizon_base(network: str) -> str:
    return "https://horizon.stellar.org" if network == "public" else "https://horizon-testnet.stellar.org"


def _expert(kind: str, id_: str, network: str) -> str:
    seg = "public" if network == "public" else "testnet"
    return f"https://stellar.expert/explorer/{seg}/{kind}/{id_}"


def main() -> int:
    p = argparse.ArgumentParser(description="Verify a testnet agent registration (story 1.07).")
    p.add_argument("--tx", required=True, help="registration transaction hash")
    p.add_argument("--agent", required=True, help="agent id")
    p.add_argument("--owner", help="expected owner G-address (optional cross-check)")
    p.add_argument("--api-base", help="marketplace API base, e.g. https://...onrender.com")
    p.add_argument("--network", default="testnet", choices=["testnet", "public"])
    args = p.parse_args()

    checks: list[Check] = []
    source: str | None = None

    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        tx_resp = client.get(f"{_horizon_base(args.network)}/transactions/{args.tx}")
        if tx_resp.status_code != 200:
            checks.append(Check("tx_on_horizon", False, f"Horizon returned {tx_resp.status_code} for the tx hash"))
        else:
            tx = tx_resp.json()
            source = tx.get("source_account")
            checks.append(Check("tx_on_horizon", True, "transaction found on Horizon"))
            checks.extend(check_registration_tx(tx, args.owner))

        if args.api_base:
            base = args.api_base.rstrip("/")
            agents_resp = client.get(f"{base}/api/agents")
            if agents_resp.status_code != 200:
                checks.append(Check("marketplace_reachable", False, f"/api/agents returned {agents_resp.status_code}"))
            else:
                # The Horizon tx source is the authoritative wallet; fall back
                # to --owner when the tx could not be read.
                expected_owner = args.owner or source
                checks.extend(check_marketplace_listing(agents_resp.json(), args.agent, expected_owner))

    print(f"\nRegistration evidence — agent {args.agent} - tx {args.tx[:12]}...\n")
    for c in checks:
        print(f"  [{'PASS' if c.ok else 'FAIL'}] {c.name}: {c.detail}")
    print(f"\n  stellar.expert (tx):      {_expert('tx', args.tx, args.network)}")
    if args.owner or source:
        print(f"  stellar.expert (account): {_expert('account', args.owner or source or '', args.network)}")

    ok = all_passed(checks)
    print(f"\n  VERDICT: {'PASS - registration verified' if ok else 'FAIL - see checks above'}\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
