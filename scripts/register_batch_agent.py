"""
One-time: register the meta-agent `orizon_batch` on-chain.

Why: Freighter authorizes payment *to a specific agent_id* in PaymentEscrow.
For workflow-level x402 we authorize to a batch agent representing the
orchestrator itself. The backend is the owner (so all testnet XLM flows
to the same admin account during demos).

Usage:
    cd ~/Websites-Services-2026/orizon-agents-BE-Stellar
    .venv/bin/python scripts/register_batch_agent.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# let `import app.*` work when run as a standalone script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stellar_sdk import Keypair, scval as _sv

from app.config import settings
from app.stellar import client as sc


def main() -> None:
    if not settings.stellar_signing_key:
        raise SystemExit("STELLAR_SIGNING_KEY is empty — set it in .env first")

    admin = Keypair.from_secret(settings.stellar_signing_key).public_key
    print(f"admin: {admin}")
    print(f"registry: {sc.contract_ids().agent_registry}")

    args = [
        sc.addr(admin),
        sc.sym("orizon_batch"),
        _sv.to_string("Orizon Batch"),
        _sv.to_vec([sc.sym("workflow")]),
        sc.i128(0),  # free — the authorize max is set by the payer per-workflow
    ]
    try:
        result = sc.invoke_with_server_key(
            sc.contract_ids().agent_registry,
            "register",
            args,
        )
    except Exception as e:
        msg = str(e)
        if "AlreadyExists" in msg or "Contract, #3" in msg:
            print("already registered — nothing to do ✓")
            return
        raise

    print(f"status: {result.get('status')}")
    print(f"tx:     {result.get('hash')}")
    print("done ✓")


if __name__ == "__main__":
    main()
