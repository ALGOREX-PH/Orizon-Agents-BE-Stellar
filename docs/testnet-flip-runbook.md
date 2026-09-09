# Runbook — flip orizons.xyz to TESTNET (and back)

**Goal:** run the public production site **orizons.xyz** on **testnet** for the
Blue Belt sprint (the whole sprint is testnet-only, SOW §3.6), then flip back to
mainnet when the sprint's testnet window closes. This unblocks story 1.07 (the
external-wallet registration lands on the real public URL) and **supersedes the
separate testnet surface** of story 1.11 — orizons.xyz *is* the testnet surface.

**Who does what.** The live network lives in the **dashboards** (Render env
overrides `render.yaml`; Vercel `NEXT_PUBLIC_*` are inlined at build time), so
the flip is a dashboard operation only the account owner can do. The repo change
is one line in a workflow file. `render.yaml` is deliberately **not** flipped —
it stays the mainnet target so a routine `Update-2 → main` merge can never
surprise-flip the live BE; the dashboard is authoritative during the sprint.

> **Order matters.** Flip the **BE (Render)** first and verify it, then the
> **FE (Vercel)**, then land the smoke-workflow change on `main`. Doing the FE
> first would point a testnet UI at a mainnet API.

---

## 1. Backend — Render dashboard (the orizons.xyz API service)

Set these env vars on the existing production BE service (they override
`render.yaml`). Values are the deployed **testnet** contracts (same as
`.env.example`):

```
STELLAR_NETWORK=testnet
STELLAR_RPC_URL=https://soroban-testnet.stellar.org
STELLAR_NETWORK_PASSPHRASE=Test SDF Network ; September 2015
STELLAR_AGENT_REGISTRY=CAPHXWU53UZUZJGV7IAE57NNMH3YYB5MTWO6YA53KKMXSFVLOITBJ3GQ
STELLAR_REPUTATION_LEDGER=CDCSOBEVZUPQZV5GV4D6KYHZCLNGW2KXY74RUHSZ3EZUXF34DPW422ZT
STELLAR_PAYMENT_ESCROW=CBJPTMAPMGODGZCZ2IMEQSRUX3WGUXNMKDTNN2KMJ3NFGYZ5OJ5525PI
STELLAR_ATTESTATION_REGISTRY=CBYUZKOET43UXTBXZUJIBBJW5ODGD2J2AZVVXCR3QONGOCAHOXQQHEGK
STELLAR_ASSET_SAC=CDLZFC3SYJYDZT7K67VZ75HPJVIEUVNIXF47ZG2FB2RMQQVU2HHGCYSC
STELLAR_ADMIN_ADDRESS=GA7AI5TAJEZA27I666DSJC4MUJYBEWUYNNZWPU7R2ONA7IZQVO6R5OQV   # unchanged
```

**⚠ Signing key — the one that matters.** Replace `STELLAR_SIGNING_KEY` with a
**fresh testnet key funded via friendbot** — never leave the mainnet key on a
testnet service:
- The mainnet key controls real funds; it must not sit on the testnet site, and
  a mainnet key against testnet config would fail at signing anyway.
- Registration itself is **client-signed** (the contributor's wallet), so 1.07
  works even with an empty key. The server key is only used for the
  settlement path (`charge` / `seal` / ratings); set a funded testnet key to
  exercise the full execute→settle flow.
- Generate one in the [Stellar Lab](https://lab.stellar.org) and fund it via
  friendbot; paste the **S…** secret into `STELLAR_SIGNING_KEY`.

**PDAX (optional).** The testnet site does not need the fiat ramp. You may blank
`PDAX_USERNAME/PASSWORD/OTP_SECRET/WEBHOOK_SECRET`. Keep `API_KEY` set regardless
(the deep-health guard uses it; and the config validator requires it while any
money-capable credential is present).

Save → Render redeploys. **Verify before touching the FE:**

```
curl -s https://orizons.xyz/api/stellar/network | jq '.network, .network_passphrase, .contracts.agent_registry'
# expect: "testnet", "Test SDF Network ; September 2015", "CAPHXWU5…"
```

---

## 2. Frontend — Vercel dashboard (the orizons.xyz site)

The FE **code already defaults to testnet** (`lib/env.ts`); it is mainnet only
because the Vercel Production env pins it. Flip it by removing the mainnet pins
so the testnet defaults apply:

1. In the Production environment, **delete** (or set to the testnet values):
   - `NEXT_PUBLIC_STELLAR_NETWORK_PASSPHRASE`  → delete (default `Test SDF Network ; September 2015`)
   - `NEXT_PUBLIC_HORIZON_URL`                 → delete (default `https://horizon-testnet.stellar.org`)
   - `NEXT_PUBLIC_SOROBAN_RPC_URL`             → delete (default `https://soroban-testnet.stellar.org`)
2. Ensure `NEXT_PUBLIC_API_BASE` (and any rewrite/proxy target) points at the
   orizons.xyz BE that you just flipped — no change if it already does.
3. **Redeploy** (env vars are inlined at build; a redeploy is required).

`lib/env.ts` has build guards: a half-flip (mainnet passphrase + testnet
endpoints, or vice-versa) **fails `next build`** rather than shipping a
wrong-chain site — so a clean testnet set (or a clean delete) is the only thing
that will build.

---

## 3. Repo — the smoke workflow (needs the `workflow` token scope)

The 6-hourly smoke check asserts the live network. Change it to testnet so it
matches the flipped site, in `.github/workflows/smoke.yml` (FE repo):

```diff
-          SMOKE_EXPECT_NETWORK: mainnet
+          SMOKE_EXPECT_NETWORK: testnet
```

Editing a workflow file needs a `workflow`-scoped token. Either:
- `gh auth refresh -s workflow` then commit + push, **or**
- edit it directly in the GitHub web UI.

Land it on `main` at the same time as the flip (the scheduled smoke runs from
`main`) so a run never expects mainnet against a testnet site.

---

## 4. Verify the flip

```
# network identity
curl -s https://orizons.xyz/api/stellar/network | jq '.network'           # "testnet"
# marketplace up, seeded catalog present
curl -s https://orizons.xyz/api/agents | jq 'length'                       # >= 12
# full deployed smoke (from the FE repo)
SMOKE_ORIGIN=https://orizons.xyz SMOKE_EXPECT_NETWORK=testnet node scripts/smoke-deploy.mjs
```

Then run the 1.07 gate: register an agent through orizons.xyz/app/register with
an external wallet and verify it —

```
python scripts/verify_registration.py --tx <hash> --agent <id> --api-base https://orizons.xyz
```

---

## 5. Flip back to mainnet (end of the testnet window)

1. **Render:** restore the mainnet Stellar block (the values in `render.yaml`
   lines 49–66) and restore the **mainnet** `STELLAR_SIGNING_KEY`. Re-enable PDAX
   if it was blanked.
2. **Vercel:** restore the mainnet `NEXT_PUBLIC_STELLAR_NETWORK_PASSPHRASE`
   (`Public Global Stellar Network ; September 2015`), `NEXT_PUBLIC_HORIZON_URL`
   (`https://horizon.stellar.org`), `NEXT_PUBLIC_SOROBAN_RPC_URL`
   (`https://mainnet.sorobanrpc.com`) and redeploy.
3. **Repo:** set `SMOKE_EXPECT_NETWORK` back to `mainnet`.

Because `render.yaml` was never flipped, its committed values already describe
the mainnet target — flip-back is restoring the dashboard to match it.
