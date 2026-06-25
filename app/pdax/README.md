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

## Verify

```
python3 scripts/pdax_smoke.py   # offline: config, totp, models, routes
```
