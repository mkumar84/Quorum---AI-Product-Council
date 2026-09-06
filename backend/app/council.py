"""The trigger loop: after a task's state changes, look at what state it's in
now and call whichever agent's turn is next. Deliberately dumb - state in,
agent call out, no scheduler and no polling. Called synchronously right
after the state-changing action (posting a contract or any thread message),
using the same db session/transaction that action already committed with.

    contracted -> Engineering + Risk
    in_review  -> Reviewer

Each triggered agent call is its own self-contained transaction (see
orchestrator.py), so one agent failing doesn't undo another's already-saved
work - it's logged and the rest of the request proceeds normally. After
triggering, the resulting state is checked again so a full contracted ->
in_progress -> in_review -> approved/in_progress run completes in one call
without needing a second external event to fire the next step.
"""

from sqlalchemy.orm import Session

from . import models, orchestrator

MAX_DEPTH = 5  # the state machine has no cycles besides reject -> in_progress, which no
# rule here re-triggers automatically; this just keeps the recursion honest.


def _run_and_log(run_fn, db: Session, task: models.Task) -> None:
    try:
        run_fn(db, task)
    except Exception as exc:  # an agent's turn failing must not break the request that triggered it
        print(f"[council] {run_fn.__name__} failed for task {task.id} (state={task.state}): {exc}")


def on_task_updated(db: Session, task: models.Task, _depth: int = 0) -> None:
    if _depth >= MAX_DEPTH:
        return

    if task.state == "contracted":
        _run_and_log(orchestrator.run_engineering, db, task)
        _run_and_log(orchestrator.run_risk, db, task)
        on_task_updated(db, task, _depth + 1)
    elif task.state == "in_review":
        _run_and_log(orchestrator.run_reviewer, db, task)
        on_task_updated(db, task, _depth + 1)
