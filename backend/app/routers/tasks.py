import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..state_machine import InvalidTransition, validate_transition

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=schemas.TaskOut, status_code=201)
def create_task(payload: schemas.TaskCreate, db: Session = Depends(get_db)):
    task = models.Task(**payload.model_dump())
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


@router.get("/{task_id}", response_model=schemas.TaskOut)
def get_task(task_id: uuid.UUID, db: Session = Depends(get_db)):
    task = db.get(models.Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return task


@router.patch("/{task_id}", response_model=schemas.TaskOut)
def update_task(task_id: uuid.UUID, payload: schemas.TaskUpdate, db: Session = Depends(get_db)):
    task = db.get(models.Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(task, field, value)
    db.commit()
    db.refresh(task)
    return task


@router.post("/{task_id}/transition", response_model=schemas.TaskOut)
def transition_task(task_id: uuid.UUID, payload: schemas.TaskTransition, db: Session = Depends(get_db)):
    task = db.get(models.Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")

    try:
        validate_transition(task.state, payload.to_state)
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    task.state = payload.to_state
    task.updated_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
    db.refresh(task)
    return task
