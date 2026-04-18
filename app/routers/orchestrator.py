from fastapi import APIRouter, HTTPException

from ..schemas import DecomposeRequest, DecomposeResponse, ExecuteRequest, ExecuteResponse
from ..services.execution_svc import execute_plan
from ..services.orchestrator_svc import decompose
from ..state import state

router = APIRouter(prefix="/orchestrator", tags=["orchestrator"])


@router.post("/decompose", response_model=DecomposeResponse)
async def orchestrator_decompose(req: DecomposeRequest) -> DecomposeResponse:
    try:
        return await decompose(req.intent)
    except Exception as e:
        raise HTTPException(502, f"orchestrator failed: {e}") from e


@router.post("/execute", response_model=ExecuteResponse)
async def orchestrator_execute(req: ExecuteRequest) -> ExecuteResponse:
    plan = state.plans.get(req.plan_id)
    if plan is None:
        raise HTTPException(404, f"unknown plan_id: {req.plan_id}")
    task_id = await execute_plan(plan, auth_id_hex=req.auth_id_hex, payer=req.payer)
    return ExecuteResponse(task_id=task_id)
