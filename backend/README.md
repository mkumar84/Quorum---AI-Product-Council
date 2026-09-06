# Quorum backend

FastAPI service implementing the schema, CRUD, task state machine, and
Claude API wiring from `quorum-spec.pdf`. Every task-lifecycle transition can
now happen either via a manually-typed payload (for testing/debugging) or by
an actual Claude call through `orchestrator.py`.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env  # fill in DATABASE_URL and ANTHROPIC_API_KEY
psql "$DATABASE_URL" -f migrations/0001_initial_schema.sql
python seed.py         # 4 agents + 3 raw feature requests, no contracts yet
uvicorn app.main:app --reload
```

## Layout

- `migrations/0001_initial_schema.sql` — agents, tasks, threads, messages, receipts, policy_rules
- `app/models.py` / `app/schemas.py` — SQLAlchemy models and Pydantic schemas
- `app/state_machine.py` — valid task state transitions
- `app/task_service.py` — the actual lifecycle logic (transitions, message posting, contract/review application), shared by the routers, the orchestrator, and council so a human's manual call and an agent's turn go through the identical, state-machine-enforced code path
- `app/prompts.py` — loads each agent's system prompt from `../agents/system-prompts.md`
- `app/orchestrator.py` — one function per role (`run_pm`, `run_engineering`, `run_risk`, `run_reviewer`): loads that role's prompt, pulls the task + thread history, calls Claude, applies the result via `task_service`. Each call is one self-contained transaction (a single `db.commit()`)
- `app/council.py` — the state-driven trigger loop: after a task update, checks its state and calls whichever agent's turn is next (`contracted` → Engineering + Risk, `in_review` → Reviewer), then rechecks so a full cascade completes in one call. No scheduler, no polling — just direct function calls off the resulting state, logging (not raising) if one agent's turn fails so the rest of the cascade and the triggering request still succeed
- `app/routers/tasks.py` — the task lifecycle endpoints (see below)
- `app/routers/agents.py`, `app/routers/policy_rules.py` — plain CRUD

## Task lifecycle endpoints

| Endpoint | Transition | Notes |
|---|---|---|
| `POST /tasks` | — → `proposed` | body: `{title}` — a raw feature request, no contract |
| `POST /tasks/{id}/contract` | `proposed` → `contracted` | manually-typed contract; body: `{pm_agent_id, objective, scope, constraints, acceptance_criteria}`. Triggers the council cascade afterward |
| `POST /tasks/{id}/claim` | `contracted` → `in_progress` | manual claim; body: `{agent_id}`. A second claim on an already-`in_progress` task is a no-op, since both agents claim in parallel |
| `POST /tasks/{id}/messages` | none directly, but may advance `in_progress` → `in_review` | post any thread message: `{author_type, author_id, message_type, content, rejected_to_agent_id?}`. Triggers the council cascade afterward |
| `POST /tasks/{id}/review` | `in_review` → `approved` or → `in_progress` | manual reviewer verdict. `verdict: "approve"` builds the receipt from the payload; `verdict: "reject"` requires `rejected_to_agent_id` and `reason` (422 if missing) and writes them onto the critique message |
| `POST /tasks/{id}/run` | whatever that role's turn implies | body: `{role: "pm"\|"engineering"\|"risk"\|"reviewer"}` — manually trigger **one** agent's real Claude turn, in isolation from the council cascade. For debugging a single agent's output before trusting the automatic chain |
| `GET /tasks/{id}` | — | task + full thread history + receipt (if approved) |
| `GET /tasks?state=` | — | filtered list for the board view |

Every transition is validated against `app/state_machine.py` before it's
applied — e.g. calling `/review` on a task still in `proposed` returns `409`.
Rejection does not park the task in a resting `rejected` state; it goes
straight back to `in_progress`, with the bounce (`rejected_to_agent_id` +
the model's actual reason text) recorded on the critique message.

`in_progress` → `in_review` is gated on `task.policy_tier` being set (by
Risk) plus a `proposal` message existing (from Engineering) — not on the
generic presence of a `decision`-typed message, since a message's type is
just a label anyone, including a human, can post.

There is currently no endpoint to move a task to `blocked` (the escalation
state) — not in this pass's scope; add one when the human-escalation flow is
built.

## How an agent's turn differs from a manual call

`task_service.py` holds the actual state-changing logic. The manual
endpoints (`/contract`, `/review`) call it with a payload typed by a human.
`orchestrator.py`'s `run_*` functions call the *same* primitives
(`apply_transition`, `post_message`, `claim`, `advance_to_review_if_ready`)
with a payload built from Claude's reply instead — so there's exactly one
code path enforcing the state machine, not two that could drift apart.

Since Claude's replies are free text, each role is asked to prefix its
answer with a machine-readable line the orchestrator parses before falling
through to the same primitives:

- PM: `CONTRACT: READY` / `CONTRACT: NEEDS_CLARIFICATION`, then a ```json block with the contract fields
- Risk: `TIER: auto` / `approval_required` / `prohibited`
- Reviewer: `VERDICT: APPROVED` (+ a ```json receipt block) / `VERDICT: REJECTED` with a second line `REJECTED_TO: <role>` naming which agent's work needs to change

The full Claude reply (including that header line) is still stored as the
message content, so the thread shows the model's real reasoning, not just
the parsed verdict.

## Testing without a real Anthropic API key

This was built and tested in a sandbox with no `ANTHROPIC_API_KEY`. Two
things were verified there and are worth re-running once a real key exists:

1. An in-process test with `orchestrator._call_claude` monkeypatched to
   scripted replies, driving one seeded task through PM → Engineering/Risk →
   Reviewer-rejects → Engineering-revises → Reviewer-approves, asserting the
   rejection's `rejected_to_agent_id` matches the real agent row and the
   receipt is generated correctly.
2. The same flow over real HTTP, with `ANTHROPIC_BASE_URL` pointed at a
   throwaway local stub that returns Messages-API-shaped responses, to
   exercise the actual `anthropic` SDK request/response path (not just the
   business logic) — including confirming `/run` stays isolated from the
   council cascade while `/contract` and `/messages` trigger it.

Neither replaces running it against the real API — do that before trusting
the prompts' actual output quality, not just the wiring.
