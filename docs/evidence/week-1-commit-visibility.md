# Week-1 commit visibility — public cadence & multi-contributor proof (BLO-106 / story 7.04)

**SDF Instawards rule:** every approved proposal member must have at least one
**visible public commit every week**, relevant to their assigned role.

**Proposal members (SOW §1):**
- Danielle Bagaforo Meer ("Dan") — git author `algorexph@gmail.com` (GitHub merge identity: `Danielle Meer <55391597+ALGOREX-PH@users.noreply.github.com>`)
- Rieselle Saure ("Rie", PM + QA) — GitHub identity `rie-hash14` (`276933516+rie-hash14@users.noreply.github.com`)

**Week-1 window:** Mon 2026-09-07 → Fri 2026-09-11 (commits allowed through Sat 2026-09-12).
**Audit run 2026-09-12**, after `git fetch origin`, over `git log --all`.

## Correction note (important)

The first pass of this audit (same day) covered only the two application repos
(`Orizon-Agents-FE-Stellar`, `Orizon-Agents-BE-Stellar`) and reported Rie at
**0 commits / NON-COMPLIANT**. That was **incomplete**: Rie's QA/UAT work lives in
a **third public repo**, [`Bl0cksmiths/Orizon-Agents-UAT-Stellar`](https://github.com/Bl0cksmiths/Orizon-Agents-UAT-Stellar),
created 2026-09-08, which the first pass did not know about. With that repo
included, the verdict is **COMPLIANT** — see below. This note is kept rather than
erased so the correction trail is visible.

## Per-author commits this week

### BE — orizon-agents-BE-Stellar
| Author | Email | Commits |
|--------|-------|---------|
| Danielle Bagaforo Meer | algorexph@gmail.com | 82 |
| Danielle Meer (GitHub merge identity = Dan) | 55391597+ALGOREX-PH@users.noreply.github.com | 5 (merges) |
| dependabot[bot] (automation) | 49699333+dependabot[bot]@users.noreply.github.com | 4 |

### FE — orizon-agents-FE-Stellar
| Author | Email | Commits |
|--------|-------|---------|
| Danielle Bagaforo Meer | algorexph@gmail.com | 48 |
| Danielle Meer (GitHub merge identity = Dan) | 55391597+ALGOREX-PH@users.noreply.github.com | 7 (merges) |
| dependabot[bot] (automation) | 49699333+dependabot[bot]@users.noreply.github.com | 1 |

### UAT — Orizon-Agents-UAT-Stellar (Rie's QA/UAT deliverable)
| Author | Email | Commits | Dates |
|--------|-------|---------|-------|
| Rieselle Saure (`rie-hash14`) | 276933516+rie-hash14@users.noreply.github.com | **99** | 96 on 2026-09-10, 3 on 2026-09-12 |
| Danielle Meer (merge) | 55391597+ALGOREX-PH@users.noreply.github.com | 1 (PR #1 merge) |

The commits are real and role-relevant — an end-to-end Playwright UAT suite run
against the live deployment plus the UAT doc set (test plan, runbook,
traceability, defects, sign-off report, wallet/browser matrix). Spot-check: tip
commit `6d370ea` = +22 lines to `docs/uat/test-plan.md`. This is exactly Rie's
assigned PM+QA role (Epic 6).

## Verdict — ✅ COMPLIANT for Week 1

- **Dan — MET.** 130 authored commits this week (82 BE + 48 FE) on public branches, plus 12 web-merge commits.
- **Rie — MET.** 99 authored commits in the public UAT repo, under her own identity (`rie-hash14`), dated within the Week-1 window, relevant to her QA role.

Both approved members show visible, public, role-relevant commits in Week 1.

## Caveats to close for a fully clean programme review

The rule is satisfied, but two items would make Rie's contribution
unambiguous to a reviewer working from the submission:

1. **Cite the UAT repo in the evidence.** The story scoped three repos
   (FE, BE, Smart-Contract); the UAT repo is a fourth. Add it to the Week-1
   evidence bundle (7.01) and the standing evidence index (5.05) so the
   programme actually sees Rie's commits — an uncited public repo is invisible
   to the review even though it exists.
2. **Add an MIT LICENSE to the UAT repo.** The deck stresses *public MIT
   repositories*; the UAT repo is public but currently carries no LICENSE.
   Match the other repos (trivial, one commit — ideally authored by Rie).

Neither blocks the weekly-visibility rule; both are cheap and worth doing before
the Friday bundle.

## What does not count (unchanged)

A `Co-authored-by:` trailer or a commit authored by Dan on Rie's behalf does not
satisfy the rule — the commit **author** must be the member. The 99 UAT commits
clear this: they are authored by `rie-hash14`, not co-authored. No fabricated or
backdated commits; no invented evidence data.
