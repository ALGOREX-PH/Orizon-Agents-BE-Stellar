"""Partial-credit refund — story 4.01, Option A (settler-funded platform credit).

The deployed `PaymentEscrow` has no refund entrypoint and never takes custody:
`charge` sends USDC payer → agent-owner directly, so there is nothing to reverse.
A dispute refund is therefore a **new transfer from the platform**, not a
clawback — the settler credits the buyer over the asset SAC, and the dispute is
recorded on-chain under a *derived* job id so it clears the ReputationLedger
replay guard (R12).

Honest trust model, disclosed in every artifact (SOW §3.8 standard):
  - the **platform funds** the credit — the disputed agent's only consequence is
    reputational, never a seizure of its funds;
  - the **platform adjudicates** the dispute — there is no on-chain arbitration
    in this sprint.
"""

from __future__ import annotations

import hashlib

# Refund policy — the credited fraction of the DISPUTED STEP's settled charge.
# A dispute credits the buyer for the step that failed; 1.0 = the full step
# price. Stated up front so buyer and operator both know the terms in advance,
# rather than a case-by-case judgement (product rule).
DEFAULT_CREDITED_FRACTION = 1.0

# Rating written for an upheld dispute, on the same 0..100 scale the settler's
# synthetic rating uses — low, so a disputed agent's reputation reflects it.
DISPUTE_RATING = 10


def dispute_job_id(job_id: bytes) -> bytes:
    """Derive the dispute's job id from the settled job's id (R12).

    `ReputationLedger.submit` checks its replay guard on `Rated(agent_id,
    job_id)` before it reads `kind`, and the settler has already auto-rated the
    settled job under `job_id` — so a dispute rating on the same pair returns
    `Error::Replay`. A distinct but deterministic derived id lets the dispute be
    recorded on-chain, still linkable to the job it disputes.
    """
    return hashlib.sha256(job_id + b"dispute").digest()[:16]


def credited_amount_usdc(step_charged_usdc: float, fraction: float = DEFAULT_CREDITED_FRACTION) -> float:
    """The USDC credited back to the buyer for a disputed step, clamped to
    [0, the step charge]. `fraction` outside [0, 1] is clamped."""
    fraction = min(max(fraction, 0.0), 1.0)
    return round(max(step_charged_usdc, 0.0) * fraction, 7)
