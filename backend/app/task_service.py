"""Shared task-lifecycle logic used by both the HTTP routers and the
orchestrator/council, so an agent's turn and a human's manual API call go
through the exact same state-machine-enforced code path (and, when called
from the orchestrator, the same db session/transaction).
"""

import datetime
import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from . import models, schemas
from .state_machine import InvalidTransition, validate_transition


def get_task_or_404(db: Session, task_id: uuid.UUID) -> models.Task:
    task = db.get(models.Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return task


def get_agent_by_role(db: Session, role: str) -> models.Agent:
    agent = db.query(models.Agent).filter(models.Agent.role == role).first()
    if not agent:
        raise HTTPException(status_code=404, detail=f"no seeded agent with role '{role}'")
    return agent


def apply_transition(db: Session, task: models.Task, to_state: str) -> None:
    try:
        validate_transition(task.state, to_state)
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    task.state = to_state
    task.updated_at = datetime.datetime.now(datetime.timezone.utc)


def post_message(db: Session, task: models.Task, payload: schemas.MessageCreate) -> models.Message:
    message = models.Message(thread_id=task.thread_id, **payload.model_dump())
    db.add(message)
    return message


def advance_to_review_if_ready(db: Session, task: models.Task) -> None:
    """in_progress -> in_review once Engineering has proposed and Risk has assigned a tier.

    Gated on task.policy_tier rather than the presence of a 'decision'-typed
    message: a message's type is just a label anyone (including a human) can
    post, and the tier is the actual signal that Risk has done its job.
    """
    if task.state != "in_progress" or task.policy_tier is None:
        return
    has_proposal = (
        db.query(models.Message)
        .filter(models.Message.thread_id == task.thread_id, models.Message.message_type == "proposal")
        .first()
        is not None
    )
    if has_proposal:
        apply_transition(db, task, "in_review")


def claim(db: Session, task: models.Task, agent_id: uuid.UUID) -> None:
    """Engineering and/or Risk claim the task; contracted -> in_progress.

    Both agents claim in parallel per the spec's state machine, so a second
    claim on an already-in_progress task is a no-op rather than an error.
    """
    if task.state == "contracted":
        apply_transition(db, task, "in_progress")
        task.owner_agent_id = agent_id
    elif task.state != "in_progress":
        raise HTTPException(status_code=409, detail=f"cannot claim task in state '{task.state}'")


def apply_contract(db: Session, task: models.Task, payload: schemas.ContractPayload) -> models.Message:
    """PM agent posts the contract; proposed -> contracted."""
    apply_transition(db, task, "contracted")

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
    return post_message(
        db,
        task,
        schemas.MessageCreate(
            author_type="agent",
            author_id=payload.pm_agent_id,
            message_type="contract",
            content=contract_summary,
        ),
    )


def apply_review(db: Session, task: models.Task, payload: schemas.ReviewPayload) -> models.Message:
    """Reviewer verdict: approve (-> approved, generates receipt) or reject (-> in_progress)."""
    if payload.verdict == "approve":
        apply_transition(db, task, "approved")
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
        return post_message(
            db,
            task,
            schemas.MessageCreate(
                author_type="agent",
                author_id=payload.reviewer_agent_id,
                message_type="receipt",
                content=f"Approved. objective={receipt.objective!r}",
            ),
        )

    apply_transition(db, task, "in_progress")
    return post_message(
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


def get_task_detail(db: Session, task: models.Task) -> schemas.TaskDetailOut:
    messages = (
        db.query(models.Message)
        .filter(models.Message.thread_id == task.thread_id)
        .order_by(models.Message.created_at)
        .all()
    )
    receipt = db.query(models.Receipt).filter(models.Receipt.task_id == task.id).first()
    return schemas.TaskDetailOut(
        **schemas.TaskOut.model_validate(task).model_dump(),
        messages=[schemas.MessageOut.model_validate(m) for m in messages],
        receipt=schemas.ReceiptOut.model_validate(receipt) if receipt else None,
    )
