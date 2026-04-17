from fastapi import APIRouter, HTTPException

from ..schemas import Task
from ..state import state

router = APIRouter(tags=["tasks"])


@router.get("/tasks", response_model=list[Task])
async def list_tasks(limit: int = 20) -> list[Task]:
    return state.recent_tasks(limit=limit)


@router.get("/tasks/{task_id}", response_model=Task)
async def get_task(task_id: str) -> Task:
    task = state.tasks.get(task_id)
    if task is None:
        raise HTTPException(404, f"unknown task: {task_id}")
    return task
