import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import council, models, orchestrator, schemas, task_service
from ..database import get_db

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=schemas.TaskOut, status_code=201)
def create_task(payload: schemas.TaskCreate, db: Session = Depends(get_db)):
    """Create a task in `proposed` state from a raw feature request."""
    task = models.Task(title=payload.title)
    db.add(task)
    db.flush()  # assigns task.id without committing

    thread = models.Thread(task_id=task.id)
    db.add(thread)
    db.flush()

    task.thread_id = thread.id
    db.commit()
    db.refresh(task)
    return task


@router.get("", response_model=list[schemas.TaskOut])
def list_tasks(state: str | None = None, db: Session = Depends(get_db)):
    query = db.query(models.Task)
    if state:
        query = query.filter(models.Task.state == state)
    return query.order_by(models.Task.created_at).all()


@router.get("/{task_id}", response_model=schemas.TaskDetailOut)
def get_task(task_id: uuid.UUID, db: Session = Depends(get_db)):
    """Full task plus its thread history and receipt (if approved)."""
    task = task_service.get_task_or_404(db, task_id)
    return task_service.get_task_detail(db, task)


@router.post("/{task_id}/contract", response_model=schemas.TaskOut)
def post_contract(task_id: uuid.UUID, payload: schemas.ContractPayload, db: Session = Depends(get_db)):
    """PM agent posts the contract; proposed -> contracted."""
    task = task_service.get_task_or_404(db, task_id)
    task_service.apply_contract(db, task, payload)
    db.commit()
    db.refresh(task)
    council.on_task_updated(db, task)
    return task


@router.post("/{task_id}/claim", response_model=schemas.TaskOut)
def claim_task(task_id: uuid.UUID, payload: schemas.ClaimPayload, db: Session = Depends(get_db)):
    task = task_service.get_task_or_404(db, task_id)
    task_service.claim(db, task, payload.agent_id)
    db.commit()
    db.refresh(task)
    return task


@router.post("/{task_id}/messages", response_model=schemas.MessageOut, status_code=201)
def post_message(task_id: uuid.UUID, payload: schemas.MessageCreate, db: Session = Depends(get_db)):
    task = task_service.get_task_or_404(db, task_id)
    message = task_service.post_message(db, task, payload)
    task_service.advance_to_review_if_ready(db, task)
    db.commit()
    db.refresh(message)
    council.on_task_updated(db, task)
    return message


@router.post("/{task_id}/review", response_model=schemas.TaskDetailOut)
def review_task(task_id: uuid.UUID, payload: schemas.ReviewPayload, db: Session = Depends(get_db)):
    task = task_service.get_task_or_404(db, task_id)
    task_service.apply_review(db, task, payload)
    db.commit()
    return task_service.get_task_detail(db, task)


@router.post("/{task_id}/run", response_model=schemas.MessageOut, status_code=201)
def run_agent(task_id: uuid.UUID, payload: schemas.RunAgentPayload, db: Session = Depends(get_db)):
    """Manually trigger a single agent's turn, in isolation from the automatic chain.

    For debugging one agent's Claude output before wiring `council.py`'s
    state-driven cascade into the normal request flow.
    """
    task = task_service.get_task_or_404(db, task_id)
    run_fn = {
        "pm": orchestrator.run_pm,
        "engineering": orchestrator.run_engineering,
        "risk": orchestrator.run_risk,
        "reviewer": orchestrator.run_reviewer,
    }[payload.role]
    return run_fn(db, task)
