from __future__ import annotations

import time
from collections import deque

from .schemas import Agent, StoredPlan, Task, TraceLine


class AppState:
    """Process-local store for agents, tasks, plans, and traces.

    Single-worker by design: render.yaml pins uvicorn to --workers 1, so all
    state lives in this one process. Contents are lost on restart; durable
    facts (payments, attestations, reputation) live on-chain, not here.

    Retention is bounded: only the newest `task_order.maxlen` tasks (with
    their traces) and `plan_order.maxlen` plans are kept — older entries are
    evicted on insert so a long-lived process can't grow without bound.
    """

    def __init__(self) -> None:
        self.agents: dict[str, Agent] = {}
        self.tasks: dict[str, Task] = {}
        # Per-task capability read tokens, minted at execute. Kept OFF the
        # Task model (it is a response shape — a token field would leak) and
        # evicted in lockstep with tasks/traces below.
        self.task_tokens: dict[str, str] = {}
        self.task_order: deque[str] = deque(maxlen=200)
        self.traces: dict[str, list[TraceLine]] = {}
        self.plans: dict[str, StoredPlan] = {}
        self.plan_order: deque[str] = deque(maxlen=200)
        self.started_at: float = time.time()

    def add_agent(self, agent: Agent) -> None:
        self.agents[agent.id] = agent

    def list_agents(self) -> list[Agent]:
        return list(self.agents.values())

    def add_task(self, task: Task) -> None:
        # appendleft on a full deque silently drops the rightmost (oldest)
        # id — capture it first so its task + trace entries go with it.
        evicted = self.task_order[-1] if len(self.task_order) == self.task_order.maxlen else None
        self.tasks[task.id] = task
        self.task_order.appendleft(task.id)
        if evicted is not None and evicted != task.id:
            self.tasks.pop(evicted, None)
            self.traces.pop(evicted, None)
            self.task_tokens.pop(evicted, None)

    def add_plan(self, plan: StoredPlan) -> None:
        evicted = self.plan_order[-1] if len(self.plan_order) == self.plan_order.maxlen else None
        self.plans[plan.id] = plan
        self.plan_order.appendleft(plan.id)
        if evicted is not None and evicted != plan.id:
            self.plans.pop(evicted, None)

    def recent_tasks(self, limit: int = 20) -> list[Task]:
        return [self.tasks[tid] for tid in list(self.task_order)[:limit] if tid in self.tasks]

    def append_trace(self, task_id: str, line: TraceLine) -> None:
        self.traces.setdefault(task_id, []).append(line)


state = AppState()
