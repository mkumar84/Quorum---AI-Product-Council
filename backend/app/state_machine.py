"""Task state machine (build spec section 2).

proposed -> contracted -> in_progress -> in_review -> approved
                                              \\-> in_progress (Reviewer rejected, sent back for revision)
                                              \\-> rejected (Reviewer found the contract PROHIBITED as
                                                  scoped - permanently closed, no revision path; see
                                                  orchestrator.run_reviewer)
any state -> blocked (escalation condition met, needs human)

'rejected' is a genuine resting state, but only for a `prohibited`-tier closure: the
work as scoped can never be approved (no sign-off can waive it), so there's no agent
to bounce it back to for a revision - only a materially different contract (a new
task) could ever proceed. An ordinary Reviewer rejection (missing approval, unmet
acceptance criteria, etc.) still goes straight back to in_progress instead of parking
in 'rejected' - the bounce is recorded on the message (rejected_to_agent_id + reason),
not as a resting task state. Keeping these distinct matters: conflating a permanent
`prohibited` closure with `approved` would make task.state alone an unreliable signal
of whether something is actually cleared to build.
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
    "in_review": {"approved", "in_progress", "rejected", "blocked"},
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
