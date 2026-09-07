"""Story 1.06 spike — endpoint-binding ownership proof (Candidate A, AC4).

Binding an operator URL to an on-chain agent id must require nothing but a
signature from the wallet that owns the agent — no account, password, email, or
API key. These tests exercise the challenge/verify prototype directly with a
real Stellar keypair.
"""

from __future__ import annotations

import base64

from stellar_sdk import Keypair

from app.services.external_binding import issue_challenge, verify_challenge


def _sign(kp: Keypair, nonce: str) -> str:
    """What StellarWalletsKit signMessage produces: base64 of the ed25519
    signature over the challenge nonce's UTF-8 bytes."""
    return base64.b64encode(kp.sign(nonce.encode("utf-8"))).decode("ascii")


def test_valid_wallet_signature_binds_and_is_single_use() -> None:
    owner = Keypair.random()
    nonce = issue_challenge("ext_a")

    assert verify_challenge("ext_a", owner.public_key, _sign(owner, nonce)) is True
    # single use: the proven nonce is consumed, so replaying it cannot bind again
    assert verify_challenge("ext_a", owner.public_key, _sign(owner, nonce)) is False


def test_tampered_signature_is_rejected() -> None:
    owner = Keypair.random()
    nonce = issue_challenge("ext_b")
    # signs bytes that are not the issued nonce
    assert verify_challenge("ext_b", owner.public_key, _sign(owner, nonce + "tamper")) is False


def test_signature_from_a_different_wallet_is_rejected() -> None:
    owner = Keypair.random()
    attacker = Keypair.random()
    nonce = issue_challenge("ext_c")
    # a valid signature — but from a wallet that does not own the agent
    assert verify_challenge("ext_c", owner.public_key, _sign(attacker, nonce)) is False
