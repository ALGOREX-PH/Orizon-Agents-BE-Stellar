# Week 1 evidence — D1 · Permissionless Agent Registration (backend findings)

## First external-wallet registration — evidence tooling (story 1.07 / BLO-17, 2026-09-08)

The **Milestone 1 exit gate**. Its core artifact — an agent registered by a wallet
Blocksmiths do not control, done unaided on the public testnet page — is
inherently human/dashboard-gated: it needs the **public testnet surface** (story
1.11) and a **real chapter contributor**. Neither can be faked (a self-run or a
talked-through run is not a pass). What was built is the state-of-the-art rigor
that turns a manual eyeball into a **machine-verifiable** gate and captures the
artifacts at the moment of the run.

**Evidence capture (FE):** the register success card is now a complete evidence
bundle — the owner renders as a stellar.expert **account** link (so a reviewer
can confirm "that wallet as source", AC1), alongside the tx hash + explorer link
(`TxStatus`), and a one-click **Copy evidence** yields a structured block (agent
id, owner, tx hash, both stellar.expert links, network, timestamp) in the exact
shape the 5.05 index expects. Builder `lib/registration-evidence.ts` (unit-tested).

**Machine verification (BE):** `app/evidence.py` (pure, typed, 10 unit tests) +
the CLI `scripts/verify_registration.py` check a registration against **Horizon**
(tx exists, succeeded, source = the wallet — AC1) and, with `--api-base`, the
**marketplace API** (`/api/agents` shows the id `source:onchain` owned by that
wallet, distinct from the 12 seeded — AC2). **Proven live** against the real 1.05
registration:

```
$ python scripts/verify_registration.py --tx 416bea4f… --agent sign_probe_bb5c12 \
    --owner GBI2I3WL…ADBH
  [PASS] tx_on_horizon · [PASS] tx_succeeded · [PASS] tx_has_source · [PASS] source_matches
  VERDICT: PASS - registration verified   (exit 0)
```

**Run kit (docs):** `docs/evidence/1.07-runbook.md` (the unaided contributor
procedure), `1.07-friction-log.md` (the required AC3 friction template, filled
during the run — or an explicit none-statement), and `1.07-evidence-index.md`
(the 5.05 index: the real 1.05 row as a format reference, flagged as a
developer-run that does **not** satisfy D1, plus a blank row for the real run).

**AC status:** the *tooling* for AC1/AC2 is built + proven, AC4's non-technical
path (open the stellar.expert link) is served by the success card, and AC3's
template is ready. The three ACs' **evidence rows stay blank** until 1.11 is live
and a chapter contributor runs it — that is the remaining, non-fakeable work.

## Operator agent management — change price, delist / relist (story 1.08 / BLO-44, 2026-09-08)

An operator who registered at the wrong price was stuck with it forever
(`register` rejects a duplicate id), and story 1.02's "a delisted agent stops
being routable" had no way to delist. The contract already exposed
`update_price(id, new_price)` and `set_active(id, active)` (both
`owner.require_auth()`); nothing reached them. Closed on both halves:

**Backend** — two build endpoints mirroring `build_register_agent`:
- `POST /api/stellar/build/update-price` → args `[sym(id), i128(usdc_to_i128(price))]`.
- `POST /api/stellar/build/set-active` → args `[sym(id), to_bool(active)]`.
Both: same charset + price validation at the router edge, `owner_account_unfunded`
decoded from the build, and a **cached existence preflight** (reuses read_agent's
`agent:{id}` key so it adds no new amplification — story 1.09) that returns a plain
**404 `agent_not_found`** for an unregistered id instead of an opaque build error.
`/submit` is reused unchanged. Ownership is the contract's `require_auth`, not
re-checked server-side. 8 tests in `tests/test_agent_management.py`.

**Frontend** — the registration signing flow was **extracted** into a shared,
tested `lib/sign-submit.ts` (`signAndSubmit`: sign → submit → interpret, with a
discriminated outcome and injectable `submit`/`interpret`), and **both** the
register page and the new management surface run through it — so error handling
cannot drift into a second, subtly different path (the card's explicit rule). An
**owner-gated** `ManagePanel` on the agents page (shown only when
`wallet.connected && agent.owner === wallet.address`) offers **Change price**
(current → new + stroops, register-matching validation) and **Delist / Relist**
with accurate confirmations: a price change applies to future plans only (an
existing authorization charges the price it was signed against); delisting is
reversible, never a delete, leaves in-flight authorized work untouched, and
retains reputation + history. A successful change refreshes the listing
immediately (`syncAgents()` + a re-fetch).

**Reuse of the proven chain:** the build → sign → submit → land sequence itself
was demonstrated live on testnet under story 1.05; 1.08 routes through the same
`signAndSubmit`, so "the transaction lands" is inherited-proven. A dedicated live
price-change tx belongs on the testnet evidence surface (1.11), alongside 1.05's.

**Gates (2026-09-08):** BE ruff / format / mypy-strict clean, pytest green,
coverage 87.37 %. FE typecheck / lint / prettier clean, **470 vitest tests**,
coverage thresholds met, production build clean (`/app/agents` 5.04 kB).

## Abuse bounds on the public registration endpoints (story 1.09 / BLO-45, 2026-09-08)

A **measure-first** story. The finding below is the deliverable; the only code
change it justified is caching the availability read.

### AC1 — existing coverage, measured

`RateLimitMiddleware` (`app/security.py:409`, wired `app/main.py:184`) is a
60-second sliding-window limiter over **every** non-exempt route. Exempt set is
only `{"/", "/health", "/readiness", "/api/health"}` + `OPTIONS`
(`security.py:50,445-449`), so all four registration routes are covered:

| Route | Covered | Body cap |
|-------|---------|----------|
| `POST /api/stellar/build/register-agent` | yes | 1 MiB → 413 |
| `POST /api/stellar/submit` | yes | 1 MiB → 413 (+ `signed_xdr` ≤ 32 KiB → 422) |
| `GET /api/stellar/agent-id-available/{id}` | yes | n/a (GET) |
| `POST /api/stellar/agents/sync` | yes | 1 MiB → 413 |

- **Rate:** `rate_limit_per_minute` (default **1200/min**, `config.py:83`).
- **Scope:** decided by `TRUSTED_PROXY_HOPS` (default `0`). At the default,
  `client_key()` resolves the edge-written entry — the same value for every
  visitor — so 1200/min is **one budget for the whole service**, sized as a
  flood cut, not a per-visitor quota. With hops set correctly it is per-client.
- **429 envelope** (`security.py:470-495`) — the exact app envelope, so a client
  parses it like any other error:
  ```json
  {"detail": "rate_limited",
   "error": {"code": "rate_limited", "message": "too many requests", "request_id": "<id>"}}
  ```
  plus `Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining` headers.
- **Body limit:** `BodyLimitMiddleware` bounds every request body at 1 MiB → 413
  (`security.py:316`), a second volume bound below the rate limit.

**Sufficiency:** the limiter and body cap already cover all four routes. The
only route that turned one cheap request into unbounded upstream work was the
availability check — fixed below. **No second limiter was added** (product rule).

### AC2 — RPC amplification, measured and bounded

The availability endpoint (`stellar.py:194`) called `sc.simulate_read`
**directly, bypassing `rcache.get_or_set`** — unlike its sibling `read_agent`
(line 155) — so every id-field blur was one uncached Soroban read, and it is the
cheapest route to script (a bare GET over rotating ids).

**Fix:** the read now runs through `get_or_set` under an `agentavail:{id}` key
with a producer that catches the read error and returns `available=True` (never
raises), so **both** outcomes (taken and free) are positively cached and
single-flighted. Repeated blur checks of the same id, and any concurrent burst,
collapse to **one** Soroban read within the 3 s window. Reuses the existing
cache; no parallel mechanism. Pinned by `tests/test_availability_cache.py`
(4 tests: available-collapse, taken-collapse, concurrent single-flight, and the
malformed/reserved short-circuits that never touch the chain).

**Wider amplification measured (deliberately not built):** two other unauth
routes also do uncached upstream work — `agents/sync` does `1 + N` reads and
`build/register-agent` does a preflight read + a two-round-trip
`build_invoke_xdr`. Both were left as-is, by reasoned decision, not omission:

- `agents/sync` holds an `asyncio.Lock` that **serializes** on-demand callers,
  which caps its RPC concurrency at one pass at a time (self-throttling) **and**
  gives the post-registration fast path a freshness guarantee (each trigger
  gets a pass that starts after it). Coalescing would bound the wasted work but
  break that freshness guarantee — a bad trade — and trigger volume is already
  bounded by the global limiter, with the 15 s periodic loop as the backstop.
- `build/register-agent`'s dominant cost is `build_invoke_xdr` (needs a live
  account sequence number), which is **inherently uncacheable**; it is a POST
  (harder to script than a GET) and bounded by the limiter.

Caching the one cheap-to-script GET, and bounding the rest by the existing
limiter, is the measured-sufficient answer.

### AC3 — typing does not fire per keystroke (satisfied, no change)

The FE availability check fires on the id input's `onBlur` (settle);
`onChange` only mutates React state and resets the prior result — zero requests
while typing, one on settle (`app/app/register/page.tsx`, FE repo). `useAsyncAction`
is race-/unmount-safe, so a stale in-flight check cannot overwrite a newer one.

### AC4 — a rate-limited operator recovers (satisfied + improved)

The 429 envelope + `Retry-After` are already correct (AC1). Form values live in
React `useState`, so no error path clears them. Improvement: the register submit
path now surfaces a specific, retryable message naming the wait and reassuring
that nothing was lost (`lib/rate-limit-message.ts`, `rateLimitMessage`, unit-tested),
instead of the generic "please try again".

### AC5 — registration is not gated (confirmed)

No registration route imposes a fee, allowlist, approval step, account, or API
key. `require_api_key` appears on **exactly two** routes, both server-signed
money paths (`POST /server/charge`, `POST /server/seal`) — never on
register/build/availability/sync/submit. The `agt_`-reserved and id-taken checks
gate **which id**, not **who** may register; the owner G-address is
caller-supplied and validated only for format. Only request *volume* is bounded.
