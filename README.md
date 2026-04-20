# Orizon Agents — Backend

FastAPI + Agno + OpenAI. The brain behind the Orizon Agents frontend.

## Repositories

| layer | repo |
| --- | --- |
| Backend (this repo) | https://github.com/ALGOREX-PH/Orizon-Agents-BE-Stellar |
| Frontend — Next.js | https://github.com/ALGOREX-PH/Orizon-Agents-FE-Stellar |
| Smart Contracts — Soroban / Rust | https://github.com/ALGOREX-PH/Orizon-Agents-Smart-Contract-Stellar |

## Setup

```bash
# install uv (once) — https://docs.astral.sh/uv/
curl -LsSf https://astral.sh/uv/install.sh | sh

# create venv + install deps
uv venv .venv
uv pip install -r requirements.txt

# configure
cp .env.example .env
# edit .env: set OPENAI_API_KEY

# run
./run.sh
# → http://localhost:8000  (docs at /docs)
```

## Endpoints

| method | path | purpose |
| --- | --- | --- |
| GET  | `/api/agents`                        | registry listing |
| GET  | `/api/agents/{id}`                   | agent detail |
| POST | `/api/orchestrator/decompose`        | intent → plan (real LLM) |
| POST | `/api/orchestrator/execute`          | run a plan → `{task_id}` |
| GET  | `/api/tasks`                         | recent tasks |
| GET  | `/api/tasks/{id}`                    | task detail |
| GET  | `/api/trace/{task_id}`               | full trace snapshot |
| GET  | `/api/trace/{task_id}/stream`        | SSE live trace |
| GET  | `/api/metrics/overview`              | dashboard overview |
| GET  | `/api/flow/default`                  | default DAG |
| POST | `/api/payments/x402`                 | simulated HTTP 402 flow |

## Deploy — Render (recommended)

The repo ships a `render.yaml` blueprint + a `runtime.txt` pinning Python 3.12. Render reads them on first connect.

1. Push to GitHub:
   ```bash
   git add render.yaml runtime.txt app/main.py README.md
   git commit -m "chore: render deploy"
   git push origin main
   ```
2. Go to [render.com](https://render.com) → **New → Blueprint** → connect `Orizon-Agents-BE-Stellar`.
3. Render detects `render.yaml` and lists two secrets you must fill (`sync: false`):

   | name | value |
   | --- | --- |
   | `OPENAI_API_KEY` | your OpenAI key (secret) |
   | `STELLAR_SIGNING_KEY` | your admin `S…` secret — optional, needed only for real on-chain charge/seal |

   All other env vars (model IDs, contract addresses, RPC) are preset in `render.yaml`.

4. Click **Apply**. First build takes ~2–3 minutes. You'll get `https://orizon-agents-be-xxxx.onrender.com`.
5. After the frontend is deployed on Vercel, update `CORS_ORIGINS` in the Render dashboard to your Vercel URL. Render redeploys automatically (~30 s).
6. (Optional) Register the on-chain `orizon_batch` agent so the Authorize & Execute flow can settle:
   ```bash
   cd ~/Websites-Services-2026/orizon-agents-BE-Stellar
   .venv/bin/python scripts/register_batch_agent.py
   ```
   One-time tx; runs against whichever contract addresses are in your `.env`.

### Gotchas

- **Free-tier sleep**: Render's free plan sleeps after 15 min idle. First request after idle takes ~30–50 s. Upgrade to Starter ($7/mo) for always-on.
- **SSE**: trace streams work fine for Orizon's ~4 s workflows. For long-lived streams (> 5 min), Render's free-plan buffer can cut them — move to paid or hit the backend directly.
- **Never commit** `OPENAI_API_KEY` or `STELLAR_SIGNING_KEY`. They live only in Render's dashboard; `.env` stays gitignored.

## Notes

- Storage is in-memory. State resets on restart.
- 4 real Agno workers (`copywrite.v3`, `seo.brief`, `research.pro`, `sol-audit`) + `code.gen`; the remaining workers are mocks.
- Payments and ERC-8004 proofs are simulated unless `STELLAR_SIGNING_KEY` is set — then they become real testnet transactions.
