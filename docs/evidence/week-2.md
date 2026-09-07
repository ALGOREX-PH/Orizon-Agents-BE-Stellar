# Week 2 evidence — D2 · Reputation-Gated Routing

## Reputation floor applied on the demo-kit path (story 3.01 / BLO-23, 2026-09-08)

**The defect:** `orchestrator_svc._build_kit_plan` walked the six hardcoded
`_KIT_PIPELINE` agents and stamped reputation onto every step, but never called
`passes_floor`. Curated demo intents (tetris / calculator / snake / pomodoro) —
the most-watched path in the product, and exactly what the D2 demo records —
advertised a trust gate they did not enforce. The free-form path
(`_registry_prompt_fragment`) filtered correctly; the kit path was the
split-brain.

**The fix (one floor, one policy, every path):**

- `passes_floor(reps.get(id))` is now applied to every kit-pipeline agent.
- A sub-floor step is filled by a deterministically-chosen, floor-clearing,
  worker-backed agent drawn from OUTSIDE the kit pipeline that shares ≥1 skill
  (highest smoothed score, id breaking ties); if none exists, the step is
  dropped. Never a silent reshuffle.
- Every action is surfaced: `DecomposeResponse.notices: list[PlanFloorNotice]`
  records each `excluded` / `substituted` / `degraded` action with a reason that
  names the deciding bps; `PlanStep.substituted_for` and `PlanStep.degraded`
  badge the step inline (story 3.02 renders these).
- The existing `_MIN_ROUTABLE_AGENTS = 3` backstop is reused: if the floor
  would leave fewer than three steps, the top-scored dropped kit agents are
  re-admitted (flagged `degraded`) so the buyer still gets a workable plan. No
  second starvation rule was invented.
- The path stays LLM-free and deterministic — a pure function of `(intent,
  reps)`.

**Acceptance criteria — all proven by `tests/test_kit_floor.py` (6 tests):**

| AC | Test | Result |
|----|------|--------|
| Sub-floor agent excluded from a kit plan | `test_sub_floor_agent_is_excluded_from_kit_plan` | PASS |
| Kit plan stays deterministic, no LLM | `test_kit_plan_is_deterministic`, `test_kit_path_applies_floor_without_calling_the_llm` | PASS |
| Substitution surfaced, never silent | `test_sub_floor_agent_is_substituted_and_surfaced` | PASS |
| Floor cannot starve the plan | `test_starvation_backstop_keeps_kit_plan_workable` | PASS |
| Regression test pins the behaviour | the exclusion test above (fails if the floor is ever removed) | PASS |
| (defensive) unseeded kit id is skipped, not crashed | `test_kit_step_for_unseeded_agent_is_skipped_not_crashed` | PASS |

**Gates (2026-09-08):** ruff clean · ruff format clean · mypy-strict clean
(87 files) · pytest 536 passed · total coverage 87.19 % (floor 82 %) ·
`app/services/orchestrator_svc.py` at **100 %** (122/122 statements).

**Independent audit:** a read-only adversarial pass re-derived all five ACs
against the committed code (CONFIRMED) and cleared five logic-hole probes —
determinism of step/notice order and substitute pick, double-booking, the
kit-id exclusion, sort tie-breaks, and steps/notices consistency
(all CONFIRMED-SAFE).
