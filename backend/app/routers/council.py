import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models, orchestrator
from ..database import get_db

router = APIRouter(prefix="/tasks/{task_id}/agents", tags=["council"])


class RunAgentRequest(BaseModel):
    agent_id: uuid.UUID


def _get_task(db: Session, task_id: uuid.UUID) -> models.Task:
    task = db.get(models.Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return task


@router.post("/pm/run")
def run_pm(task_id: uuid.UUID, payload: RunAgentRequest, db: Session = Depends(get_db)):
    task = _get_task(db, task_id)
    reply = orchestrator.run_pm_intake(db, task, payload.agent_id)
    return {"reply": reply, "task_state": task.state}


@router.post("/engineering/run")
def run_engineering(task_id: uuid.UUID, payload: RunAgentRequest, db: Session = Depends(get_db)):
    task = _get_task(db, task_id)
    reply = orchestrator.run_engineering_proposal(db, task, payload.agent_id)
    return {"reply": reply, "task_state": task.state}


@router.post("/risk/run")
def run_risk(task_id: uuid.UUID, payload: RunAgentRequest, db: Session = Depends(get_db)):
    task = _get_task(db, task_id)
    reply = orchestrator.run_risk_assessment(db, task, payload.agent_id)
    return {"reply": reply, "task_state": task.state}


@router.post("/reviewer/run")
def run_reviewer(task_id: uuid.UUID, payload: RunAgentRequest, db: Session = Depends(get_db)):
    task = _get_task(db, task_id)
    to_state, reply = orchestrator.run_review(db, task, payload.agent_id)
    return {"reply": reply, "task_state": to_state}
