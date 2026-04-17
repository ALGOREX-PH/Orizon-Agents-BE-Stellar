from __future__ import annotations

import time
from collections import deque
from typing import Deque

from .schemas import Agent, StoredPlan, Task, TraceLine


class AppState:
    def __init__(self) -> None:
        self.agents: dict[str, Agent] = {}
        self.tasks: dict[str, Task] = {}
        self.task_order: Deque[str] = deque(maxlen=200)
        self.traces: dict[str, list[TraceLine]] = {}
        self.plans: dict[str, StoredPlan] = {}
        self.started_at: float = time.time()

    def add_agent(self, agent: Agent) -> None:
        self.agents[agent.id] = agent

    def list_agents(self) -> list[Agent]:
        return list(self.agents.values())

    def add_task(self, task: Task) -> None:
        self.tasks[task.id] = task
        self.task_order.appendleft(task.id)

    def recent_tasks(self, limit: int = 20) -> list[Task]:
        return [self.tasks[tid] for tid in list(self.task_order)[:limit] if tid in self.tasks]

    def append_trace(self, task_id: str, line: TraceLine) -> None:
        self.traces.setdefault(task_id, []).append(line)


state = AppState()
