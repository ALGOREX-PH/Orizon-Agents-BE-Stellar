"""Evidence verification for a testnet agent registration (story 1.07).

Pure, network-free checks that a registration is real and matches its captured
artifacts, so the Milestone 1 exit gate is machine-verifiable rather than a
manual eyeball of an explorer page. The CLI wrapper
(`scripts/verify_registration.py`) fetches the inputs from Horizon and the
marketplace API and feeds their parsed JSON straight into these functions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Check:
    """One named pass/fail assertion with a human-readable detail line."""

    name: str
    ok: bool
    detail: str


def check_registration_tx(tx: dict[str, Any], expected_source: str | None = None) -> list[Check]:
    """Verify a Horizon transaction record (`GET /transactions/{hash}`) is a
    successful transaction signed by the operator's wallet.

    `expected_source`, when given, asserts the tx source equals the wallet the
    evidence claims — the "with that wallet as source" half of AC1.
    """
    checks: list[Check] = []

    successful = tx.get("successful") is True
    if successful:
        tx_detail = "transaction successful on-chain"
    else:
        tx_detail = f"tx not successful (successful={tx.get('successful')!r})"
    checks.append(Check("tx_succeeded", successful, tx_detail))

    source = tx.get("source_account")
    has_source = isinstance(source, str) and source.startswith("G")
    checks.append(
        Check(
            "tx_has_source",
            has_source,
            f"source {source}" if has_source else f"no valid source account ({source!r})",
        )
    )

    if expected_source is not None:
        matches = source == expected_source
        checks.append(
            Check(
                "source_matches",
                matches,
                "source matches the claimed wallet" if matches else f"source {source} != expected {expected_source}",
            )
        )

    return checks


def check_marketplace_listing(
    agents: list[dict[str, Any]], agent_id: str, expected_owner: str | None = None
) -> list[Check]:
    """Verify the agent is live in `GET /api/agents` with on-chain provenance,
    distinguishable from the 12 seeded agents — AC2. When `expected_owner` is
    given, assert the listing's owner matches the registering wallet.
    """
    checks: list[Check] = []
    match = next((a for a in agents if a.get("id") == agent_id), None)

    present = match is not None
    checks.append(
        Check(
            "agent_listed",
            present,
            f"{agent_id} present in /api/agents" if present else f"{agent_id} not found in /api/agents",
        )
    )
    if match is None:
        return checks

    onchain = match.get("source") == "onchain"
    checks.append(
        Check(
            "onchain_provenance",
            onchain,
            "source=onchain (distinct from the seeded catalog)"
            if onchain
            else f"source={match.get('source')!r}, expected 'onchain'",
        )
    )

    if expected_owner is not None:
        owner = match.get("owner")
        matches = owner == expected_owner
        checks.append(
            Check(
                "owner_matches",
                matches,
                "listing owner matches the tx wallet" if matches else f"listing owner {owner} != {expected_owner}",
            )
        )

    return checks


def all_passed(checks: list[Check]) -> bool:
    """True only when there is at least one check and every check passed."""
    return len(checks) > 0 and all(c.ok for c in checks)
