# Quorum backend

FastAPI service implementing the schema, CRUD, and task state machine from
`quorum-spec.pdf`. Claude API wiring is deferred to a second pass — every
endpoint that would normally be an agent's turn takes a manually-typed
payload instead (see `app/prompts.py` for the system-prompt loader that the
next pass will call into).

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env  # fill in DATABASE_URL
psql "$DATABASE_URL" -f migrations/0001_initial_schema.sql
python seed.py         # 4 agents + 3 raw feature requests, no contracts yet
uvicorn app.main:app --reload
```

## Layout

- `migrations/0001_initial_schema.sql` — agents, tasks, threads, messages, receipts, policy_rules
- `app/models.py` / `app/schemas.py` — SQLAlchemy models and Pydantic schemas
- `app/state_machine.py` — valid task state transitions, enforced in the router
- `app/routers/tasks.py` — the task lifecycle endpoints (see below)
- `app/routers/agents.py`, `app/routers/policy_rules.py` — plain CRUD
- `app/prompts.py` — loads each agent's system prompt from `../agents/system-prompts.md` (not yet wired to an endpoint)

## Task lifecycle endpoints

| Endpoint | Transition | Notes |
|---|---|---|
| `POST /tasks` | — → `proposed` | body: `{title}` — a raw feature request, no contract |
| `POST /tasks/{id}/contract` | `proposed` → `contracted` | stands in for the PM agent; body: `{pm_agent_id, objective, scope, constraints, acceptance_criteria}` |
| `POST /tasks/{id}/claim` | `contracted` → `in_progress` | stands in for Engineering/Risk; body: `{agent_id}`. A second claim on an already-`in_progress` task is a no-op, since both agents claim in parallel |
| `POST /tasks/{id}/messages` | none | post any thread message: `{author_type, author_id, message_type, content, rejected_to_agent_id?}` |
| `POST /tasks/{id}/review` | `in_review` → `approved` or → `in_progress` | stands in for the Reviewer. `verdict: "approve"` builds the receipt from the payload; `verdict: "reject"` requires `rejected_to_agent_id` and `reason` (422 if missing) and writes them onto the critique message so the frontend can show exactly who it bounced back to |
| `GET /tasks/{id}` | — | task + full thread history + receipt (if approved) |
| `GET /tasks?state=` | — | filtered list for the board view |

Every transition is validated against `app/state_machine.py` before it's
applied — e.g. calling `/review` on a task still in `proposed` returns `409`,
not a silently-accepted state change. Rejection does not park the task in a
resting `rejected` state; it goes straight back to `in_progress`, with the
bounce recorded on the message.

There is currently no endpoint to move a task to `blocked` (the escalation
state) — not in this pass's scope; add one when the human-escalation flow is
built.
