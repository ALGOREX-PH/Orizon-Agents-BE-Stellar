# Orizon Agents — Backend

FastAPI + Agno + OpenAI `gpt-4o-mini`. The brain behind the Orizon Agents frontend.

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

## Notes

- Storage is in-memory. State resets on restart.
- 4 real Agno workers (`copywrite.v3`, `seo.brief`, `research.pro`, `sol-audit`); the remaining 6 are mocks.
- Payments and ERC-8004 proofs are simulated.
