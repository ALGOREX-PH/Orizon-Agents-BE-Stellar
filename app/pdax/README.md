# PDAX integration

A typed async wrapper around the [PDAX institutions API](https://services.pdax.ph)
for PHP ↔ crypto on/off-ramp. Mirrors the `app/stellar/` style: a transport
client with a token manager, Pydantic models per domain, and thin domain
modules. For Orizon the relevant asset is **USDCXLM** (USDC on Stellar).

## Layout

| File | Purpose |
| --- | --- |
| `config.py` | Resolve base URL from `PDAX_ENVIRONMENT` (production/stage/uat) |
| `errors.py` | `PdaxError` + documented error-code table |
| `totp.py` | Stdlib RFC 6238 TOTP for SOFTWARE_TOKEN_MFA |
| `auth.py` | `PdaxAuth` — login / OTP / refresh with token caching |
| `client.py` | `PdaxClient` — httpx transport, header injection, error mapping |
| `constants/` | Accepted countries, bank codes, tokens, enumerated values |
| `models/` | Request/response models grouped by domain |
| `trade.py` `funding.py` `withdrawals.py` `transactions.py` `balances.py` `webhooks.py` | Domain endpoint functions |

The router lives at `app/routers/pdax.py` and is mounted under `/api/pdax`.

## Auth

The backend authenticates with its own PDAX credentials and caches the 10-minute
access/id tokens, refreshing via the 30-day refresh token. The frontend never
sees tokens. If the account has MFA, set `PDAX_OTP_SECRET` (base32 seed) and the
challenge is answered automatically.

## Config

```
PDAX_ENVIRONMENT=uat            # production | stage | uat
PDAX_USERNAME=...               # account email (host secret in prod)
PDAX_PASSWORD=...               # host secret in prod
PDAX_OTP_SECRET=                # base32 TOTP seed, only if MFA is enabled
PDAX_WEBHOOK_SECRET=            # optional inbound webhook HMAC secret
```

Staging/UAT require your static egress IP to be whitelisted by PDAX first.

## Ramp orchestration (PHP ↔ USDCXLM)

`ramp.py` composes the primitives into two user-facing flows, tracked as
`RampRecord`s (`ramp_store.py`) and exposed under `/api/pdax/ramp/*`:

- **On-ramp (PHP → USDCXLM)** — `start_onramp` creates a fiat deposit and
  returns a `payment_checkout_url`. A non-web3 buyer pays via bank/e-wallet
  (InstaPay QRPh, Maya, GrabPay, UnionBank). When the `DEPOSIT COMPLETED`
  webhook lands, `advance_onramp` buys USDC and withdraws USDCXLM to the
  buyer's Stellar address — which can then fund agent work via x402.
- **Off-ramp (USDCXLM → PHP)** — `start_offramp` returns a USDCXLM deposit
  address. The agent sends USDC there; the `DEPOSIT completed` webhook triggers
  `advance_offramp`, which sells USDC and pays PHP to a bank account.

`handle_event` is the webhook dispatcher that matches an event to a waiting
ramp (on-ramp by `identifier`, off-ramp by deposit address) and advances it.

## Production hardening

- **Resilience** (`resilience.py`) — the transport rate-limits with an async
  token bucket and retries transient failures (network, 429/5xx, PDAX
  `OT010032`) using exponential backoff with full jitter. 4xx validation errors
  are never retried. Tunable via `PDAX_MAX_RETRIES` / `PDAX_RATE_LIMIT_*`.
- **Observability** (`observability.py`) — every call logs method, path,
  status, latency, and attempt number under the `orizon.pdax` logger.
- **Fail-fast validation** (`validation.py`) — fiat deposit/withdraw payloads
  are checked against the accepted-value tables (country, bank, method, source
  of funds, purpose, relationship, fee type, sex) and the ≥ 50,000 PHP travel
  rule *before* the network call, turning a slow 400 into an instant error.
- **Decimal money** (`money.py`) — outbound amounts are normalized through
  `Decimal` so float noise (`17.179999999999998`) never trips step validation.
- **Idempotency** — webhook deliveries are deduped (`webhooks.claim_event`) and
  ramp settlement runs under a per-ramp lock with a status re-check, so a
  retried or racing event can never double-buy or double-withdraw.
- **Health** — `GET /api/pdax/health` probes the auth handshake and reports
  `ok` / `degraded` / `unconfigured` without exposing secrets.

## Verify

```
python3 scripts/pdax_smoke.py            # offline: config, totp, models, routes
python3 scripts/pdax_ramp_smoke.py       # offline: on-ramp + off-ramp sequencing
python3 scripts/pdax_hardening_smoke.py  # offline: retry, rate-limit, validation,
                                         #          money, dedupe, idempotency
```
