"""Off-chain endpoint binding — story-1.06 ownership proof (Candidate A).

Binding an operator URL to an on-chain agent id must cost nothing but a
signature from the wallet that owns the agent — no password, email, or API key
(SOW Deliverable 1's whole premise). The flow:

  1. issue_challenge(agent_id) -> nonce. A random, short-lived value stored
     against the agent id.
  2. The operator signs the nonce's UTF-8 bytes with the secret key of the
     agent's on-chain owner (the G-address in the AgentRegistry `Agent`
     struct) — e.g. via StellarWalletsKit signMessage — and base64-encodes the
     signature.
  3. verify_challenge(agent_id, owner, signature_b64) checks that signature
     against `owner` and, on success, consumes the nonce (single use). The
     caller then records the (agent_id -> endpoint_url) binding.

This module is the spike prototype of steps 1 and 3 — pure and testable, with
an in-memory nonce store. The persistent binding table, the bind API endpoint,
and confirming `owner` against the live AgentRegistry are Epic 2.
"""

from __future__ import annotations

import base64
import secrets
import time

from stellar_sdk import Keypair

CHALLENGE_TTL_SECONDS = 300

# agent_id -> (nonce_hex, expiry_epoch). In-memory for the spike; Epic 2 moves
# this behind the binding store so it survives a restart and multiple workers.
_challenges: dict[str, tuple[str, float]] = {}


def issue_challenge(agent_id: str, ttl_seconds: int = CHALLENGE_TTL_SECONDS) -> str:
    """Mint and store a fresh challenge nonce for `agent_id`; return it.

    A new challenge overwrites any outstanding one for the same agent, so an
    earlier nonce cannot be reused once the operator has asked for another.
    """
    nonce = secrets.token_hex(16)
    _challenges[agent_id] = (nonce, time.time() + ttl_seconds)
    return nonce


def verify_challenge(agent_id: str, owner: str, signature_b64: str) -> bool:
    """Verify a base64 ed25519 signature over the outstanding nonce against
    `owner` (a Stellar G-address). Consumes the nonce on success.

    Returns False on any failure — no or expired nonce, malformed owner or
    signature, or a signature that does not verify. Every failure mode
    (BadSignatureError, Ed25519PublicKeyInvalidError, binascii.Error) is a
    ValueError subclass, so one handler covers them without masking real bugs.
    """
    entry = _challenges.get(agent_id)
    if entry is None:
        return False
    nonce, expiry = entry
    if time.time() > expiry:
        _challenges.pop(agent_id, None)
        return False
    try:
        signature = base64.b64decode(signature_b64, validate=True)
        Keypair.from_public_key(owner).verify(nonce.encode("utf-8"), signature)
    except ValueError:
        return False
    _challenges.pop(agent_id, None)  # single use — a proven nonce never verifies twice
    return True
