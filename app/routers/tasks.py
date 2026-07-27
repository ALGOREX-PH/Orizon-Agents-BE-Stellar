
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..schemas import Task
from ..state import state

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


@router.get("/tasks", response_model=list[Task])
async def list_tasks(limit: int = Query(20, ge=1, le=200)) -> list[Task]:
    return state.recent_tasks(limit=limit)


@router.get("/tasks/{task_id}", response_model=Task)
async def get_task(task_id: str) -> Task:
    task = state.tasks.get(task_id)
    if task is None:
        raise HTTPException(404, f"unknown task: {task_id}")
    return task


@router.get("/tasks/{task_id}/artifact", response_model=ArtifactResponse)
async def get_artifact(task_id: str) -> ArtifactResponse:
    """Returns the code artifact produced by the workflow, if any."""
    task = state.tasks.get(task_id)
    if task is None:
        raise HTTPException(404, f"unknown task: {task_id}")
    return ArtifactResponse(
        artifact=task.artifact, charge_tx=task.charge_tx, proof_tx=task.proof_tx
    )
