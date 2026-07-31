from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field

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


def humanize_age(seconds: float) -> str:
    """Coarse relative age, e.g. 125.0 → "2m ago". Clock skew reads "just now"."""
    if seconds < 10:
        return "just now"
    if seconds < 60:
        return f"{int(seconds)}s ago"
    if seconds < 3_600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86_400:
        return f"{int(seconds // 3_600)}h ago"
    return f"{int(seconds // 86_400)}d ago"


class TaskSummary(BaseModel):
    """A task without its artifact — the shape the task list is served in.

    An artifact carries `files[*].content` plus a byte-identical `preview_html`
    (30–38 KB for a baked kit), so a completed task is ~70 KB. The dashboard
    polls the list every 5s and reads none of it, which made a full list ~1.4 MB
    per poll per open tab. Listing summaries keeps the poll cheap; the payload
    is served by GET /tasks/{id}/artifact, the one place it is actually read.
    """

    id: str
    intent: str
    agents: int
    spent: float
    status: TaskStatus
    # Unix epoch seconds — the machine-readable truth, and what a client should
    # format itself. Pre-rendering a relative string server-side is what froze
    # the old `started` field at "just now": it was written once at creation and
    # nothing ever recomputed it, so hours-old rows still claimed to be seconds
    # old. `started` below stays in the payload, unchanged in type, because the
    # dashboard renders it verbatim (`started: string` in lib/types.ts) — but it
    # is now derived, never stored, so it cannot go stale again.
    started_at: float = Field(default_factory=time.time)
    charge_tx: str | None = None
    proof_tx: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def started(self) -> str:
        """Human-readable age ("2m ago"), computed at serialization time."""
        return humanize_age(time.time() - self.started_at)


class Task(TaskSummary):
    """A stored task, artifact included. This is what app state holds and what
    the per-task routes serve; only the list route narrows to TaskSummary."""

    artifact: dict | None = None


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
    # Capability token for reading this task (status/artifact/trace). Always
    # returned so clients can store it before TASK_AUTH_REQUIRED is flipped
    # on; harmless while enforcement is off.
    read_token: str | None = None


class X402Request(BaseModel):
    # agent_id is echoed into the X-Orizon-Payment-Required response header —
    # restrict it to a safe token so header injection (CR/LF) is impossible.
    agent_id: str = Field(..., max_length=64, pattern=r"^[A-Za-z0-9_.\-]{1,64}$")
    amount_usdc: float = Field(..., gt=0, le=10_000, allow_inf_nan=False)


class X402Response(BaseModel):
    status: Literal["402", "paid"]
    receipt: str | None = None
