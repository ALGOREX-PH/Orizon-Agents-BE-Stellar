# 7.08 — KYC, payout wallet & tranche record retention (BLO-110)

Epic 7 · Compliance · owner Danielle Bagaforo Meer · retained to sprint close **2026-10-06**.

The durable financial record for the Blue Belt Instaward, maintained by the lead
so disbursement is never held and the money side survives the sprint. Programme
obligation from the Instawards grantee onboarding deck — not a SOW v4 deliverable.

> Sensitive values are placeholders. Fill locally; do **not** commit anything
> marked *do not commit if sensitive*.

## 1. KYC status

| Item | Value |
| --- | --- |
| KYC cleared | **2026-08-19** (TIN ID + Airtable onboarding form) |
| Approved by | Stellar Development Foundation (SDF) |
| Award approved | **2026-08-20** — Instawards "Blue Belt" tier |
| KYC reference / ID | `<Dan to fill — do not commit if sensitive>` |
| TIN name ↔ payee name match | `<Dan to confirm — y/n + date>` |

Disbursement-gating rules (onboarding deck):
- **TIN name on file must match the name receiving funds** — a mismatch is a hold, not a query. Verify once, at sprint start.
- **No disbursement before KYC approval — no exceptions.** Check a delayed tranche against KYC status *before* escalating it as a programme issue.
- KYC (08-19) and approval (08-20) both predate Day 1 (09-07): retention only, no re-submission.

## 2. Payout wallet

| Item | Value |
| --- | --- |
| Payout wallet address / method | `<Dan to fill>` |
| Recorded outside the Airtable form? | `<Dan to confirm — y/n>` |
| Still controlled by payee? | `<Dan to confirm — y/n + date>` |

- The address in the Airtable form is where every tranche lands and what any reconciliation runs against. **Never invent an address.**
- Record it somewhere retrievable **outside** the submitted form.
- **Sprint work is testnet-only** (SOW §3.6). The **payout wallet is a separate, real-value account, distinct from any testnet signing key** used for build/QA evidence — do not conflate them.

## 3. Tranche record

Payout is released in **weekly tranches**, each gated on that week's Friday
evidence bundle (story 7.01). **If a week produces no verifiable output, that
week's tranche waits.** Archive confirmations *as received* — date, amount, tx reference.

| Week | Milestone (due) | Evidence bundle | Submitted | Confirmed (y/n) | Tranche status | Amount |
| --- | --- | --- | --- | --- | --- | --- |
| W1 | M1 · Permissionless Registration (2026-09-11) | `<link — 7.01 W1 bundle>` | | | Pending | |
| W2 | M2 (2026-09-18) | `<link>` | | | Pending | |
| W3 | M3 (2026-09-25) | `<link>` | | | Pending | |
| W4 | M4 (2026-10-02) | `<link>` | | | Pending | |
| Close | M5 · Sprint close (2026-10-06) | `<link>` | | | Pending | |

- **Program Contact / confirmation source:** Armielyn Obinguar. The submission channel is being confirmed under **decision D-005** — record the actual channel here once it lands.
- **Tranche sizing:** the deck states no award dollar value, so amounts reconcile against our own billing — **SOW v4 §4.2 / Appendix A.4** (the financial source of truth). Envelope: **$4,800 / 160 hrs @ $30/hr**, build + test only; hard per-award cap **$5,000**.
- Keep the raw tx hash for each confirmation (a column here, or inside the linked bundle).

## 4. Retention policy

- **Where:** this document, cross-linked from the evidence index (story **5.05**); each weekly bundle lives with its 7.01 entry.
- **What:** the Friday evidence bundle, on-chain tx hashes, and each tranche/submission confirmation (date + amount + tx reference).
- **Wallet history:** export the payout wallet transaction history at **close (2026-10-06)**, covering the full 30-day period, retained with the confirmations.
- **How long:** through the sprint and its review — do not prune until the programme review is closed.
- **Tax — out of scope.** Funds are paid to the recipient, who files their own taxes; the programme cannot advise on tax and no tax question is routed to the Program Contact.

## 5. Close checklist (what 7.08 requires)

- [ ] TIN name confirmed to match the payee name — check + date recorded (§1).
- [ ] KYC date (08-19), approval date (08-20) and the payout wallet on file all stated and retrievable here.
- [ ] Payout wallet recorded outside the Airtable form and confirmed still controlled.
- [ ] Every tranche confirmation archived on receipt with date, amount, tx reference (§3).
- [ ] Each tranche reconciled against SOW v4 §4.2 / Appendix A.4; discrepancies raised at the next check-in.
- [ ] Payout wallet transaction history exported at close, covering the full period.
