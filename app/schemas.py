from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# ───── Registry ────────────────────────────────────────────
AgentStatus = Literal["online", "idle", "offline"]


class Agent(BaseModel):
    id: str
    name: str
    skills: list[str]
    price: float
    rep: float
    status: AgentStatus
    runs: int
    real: bool = False  # whether backed by a real Agno Agent


# ───── Tasks ───────────────────────────────────────────────
TaskStatus = Literal["pending", "running", "complete", "failed"]


class Task(BaseModel):
    id: str
    intent: str
    agents: int
    spent: float
    status: TaskStatus
    started: str  # human-readable ("2m ago")
    artifact: dict | None = None
    charge_tx: str | None = None
    proof_tx: str | None = None


# ───── Artifacts ──────────────────────────────────────────
class ArtifactFile(BaseModel):
    path: str
    language: str
    content: str


class CodeArtifact(BaseModel):
    title: str
    summary: str
    files: list[ArtifactFile]
    entry: str
    preview_html: str


# ───── Plans ───────────────────────────────────────────────
class PlanStep(BaseModel):
    agent_id: str = Field(..., description="Must match a registered agent id")
    agent_name: str | None = None  # backfilled server-side
    rationale: str = Field(..., description="<= 20 words")
    est_price_usdc: float = Field(..., ge=0)
    est_eta_seconds: float = Field(..., ge=0)
    rep_bps: int | None = None  # smoothed reputation at plan time (0..10_000)
    rep_source: Literal["onchain", "prior"] | None = None


class Plan(BaseModel):
    steps: list[PlanStep]


class StoredPlan(BaseModel):
    id: str
    intent: str
    plan: Plan
    total_usdc: float
    total_eta: float


# ───── Trace ───────────────────────────────────────────────
TraceLevel = Literal["input", "exec", "proof", "cost", "out", "error", "artifact"]


class TraceLine(BaseModel):
    t: str
    level: TraceLevel
    msg: str


# ───── Flow ────────────────────────────────────────────────
class FlowNode(BaseModel):
    id: str
    label: str
    sub: str
    x: float
    y: float


class Flow(BaseModel):
    nodes: list[FlowNode]
    edges: list[tuple[str, str]]


# ───── Metrics ─────────────────────────────────────────────
class OverviewMetrics(BaseModel):
    agents_online: int
    tasks_per_sec: float
    avg_completion: float  # 0..1
    avg_trust: float  # 0..5
    throughput: list[int]  # sparkline
    skills: list[dict[str, Any]]  # [{name, pct, tone}]


# ───── Requests ────────────────────────────────────────────
class DecomposeRequest(BaseModel):
    intent: str = Field(..., min_length=3, max_length=500)


class DecomposeResponse(BaseModel):
    plan_id: str
    intent: str
    steps: list[PlanStep]
    total_usdc: float
    total_eta: float


class ExecuteRequest(BaseModel):
    plan_id: str = Field(..., max_length=64)
    auth_id_hex: str | None = Field(
        default=None, pattern=r"^[0-9a-fA-F]{32}$"
    )  # 32-hex auth id from PaymentEscrow.authorize
    payer: str | None = Field(default=None, pattern=r"^G[A-Z2-7]{55}$")  # G... address of the payer (from Freighter)


class ExecuteResponse(BaseModel):
    task_id: str


class X402Request(BaseModel):
    # agent_id is echoed into the X-Orizon-Payment-Required response header —
    # restrict it to a safe token so header injection (CR/LF) is impossible.
    agent_id: str = Field(..., max_length=64, pattern=r"^[A-Za-z0-9_.\-]{1,64}$")
    amount_usdc: float = Field(..., gt=0, le=10_000, allow_inf_nan=False)


class X402Response(BaseModel):
    status: Literal["402", "paid"]
    receipt: str | None = None
