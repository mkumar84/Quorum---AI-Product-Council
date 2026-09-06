"""Claude API wiring for the council agents (build spec section 3 + 5).

One function per role. Each:
  1. loads that role's system prompt from app/prompts.py (sourced from
     agents/system-prompts.md)
  2. pulls the task + full thread history from Postgres
  3. calls Claude (Sonnet) with the prompt + thread as context
  4. posts the reply back via task_service.post_message, applying whatever
     state change that role's turn implies

Everything for one agent's turn — read, Claude call, message insert, state
transition, receipt if any — shares the caller's db session and commits once
at the end of the function, so it's one transaction rather than a round trip
through the HTTP API.
"""

import datetime
import json
import os
import re
import time

import anthropic
from fastapi import HTTPException
from sqlalchemy.orm import Session

from . import models, schemas, task_service
from .prompts import get_system_prompt

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

MAX_CLAUDE_RETRIES = 2
RETRY_BACKOFF_SECONDS = [1, 4]  # one entry per retry (not per attempt) - 1s, then 4s

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    return _client


def _call_claude(system_prompt: str, user_content: str) -> str:
    try:
        response = _get_client().messages.create(
            model=MODEL,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
    except anthropic.AuthenticationError as exc:
        raise HTTPException(status_code=502, detail=f"Claude API authentication failed: {exc}") from exc
    except anthropic.RateLimitError as exc:
        raise HTTPException(status_code=502, detail=f"Claude API rate limited: {exc}") from exc
    except anthropic.APIStatusError as exc:
        raise HTTPException(
            status_code=502, detail=f"Claude API error ({exc.status_code}): {exc.message}"
        ) from exc
    except anthropic.APIConnectionError as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach Claude API: {exc}") from exc
    except Exception as exc:
        # e.g. no credentials configured at all - the SDK raises a plain TypeError
        # from header validation before any request is attempted, not an API error.
        raise HTTPException(status_code=502, detail=f"Claude API call failed: {exc}") from exc

    return "".join(block.text for block in response.content if block.type == "text")


class ClaudeCallFailed(Exception):
    """Raised by _call_claude_with_retries when every attempt, retries included, failed."""


def _call_claude_with_retries(system_prompt: str, user_content: str) -> str:
    """At most MAX_CLAUDE_RETRIES retries (so MAX_CLAUDE_RETRIES + 1 attempts total),
    with exponential backoff between attempts - not unbounded retrying."""
    last_exc: Exception | None = None
    for attempt in range(MAX_CLAUDE_RETRIES + 1):
        try:
            return _call_claude(system_prompt, user_content)
        except Exception as exc:
            last_exc = exc
            if attempt < MAX_CLAUDE_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS[attempt])
    raise ClaudeCallFailed(
        f"Claude call failed after {MAX_CLAUDE_RETRIES + 1} attempts: {last_exc}"
    ) from last_exc


class _Blocked(Exception):
    """Internal signal: the agent's Claude call exhausted its retries, and the
    task has already been logged + transitioned to blocked. Each run_* function
    catches this once and returns the system_error message instead of raising -
    a failed agent call is a handled outcome, not a crash."""

    def __init__(self, message: "models.Message"):
        self.message = message


def _run_or_block(
    db: Session, task: models.Task, agent: models.Agent, system_prompt: str, user_content: str
) -> str:
    """Calls Claude with retries; on exhaustion, blocks the task and raises _Blocked
    (caught by the calling run_* function, which returns the logged message)."""
    try:
        return _call_claude_with_retries(system_prompt, user_content)
    except ClaudeCallFailed as exc:
        message = task_service.post_message(
            db,
            task,
            schemas.MessageCreate(
                author_type="agent",
                author_id=agent.id,
                message_type="system_error",
                content=(
                    f"[agent-call-failed] {agent.role} agent's Claude call failed after "
                    f"{MAX_CLAUDE_RETRIES + 1} attempts (initial + {MAX_CLAUDE_RETRIES} retries "
                    f"with backoff) and was not retried further: {exc}"
                ),
            ),
        )
        task_service.apply_transition(db, task, "blocked")
        db.commit()
        db.refresh(message)
        raise _Blocked(message) from exc


def _thread_transcript(db: Session, thread_id) -> str:
    messages = (
        db.query(models.Message)
        .filter(models.Message.thread_id == thread_id)
        .order_by(models.Message.created_at)
        .all()
    )
    if not messages:
        return "(no messages yet)"
    return "\n\n".join(f"[{m.message_type} / {m.author_type}] {m.content}" for m in messages)


def _build_context(db: Session, task: models.Task) -> str:
    return (
        f"Task contract so far:\n"
        f"Title: {task.title}\n"
        f"Objective: {task.objective or '(none yet)'}\n"
        f"Scope: {task.scope}\n"
        f"Constraints: {task.constraints}\n"
        f"Acceptance criteria: {task.acceptance_criteria}\n"
        f"Policy tier: {task.policy_tier or '(none yet)'}\n"
        f"State: {task.state}\n\n"
        f"Thread so far:\n{_thread_transcript(db, task.thread_id)}\n"
    )


def _extract_json_block(text: str) -> dict | None:
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def _require_state(task: models.Task, *allowed: str) -> None:
    if task.state not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"agent turn requires task state in {allowed}, task is '{task.state}'",
        )


CONTRACT_FORMAT_INSTRUCTION = (
    "\nRespond starting with exactly one of these first lines: 'CONTRACT: READY' or "
    "'CONTRACT: NEEDS_CLARIFICATION'. If ready, follow it with a fenced ```json code block "
    "whose keys are objective (string), scope, constraints, acceptance_criteria (each a list "
    "of strings). If it needs clarification, follow it with your question."
)


def run_pm(db: Session, task: models.Task) -> models.Message:
    """proposed -> contracted (or stays proposed with a clarifying question);
    or, if PM is the target of an outstanding rejection, in_progress -> in_review
    once its revised contract is posted - same re-entry pattern as the other
    three agents, no longer a one-shot-only intake step."""
    _require_state(task, "proposed", "in_progress")
    agent = task_service.get_agent_by_role(db, "pm")
    try:
        reply = _run_or_block(
            db, task, agent, get_system_prompt("pm"), _build_context(db, task) + CONTRACT_FORMAT_INSTRUCTION
        )
    except _Blocked as blocked:
        return blocked.message
    ready = reply.strip().upper().startswith("CONTRACT: READY")

    if ready:
        fields = _extract_json_block(reply) or {}
        task.objective = fields.get("objective") or task.objective
        task.scope = fields.get("scope") or task.scope
        task.constraints = fields.get("constraints") or task.constraints
        task.acceptance_criteria = fields.get("acceptance_criteria") or task.acceptance_criteria
        if task.state == "proposed":
            task_service.apply_transition(db, task, "contracted")
        message_type = "contract"
    else:
        message_type = "critique"

    resolves_message_id = task.pending_critique_message_id if task.rejected_to_agent_id else None
    message = task_service.post_message(
        db,
        task,
        schemas.MessageCreate(
            author_type="agent",
            author_id=agent.id,
            message_type=message_type,
            content=reply,
            resolves_message_id=resolves_message_id,
        ),
    )
    task_service.advance_to_review_if_ready(db, task)
    db.commit()
    db.refresh(message)
    return message


def run_engineering(db: Session, task: models.Task) -> models.Message:
    """contracted -> in_progress (claims); posts a proposal."""
    _require_state(task, "contracted", "in_progress")
    agent = task_service.get_agent_by_role(db, "engineering_lead")
    task_service.claim(db, task, agent.id)

    try:
        reply = _run_or_block(db, task, agent, get_system_prompt("engineering_lead"), _build_context(db, task))
    except _Blocked as blocked:
        return blocked.message
    resolves_message_id = task.pending_critique_message_id if task.rejected_to_agent_id else None
    message = task_service.post_message(
        db,
        task,
        schemas.MessageCreate(
            author_type="agent",
            author_id=agent.id,
            message_type="proposal",
            content=reply,
            resolves_message_id=resolves_message_id,
        ),
    )
    task_service.advance_to_review_if_ready(db, task)
    db.commit()
    db.refresh(message)
    return message


TIER_FORMAT_INSTRUCTION = (
    "\nRespond starting with exactly one of these first lines: 'TIER: auto', "
    "'TIER: approval_required', or 'TIER: prohibited'. Follow it with your one-line reasoning."
)

_TIER_VALUES = {"auto", "approval_required", "prohibited"}


def run_risk(db: Session, task: models.Task) -> models.Message:
    """contracted -> in_progress (claims); posts a policy-tier decision."""
    _require_state(task, "contracted", "in_progress")
    agent = task_service.get_agent_by_role(db, "risk_governance")
    task_service.claim(db, task, agent.id)

    try:
        reply = _run_or_block(
            db, task, agent, get_system_prompt("risk_governance"), _build_context(db, task) + TIER_FORMAT_INSTRUCTION
        )
    except _Blocked as blocked:
        return blocked.message
    resolves_message_id = task.pending_critique_message_id if task.rejected_to_agent_id else None
    message = task_service.post_message(
        db,
        task,
        schemas.MessageCreate(
            author_type="agent",
            author_id=agent.id,
            message_type="decision",
            content=reply,
            resolves_message_id=resolves_message_id,
        ),
    )

    first_line = reply.strip().splitlines()[0].strip() if reply.strip() else ""
    tier = first_line.split(":", 1)[1].strip().lower() if ":" in first_line else ""
    if tier in _TIER_VALUES:
        task.policy_tier = tier

    task_service.advance_to_review_if_ready(db, task)
    db.commit()
    db.refresh(message)
    return message


REVIEW_FORMAT_INSTRUCTION = (
    "\nRespond starting with exactly one of these first lines: 'VERDICT: APPROVED' or "
    "'VERDICT: REJECTED'.\nIf REJECTED, the second line must be exactly 'REJECTED_TO: <role>' "
    "where <role> is one of pm, engineering_lead, risk_governance - whichever agent's work "
    "needs to change - followed by your reason.\nIf APPROVED, follow with a fenced ```json "
    "code block whose keys are objective, changed, verified, not_verified, risks, "
    "approval_needed (each a string or list of strings)."
)


def run_reviewer(db: Session, task: models.Task) -> models.Message:
    """in_review -> approved (+ receipt) | in_progress (rejected, bounced to an agent)."""
    _require_state(task, "in_review")
    agent = task_service.get_agent_by_role(db, "reviewer")
    try:
        reply = _run_or_block(
            db, task, agent, get_system_prompt("reviewer"), _build_context(db, task) + REVIEW_FORMAT_INSTRUCTION
        )
    except _Blocked as blocked:
        return blocked.message
    lines = reply.strip().splitlines()
    approved = bool(lines) and lines[0].strip().upper().startswith("VERDICT: APPROVED")

    if approved:
        task_service.apply_transition(db, task, "approved")
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
                decided_by=agent.id,
                decided_at=datetime.datetime.now(datetime.timezone.utc),
            )
        )
        message = task_service.post_message(
            db,
            task,
            schemas.MessageCreate(author_type="agent", author_id=agent.id, message_type="receipt", content=reply),
        )
    else:
        rejected_to_agent_id = None
        if len(lines) > 1 and lines[1].strip().upper().startswith("REJECTED_TO:"):
            role = lines[1].split(":", 1)[1].strip().lower()
            rejected_agent = db.query(models.Agent).filter(models.Agent.role == role).first()
            rejected_to_agent_id = rejected_agent.id if rejected_agent else None

        task_service.apply_transition(db, task, "in_progress")
        message = task_service.post_message(
            db,
            task,
            schemas.MessageCreate(
                author_type="agent",
                author_id=agent.id,
                message_type="critique",
                content=reply,
                rejected_to_agent_id=rejected_to_agent_id,
            ),
        )
        task.rejected_to_agent_id = rejected_to_agent_id
        task.pending_critique_message_id = message.id

    db.commit()
    db.refresh(message)
    return message
