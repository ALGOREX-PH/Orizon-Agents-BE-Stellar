"""Story 1.07 — registration evidence verification logic (app/evidence.py).

Pure checks over Horizon-tx and /api/agents JSON that make the Milestone 1 exit
gate machine-verifiable: a successful tx signed by the claimed wallet (AC1) and
an on-chain marketplace listing owned by it, distinct from the seeded catalog
(AC2).
"""

from __future__ import annotations

from app.evidence import all_passed, check_marketplace_listing, check_registration_tx

_WALLET = "GBI2I3WLMP2Q6L26G7CBKRPP5WJ6G3GGYJHWALOJ7D6EBRGL5OZAADBH"


def test_registration_tx_all_checks_pass_for_a_successful_tx() -> None:
    checks = check_registration_tx({"successful": True, "source_account": _WALLET}, expected_source=_WALLET)
    assert all_passed(checks)
    assert {c.name for c in checks} == {"tx_succeeded", "tx_has_source", "source_matches"}


def test_registration_tx_flags_a_failed_tx() -> None:
    checks = check_registration_tx({"successful": False, "source_account": _WALLET})
    assert {c.name: c.ok for c in checks}["tx_succeeded"] is False
    assert not all_passed(checks)


def test_registration_tx_flags_a_wrong_source() -> None:
    checks = check_registration_tx({"successful": True, "source_account": _WALLET}, expected_source="GDIFFERENT")
    assert next(c for c in checks if c.name == "source_matches").ok is False


def test_registration_tx_without_expected_source_skips_the_match_check() -> None:
    checks = check_registration_tx({"successful": True, "source_account": _WALLET})
    assert "source_matches" not in {c.name for c in checks}


def test_registration_tx_flags_a_missing_source() -> None:
    checks = check_registration_tx({"successful": True})
    assert next(c for c in checks if c.name == "tx_has_source").ok is False


def test_marketplace_listing_passes_for_an_onchain_agent() -> None:
    agents = [
        {"id": "agt_01h8", "source": "seeded"},
        {"id": "weather_bot", "source": "onchain", "owner": _WALLET},
    ]
    checks = check_marketplace_listing(agents, "weather_bot", expected_owner=_WALLET)
    assert all_passed(checks)
    assert {c.name for c in checks} == {"agent_listed", "onchain_provenance", "owner_matches"}


def test_marketplace_listing_flags_a_missing_agent() -> None:
    checks = check_marketplace_listing([{"id": "agt_01h8", "source": "seeded"}], "ghost")
    assert next(c for c in checks if c.name == "agent_listed").ok is False
    assert not all_passed(checks)


def test_marketplace_listing_flags_a_seeded_agent_as_not_onchain() -> None:
    checks = check_marketplace_listing([{"id": "agt_01h8", "source": "seeded"}], "agt_01h8")
    by = {c.name: c.ok for c in checks}
    assert by["agent_listed"] is True
    assert by["onchain_provenance"] is False


def test_marketplace_listing_flags_a_wrong_owner() -> None:
    agents = [{"id": "weather_bot", "source": "onchain", "owner": "GOTHER"}]
    checks = check_marketplace_listing(agents, "weather_bot", expected_owner=_WALLET)
    assert next(c for c in checks if c.name == "owner_matches").ok is False


def test_all_passed_is_false_for_no_checks() -> None:
    assert all_passed([]) is False
