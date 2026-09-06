import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..state_machine import InvalidTransition, validate_transition

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _get_task(db: Session, task_id: uuid.UUID) -> models.Task:
    task = db.get(models.Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return task


def _apply_transition(db: Session, task: models.Task, to_state: str) -> None:
    try:
        validate_transition(task.state, to_state)
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    task.state = to_state
    task.updated_at = datetime.datetime.now(datetime.timezone.utc)


def _post_message(db: Session, task: models.Task, payload: schemas.MessageCreate) -> models.Message:
    message = models.Message(thread_id=task.thread_id, **payload.model_dump())
    db.add(message)
    return message


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
    task = _get_task(db, task_id)
    messages = (
        db.query(models.Message)
        .filter(models.Message.thread_id == task.thread_id)
        .order_by(models.Message.created_at)
        .all()
    )
    receipt = db.query(models.Receipt).filter(models.Receipt.task_id == task_id).first()
    return schemas.TaskDetailOut(
        **schemas.TaskOut.model_validate(task).model_dump(),
        messages=[schemas.MessageOut.model_validate(m) for m in messages],
        receipt=schemas.ReceiptOut.model_validate(receipt) if receipt else None,
    )


@router.post("/{task_id}/contract", response_model=schemas.TaskOut)
def post_contract(task_id: uuid.UUID, payload: schemas.ContractPayload, db: Session = Depends(get_db)):
    """PM agent posts the contract; proposed -> contracted."""
    task = _get_task(db, task_id)
    _apply_transition(db, task, "contracted")

    task.objective = payload.objective
    task.scope = payload.scope
    task.constraints = payload.constraints
    task.acceptance_criteria = payload.acceptance_criteria

    contract_summary = (
        f"objective: {payload.objective}\n"
        f"scope: {payload.scope}\n"
        f"constraints: {payload.constraints}\n"
        f"acceptance_criteria: {payload.acceptance_criteria}"
    )
    _post_message(
        db,
        task,
        schemas.MessageCreate(
            author_type="agent",
            author_id=payload.pm_agent_id,
            message_type="contract",
            content=contract_summary,
        ),
    )
    db.commit()
    db.refresh(task)
    return task


@router.post("/{task_id}/claim", response_model=schemas.TaskOut)
def claim_task(task_id: uuid.UUID, payload: schemas.ClaimPayload, db: Session = Depends(get_db)):
    """Engineering and/or Risk claim the task; contracted -> in_progress.

    Both agents claim in parallel per the spec's state machine, so a second
    claim on an already-in_progress task is a no-op rather than an error.
    """
    task = _get_task(db, task_id)
    if task.state == "contracted":
        _apply_transition(db, task, "in_progress")
        task.owner_agent_id = payload.agent_id
    elif task.state != "in_progress":
        raise HTTPException(
            status_code=409, detail=f"cannot claim task in state '{task.state}'"
        )
    db.commit()
    db.refresh(task)
    return task


def _advance_to_review_if_ready(db: Session, task: models.Task) -> None:
    """in_progress -> in_review once both Engineering and Risk have posted an output."""
    if task.state != "in_progress":
        return
    posted_types = {
        row[0]
        for row in db.query(models.Message.message_type)
        .filter(models.Message.thread_id == task.thread_id)
        .distinct()
    }
    if {"proposal", "decision"} <= posted_types:
        _apply_transition(db, task, "in_review")


@router.post("/{task_id}/messages", response_model=schemas.MessageOut, status_code=201)
def post_message(task_id: uuid.UUID, payload: schemas.MessageCreate, db: Session = Depends(get_db)):
    task = _get_task(db, task_id)
    message = _post_message(db, task, payload)
    _advance_to_review_if_ready(db, task)
    db.commit()
    db.refresh(message)
    return message


@router.post("/{task_id}/review", response_model=schemas.TaskDetailOut)
def review_task(task_id: uuid.UUID, payload: schemas.ReviewPayload, db: Session = Depends(get_db)):
    """Reviewer verdict: approve (-> approved, generates receipt) or reject (-> in_progress)."""
    task = _get_task(db, task_id)

    if payload.verdict == "approve":
        _apply_transition(db, task, "approved")
        receipt = models.Receipt(
            task_id=task.id,
            objective=payload.objective or task.objective,
            changed=payload.changed,
            verified=payload.verified,
            not_verified=payload.not_verified,
            risks=payload.risks,
            approval_needed=payload.approval_needed,
            decided_by=payload.reviewer_agent_id,
            decided_at=datetime.datetime.now(datetime.timezone.utc),
        )
        db.add(receipt)
        _post_message(
            db,
            task,
            schemas.MessageCreate(
                author_type="agent",
                author_id=payload.reviewer_agent_id,
                message_type="receipt",
                content=f"Approved. objective={receipt.objective!r}",
            ),
        )
    else:
        _apply_transition(db, task, "in_progress")
        _post_message(
            db,
            task,
            schemas.MessageCreate(
                author_type="agent",
                author_id=payload.reviewer_agent_id,
                message_type="critique",
                content=payload.reason,
                rejected_to_agent_id=payload.rejected_to_agent_id,
            ),
        )

    db.commit()
    return get_task(task_id, db)
