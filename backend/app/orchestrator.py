"""Claude API wiring for the council agents (build spec section 3 + 5).

Each function calls the Anthropic Messages API with the role's system prompt
and the task/thread context, then applies the result to the task via the
state machine — mirroring the flow in `docs`/schema section 2:

    proposed -> [pm]        -> contracted
    contracted -> [eng, risk] (parallel) -> in_progress
    in_progress -> [reviewer] -> in_review -> approved | rejected
"""

import datetime
import json
import os
import re
import uuid

import anthropic
from sqlalchemy.orm import Session

from . import models
from .prompts import get_system_prompt
from .state_machine import validate_transition

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    return _client


def _thread_transcript(db: Session, thread_id: uuid.UUID) -> str:
    messages = (
        db.query(models.Message)
        .filter(models.Message.thread_id == thread_id)
        .order_by(models.Message.created_at)
        .all()
    )
    if not messages:
        return "(no messages yet)"
    return "\n\n".join(f"[{m.message_type} / {m.author_type}] {m.content}" for m in messages)


def _task_summary(task: models.Task) -> str:
    return (
        f"Title: {task.title}\n"
        f"Objective: {task.objective or '(none yet)'}\n"
        f"Scope: {task.scope}\n"
        f"Constraints: {task.constraints}\n"
        f"Acceptance criteria: {task.acceptance_criteria}\n"
        f"Policy tier: {task.policy_tier or '(none yet)'}\n"
        f"State: {task.state}"
    )


def _call_agent(role: str, task: models.Task, db: Session, extra: str = "") -> str:
    system_prompt = get_system_prompt(role)
    user_content = (
        f"Task contract so far:\n{_task_summary(task)}\n\n"
        f"Thread so far:\n{_thread_transcript(db, task.thread_id)}\n"
        f"{extra}"
    )
    response = _get_client().messages.create(
        model=MODEL,
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )
    return "".join(block.text for block in response.content if block.type == "text")


def _post_message(db: Session, task: models.Task, agent_id: uuid.UUID, message_type: str, content: str) -> None:
    db.add(
        models.Message(
            thread_id=task.thread_id,
            author_type="agent",
            author_id=agent_id,
            message_type=message_type,
            content=content,
        )
    )


CONTRACT_FORMAT_INSTRUCTION = (
    "\nRespond starting with exactly one of these first lines: 'CONTRACT: READY' or "
    "'CONTRACT: NEEDS_CLARIFICATION'. If ready, follow it with a fenced ```json code block "
    "whose keys are objective (string), scope, constraints, acceptance_criteria (each a list "
    "of strings). If it needs clarification, follow it with your question."
)


def run_pm_intake(db: Session, task: models.Task, pm_agent_id: uuid.UUID) -> str:
    """proposed -> contracted (or stays proposed with a clarifying question)."""
    reply = _call_agent("pm", task, db, extra=CONTRACT_FORMAT_INSTRUCTION)
    ready = reply.strip().upper().startswith("CONTRACT: READY")
    _post_message(db, task, pm_agent_id, "contract" if ready else "critique", reply)

    if ready:
        fields = _extract_json_block(reply) or {}
        task.objective = fields.get("objective") or task.objective
        task.scope = fields.get("scope") or task.scope
        task.constraints = fields.get("constraints") or task.constraints
        task.acceptance_criteria = fields.get("acceptance_criteria") or task.acceptance_criteria
        validate_transition(task.state, "contracted")
        task.state = "contracted"

    db.commit()
    return reply


def _claim(task: models.Task) -> None:
    """contracted -> in_progress, the moment Engineering or Risk starts work."""
    if task.state == "contracted":
        validate_transition(task.state, "in_progress")
        task.state = "in_progress"


def _advance_to_review_if_ready(db: Session, task: models.Task) -> None:
    """in_progress -> in_review once both Engineering and Risk have posted."""
    if task.state != "in_progress" or task.policy_tier is None:
        return
    has_proposal = (
        db.query(models.Message)
        .filter(models.Message.thread_id == task.thread_id, models.Message.message_type == "proposal")
        .first()
        is not None
    )
    if has_proposal:
        validate_transition(task.state, "in_review")
        task.state = "in_review"


def run_engineering_proposal(db: Session, task: models.Task, eng_agent_id: uuid.UUID) -> str:
    """contracted -> in_progress; proposal posted by Engineering Lead."""
    _claim(task)
    reply = _call_agent("engineering_lead", task, db)
    _post_message(db, task, eng_agent_id, "proposal", reply)
    _advance_to_review_if_ready(db, task)
    db.commit()
    return reply


TIER_FORMAT_INSTRUCTION = (
    "\nRespond starting with exactly one of these first lines: 'TIER: auto', "
    "'TIER: approval_required', or 'TIER: prohibited'. Follow it with your one-line reasoning."
)

_TIER_VALUES = {"auto", "approval_required", "prohibited"}


def run_risk_assessment(db: Session, task: models.Task, risk_agent_id: uuid.UUID) -> str:
    """contracted -> in_progress; policy tier assigned by Risk/Governance."""
    _claim(task)
    reply = _call_agent("risk_governance", task, db, extra=TIER_FORMAT_INSTRUCTION)
    _post_message(db, task, risk_agent_id, "decision", reply)

    first_line = reply.strip().splitlines()[0].strip()
    tier = first_line.split(":", 1)[1].strip().lower() if ":" in first_line else ""
    if tier in _TIER_VALUES:
        task.policy_tier = tier

    _advance_to_review_if_ready(db, task)
    db.commit()
    return reply


RECEIPT_FORMAT_INSTRUCTION = (
    "\nRespond starting with exactly one of these first lines: 'VERDICT: APPROVED' or "
    "'VERDICT: REJECTED'. If approved, follow it with a fenced ```json code block whose keys "
    "are objective, changed, verified, not_verified, risks, approval_needed (each a string or "
    "list of strings). If rejected, follow it with which agent it goes back to and why."
)


def _extract_json_block(text: str) -> dict | None:
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def run_review(
    db: Session, task: models.Task, reviewer_agent_id: uuid.UUID
) -> tuple[str, str]:
    """in_review -> approved (+ receipt) | rejected, per the Reviewer's verdict."""
    reply = _call_agent("reviewer", task, db, extra=RECEIPT_FORMAT_INSTRUCTION)
    approved = reply.strip().upper().startswith("VERDICT: APPROVED")
    to_state = "approved" if approved else "rejected"
    validate_transition(task.state, to_state)
    _post_message(db, task, reviewer_agent_id, "decision", reply)
    task.state = to_state

    if approved:
        fields = _extract_json_block(reply) or {}

        def as_list(value) -> list[str]:
            if value is None:
                return []
            return value if isinstance(value, list) else [str(value)]

        db.add(
            models.Receipt(
                task_id=task.id,
                objective=fields.get("objective") or task.objective,
                changed=as_list(fields.get("changed")),
                verified=as_list(fields.get("verified")),
                not_verified=as_list(fields.get("not_verified")),
                risks=as_list(fields.get("risks")),
                approval_needed=as_list(fields.get("approval_needed")),
                decided_by=reviewer_agent_id,
                decided_at=datetime.datetime.now(datetime.timezone.utc),
            )
        )

    db.commit()
    return to_state, reply
