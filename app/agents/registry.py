from __future__ import annotations

from .workers.base import Worker
from .workers.code_gen import CodeGen
from .workers.copywrite import Copywrite
from .workers.mock import MockWorker
from .workers.research_pro import ResearchPro
from .workers.seo_brief import SeoBrief
from .workers.sol_audit import SolAudit

# Real Agno workers (GPT-4o-mini)
_REAL: list[Worker] = [
    Copywrite(),     # agt_01h8 copywrite.v3
    SeoBrief(),      # agt_05x7 seo.brief
    ResearchPro(),   # agt_09l5 research.pro
    SolAudit(),      # agt_04m1 sol-audit
    CodeGen(),       # agt_11c0 code.gen
]

# Mock workers for the remaining agents in the registry
_MOCK: list[Worker] = [
    MockWorker("agt_02k2", "design.figma"),
    MockWorker("agt_03d9", "code.next"),
    MockWorker("agt_06q4", "vision.ocr"),
    MockWorker("agt_07w3", "ads.meta"),
    MockWorker("agt_08j2", "deploy.v0"),
    MockWorker("agt_10b6", "translate.42"),
]

WORKERS: dict[str, Worker] = {w.id: w for w in (_REAL + _MOCK)}


def get_worker(agent_id: str) -> Worker | None:
    return WORKERS.get(agent_id)
