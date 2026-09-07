"""Task state machine (build spec section 2).

proposed -> contracted -> in_progress -> in_review -> approved
                                              \\-> in_progress (Reviewer rejected, sent back)
any state -> blocked (escalation condition met, needs human)

'rejected' is kept as a valid task_state (per the schema) but the /review
endpoint sends a rejected task straight back to in_progress rather than
parking it in 'rejected' — the bounce is recorded on the message
(rejected_to_agent_id + reason), not as a resting task state.
"""

ALL_STATES = {
    "proposed",
    "contracted",
    "in_progress",
    "in_review",
    "approved",
    "rejected",
    "blocked",
}

TERMINAL_STATES = {"approved"}

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "proposed": {"contracted", "blocked"},
    "contracted": {"in_progress", "blocked"},
    "in_progress": {"in_review", "blocked"},
    "in_review": {"approved", "in_progress", "blocked"},
    "rejected": {"in_progress", "blocked"},
    "blocked": {"proposed", "contracted", "in_progress", "in_review", "rejected"},
    "approved": set(),
}


class InvalidTransition(ValueError):
    pass


def validate_transition(from_state: str, to_state: str) -> None:
    if to_state not in ALL_STATES:
        raise InvalidTransition(f"'{to_state}' is not a known task state")
    if to_state not in ALLOWED_TRANSITIONS.get(from_state, set()):
        raise InvalidTransition(f"cannot transition task from '{from_state}' to '{to_state}'")
