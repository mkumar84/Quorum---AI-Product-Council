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
    """Posts a message - but while a rejection is outstanding (task.rejected_to_agent_id
    is set), every poster (any agent, or a human) must name exactly which critique
    they're answering via resolves_message_id. This is what stops an unrelated
    message from ever being mistaken for a fix: it can't even be posted without
    deliberately linking to the critique it's responding to.
    """
    if task.rejected_to_agent_id is not None and payload.resolves_message_id != task.pending_critique_message_id:
        raise HTTPException(
            status_code=422,
            detail=(
                "this task has an outstanding rejection; resolves_message_id must point at "
                f"the critique message that caused it ({task.pending_critique_message_id})"
            ),
        )
    if payload.message_type == "contract" and task.policy_tier is not None:
        # A contract amendment invalidates whatever tier Risk assigned to the
        # prior text - that decision was never made against this version of
        # the contract. Reset it so advance_to_review_if_ready's existing
        # policy_tier-is-set gate forces a fresh Risk turn before this can
        # reach in_review, rather than letting the Reviewer certify a tier
        # nobody actually re-checked (the HQ-102 gap).
        task.policy_tier = None
    message = models.Message(thread_id=task.thread_id, **payload.model_dump())
    db.add(message)
    db.flush()  # populate message.id now - callers often need it immediately (e.g. to
    # record it as task.pending_critique_message_id), before any explicit commit
    return message


# The message type that actually counts as "this role's real output" - a
# clarifying question (critique) from PM, say, links to the rejection via
# resolves_message_id too, but doesn't itself resolve it.
_RESOLUTION_MESSAGE_TYPE = {
    "pm": "contract",
    "engineering_lead": "proposal",
    "risk_governance": "decision",
}


def advance_to_review_if_ready(db: Session, task: models.Task) -> None:
    """in_progress -> in_review, either the first time (Engineering has proposed
    and Risk has assigned a tier) or after a rejection (the targeted agent's
    linked resolution has landed) - clearing the rejection in the latter case.

    Not gated on generic message-type presence once a rejection is outstanding:
    that let any message from anyone re-open review without the actual defect
    being addressed. It now requires a message that (a) links to the specific
    critique via resolves_message_id, (b) comes from the agent it was rejected
    to, and (c) is that role's real output type, not just an acknowledgment.
    """
    if task.state != "in_progress":
        return

    if task.rejected_to_agent_id is not None:
        target_agent = db.get(models.Agent, task.rejected_to_agent_id)
        expected_type = _RESOLUTION_MESSAGE_TYPE.get(target_agent.role) if target_agent else None
        resolved = (
            db.query(models.Message)
            .filter(
                models.Message.thread_id == task.thread_id,
                models.Message.resolves_message_id == task.pending_critique_message_id,
                models.Message.author_id == task.rejected_to_agent_id,
                models.Message.message_type == expected_type,
            )
            .first()
            is not None
        )
        if not resolved:
            return
        task.rejected_to_agent_id = None
        task.pending_critique_message_id = None
        if task.policy_tier is None:
            # The resolving message was a contract amendment that reset the
            # tier (see post_message) - the rejection is cleared, but this
            # must wait for Risk's fresh decision before in_review, same as
            # a first-time contract. Falls through to the tier gate below on
            # Risk's next turn rather than certifying a tier no one re-checked.
            return
        apply_transition(db, task, "in_review")
        return

    if task.policy_tier is None:
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
    message = post_message(
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
    task.rejected_to_agent_id = payload.rejected_to_agent_id
    task.pending_critique_message_id = message.id
    return message


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
