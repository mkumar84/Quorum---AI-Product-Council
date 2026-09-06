"""Task state machine (build spec section 2).

proposed -> contracted -> in_progress -> in_review -> approved
                                              \\-> rejected -> in_progress
any state -> blocked (escalation condition met, needs human)
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
    "in_review": {"approved", "rejected", "blocked"},
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
