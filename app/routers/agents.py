from fastapi import APIRouter, HTTPException

from ..schemas import Agent
from ..state import state

router = APIRouter(tags=["agents"])


@router.get("/agents", response_model=list[Agent])
async def list_agents() -> list[Agent]:
    return state.list_agents()


@router.get("/agents/{agent_id}", response_model=Agent)
async def get_agent(agent_id: str) -> Agent:
    agent = state.agents.get(agent_id)
    if agent is None:
        raise HTTPException(404, f"unknown agent: {agent_id}")
    return agent
