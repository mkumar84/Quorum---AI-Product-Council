"""The trigger loop: after a task's state changes, look at what state it's in
now and call whichever agent's turn is next. Deliberately dumb - state in,
agent call out, no scheduler and no polling. Called synchronously right
after the state-changing action (posting a contract or any thread message),
using the same db session/transaction that action already committed with.

    contracted -> Engineering + Risk
    in_review  -> Reviewer

Each triggered agent call is its own self-contained transaction (see
orchestrator.py). A single Claude call failing is handled inside
orchestrator.py itself (retried, then the task is blocked and logged) - it
never raises out to here. _run_and_log is a second safety net for anything
else unexpected (e.g. a state-validation error), so one agent's turn failing
still can't undo another's already-saved work or break the request that
triggered it.

After triggering, the resulting state is checked again so a full contracted
-> in_progress -> in_review -> approved/in_progress run completes in one
call without needing a second external event to fire the next step.
"""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from . import models, orchestrator, schemas, task_service

MAX_DEPTH = 5  # the state machine has no cycles besides reject -> in_progress, which no
# rule here re-triggers automatically, and a failed agent call now blocks rather than
# looping back to the same state - so this is unreachable under normal operation. Kept
# as a defensive breaker: if it ever does trip, that's a bug elsewhere, and the correct
# response is still to block and log, not spin or crash.


def _run_and_log(run_fn, db: Session, task: models.Task) -> None:
    try:
        run_fn(db, task)
    except Exception as exc:  # an agent's turn failing must not break the request that triggered it
        print(f"[council] {run_fn.__name__} failed for task {task.id} (state={task.state}): {exc}")


def _block_on_cascade_limit(db: Session, task: models.Task) -> None:
    task_service.post_message(
        db,
        task,
        schemas.MessageCreate(
            author_type="agent",
            author_id=None,
            message_type="system_error",
            content=(
                f"[cascade-depth-exceeded] council's automatic cascade recursed {MAX_DEPTH} "
                f"times on this task without settling into a resting state (approved, or a "
                f"state no council rule re-triggers) - stopping rather than looping further. "
                f"This shouldn't happen under normal operation; treat it as a bug report."
            ),
        ),
    )
    try:
        task_service.apply_transition(db, task, "blocked")
    except HTTPException:
        pass  # e.g. task is already in a terminal state - nothing to block, message still stands
    db.commit()
    print(f"[council] task {task.id} blocked: exceeded max cascade depth ({MAX_DEPTH})")


def on_task_updated(db: Session, task: models.Task, _depth: int = 0) -> None:
    if _depth >= MAX_DEPTH:
        _block_on_cascade_limit(db, task)
        return

    if task.state == "contracted":
        _run_and_log(orchestrator.run_engineering, db, task)
        _run_and_log(orchestrator.run_risk, db, task)
        on_task_updated(db, task, _depth + 1)
    elif task.state == "in_review":
        _run_and_log(orchestrator.run_reviewer, db, task)
        on_task_updated(db, task, _depth + 1)
