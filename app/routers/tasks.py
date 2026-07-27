from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..config import settings
from ..schemas import Task
from ..state import state
from ..task_auth import require_task_read

router = APIRouter(tags=["tasks"])


class ArtifactResponse(BaseModel):
    """Response shape for /tasks/{task_id}/artifact.

    Mirrors the fields the frontend consumes: `artifact` carries the
    CodeArtifact-shaped dict (`preview_html` for the iframe, `files[]` for
    the code viewer), plus the on-chain charge/proof transaction hashes.
    """

    artifact: dict | None = None
    charge_tx: str | None = None
    proof_tx: str | None = None


@router.get("/tasks", response_model=list[Task], summary="List recent tasks")
async def list_tasks(limit: int = Query(20, ge=1, le=200)) -> list[Task]:
    # Task reads are capability-token-scoped when enforcement is on — the
    # global list would leak every task id and intent, so it goes empty
    # (not 404/401) and the frontend keeps working unmodified.
    if settings.task_auth_required:
        return []
    return state.recent_tasks(limit=limit)


@router.get(
    "/tasks/{task_id}",
    response_model=Task,
    summary="Get a task's status",
    dependencies=[Depends(require_task_read)],
)
async def get_task(task_id: str) -> Task:
    task = state.tasks.get(task_id)
    if task is None:
        raise HTTPException(404, f"unknown task: {task_id}")
    return task


@router.get(
    "/tasks/{task_id}/artifact",
    response_model=ArtifactResponse,
    summary="Get a task's produced artifact",
    dependencies=[Depends(require_task_read)],
)
async def get_artifact(task_id: str) -> ArtifactResponse:
    """Returns the code artifact produced by the workflow, if any."""
    task = state.tasks.get(task_id)
    if task is None:
        raise HTTPException(404, f"unknown task: {task_id}")
    return ArtifactResponse(artifact=task.artifact, charge_tx=task.charge_tx, proof_tx=task.proof_tx)
