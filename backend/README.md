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
psql "$DATABASE_URL" -f migrations/0002_add_system_error_message_type.sql
psql "$DATABASE_URL" -f migrations/0003_add_resolution_tracking.sql
python seed.py         # 4 agents + 3 intake requests, no contracts yet
uvicorn app.main:app --reload
```

## Deploying to Railway

1. **New project → Deploy from GitHub repo**, pick this repo.
2. **Set the service's Root Directory to `backend`** (Settings → Root Directory) — the app, `requirements.txt`, `Procfile`, and `railway.json` all live there, not at the repo root.
3. **Add a Postgres plugin** (New → Database → PostgreSQL) to the project. Railway injects `DATABASE_URL` into the web service automatically; `app/database.py` normalizes Railway's `postgres://`/`postgresql://` scheme to `postgresql+psycopg://` itself, so no manual edit is needed. (Uses `psycopg[binary]` — psycopg 3, not `psycopg2-binary`, which fails to build on Railway's Nixpacks image: it has no prebuilt wheel there and no `libpq-dev` to compile against.)
4. **Set environment variables** on the web service: `ANTHROPIC_API_KEY` (required for any endpoint that calls Claude), optionally `ANTHROPIC_MODEL` (defaults to `claude-sonnet-5`) and `CORS_ALLOWED_ORIGINS` (comma-separated list; defaults to `*` — tighten this once the frontend's real domain exists).
5. **Run the migrations once** against the provisioned database, in order, before the first request that touches the DB — Railway's Postgres plugin isn't auto-migrated. From the Railway CLI, linked to the project: `railway run psql "$DATABASE_URL" -f migrations/0001_initial_schema.sql`, then `...0002...`, then `...0003...` (each is idempotent-ish but not designed to be re-run after the first apply — this is a "weekend v1" raw-SQL migration set, not a tracked migration framework, so re-running an already-applied file will error on things like `CREATE TABLE`). Optionally follow with `railway run python seed.py` to seed the 4 agents + sample tasks.
6. Deploy. Railway builds via Nixpacks (auto-detected from `requirements.txt`) and starts the service with the command in `Procfile`/`railway.json`: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. The public URL appears under the service's **Settings → Networking → Public Networking** (Railway doesn't expose a public URL by default — generate one there if it isn't already).
7. Confirm with `curl https://<your-railway-domain>/health` → `{"status": "ok"}`.

I can't perform these steps myself — no Railway CLI or account access is available in this environment — but everything in the repo needed for the deploy to work (`Procfile`, `railway.json`, the `DATABASE_URL` normalization, CORS) is in place.

## Layout

- `migrations/0001_initial_schema.sql` — agents, tasks, threads, messages, receipts, policy_rules
- `migrations/0002_add_system_error_message_type.sql` — adds `system_error` to `message_type`, for automated blocking notices
- `migrations/0003_add_resolution_tracking.sql` — adds `messages.resolves_message_id` and `tasks.rejected_to_agent_id`/`pending_critique_message_id`, so a rejection can only be cleared by a message that actually links to it (see below)
- `app/models.py` / `app/schemas.py` — SQLAlchemy models and Pydantic schemas
- `app/state_machine.py` — valid task state transitions
- `app/task_service.py` — the actual lifecycle logic (transitions, message posting, contract/review application), shared by the routers, the orchestrator, and council so a human's manual call and an agent's turn go through the identical, state-machine-enforced code path
- `app/prompts.py` — loads each agent's system prompt from `agents/system-prompts.md` (inside `backend/`, so it ships with Railway's `Root Directory=/backend` deploy)
- `app/orchestrator.py` — one function per role (`run_pm`, `run_engineering`, `run_risk`, `run_reviewer`): loads that role's prompt, pulls the task + thread history, calls Claude, applies the result via `task_service`. Each call is one self-contained transaction (a single `db.commit()`)
- `app/council.py` — the state-driven trigger loop: after a task update, checks its state and calls whichever agent's turn is next (`contracted` → Engineering + Risk, `in_review` → Reviewer), then rechecks so a full cascade completes in one call. No scheduler, no polling — just direct function calls off the resulting state, logging (not raising) if one agent's turn fails so the rest of the cascade and the triggering request still succeed
- `app/routers/tasks.py` — the task lifecycle endpoints (see below)
- `app/routers/agents.py`, `app/routers/policy_rules.py` — plain CRUD
- `Procfile`, `railway.json` — Railway deploy config (see below)

## Task lifecycle endpoints

| Endpoint | Transition | Notes |
|---|---|---|
| `POST /tasks` | — → `proposed` | body: `{title}` — a raw feature request, no contract |
| `POST /tasks/{id}/contract` | `proposed` → `contracted` | manually-typed contract; body: `{pm_agent_id, objective, scope, constraints, acceptance_criteria}`. Triggers the council cascade afterward |
| `POST /tasks/{id}/claim` | `contracted` → `in_progress` | manual claim; body: `{agent_id}`. A second claim on an already-`in_progress` task is a no-op, since both agents claim in parallel |
| `POST /tasks/{id}/messages` | none directly, but may advance `in_progress` → `in_review` | post any thread message: `{author_type, author_id, message_type, content, rejected_to_agent_id?, resolves_message_id?}`. **422 if the task has an outstanding rejection and `resolves_message_id` doesn't point at the critique that caused it** (see below). Triggers the council cascade afterward |
| `POST /tasks/{id}/review` | `in_review` → `approved` or → `in_progress` | manual reviewer verdict. `verdict: "approve"` builds the receipt from the payload; `verdict: "reject"` requires `rejected_to_agent_id` and `reason` (422 if missing) and writes them onto the critique message |
| `POST /tasks/{id}/run` | whatever that role's turn implies | body: `{role: "pm"\|"engineering"\|"risk"\|"reviewer"}` — manually trigger **one** agent's real Claude turn, in isolation from the council cascade. For debugging a single agent's output before trusting the automatic chain |
| `GET /tasks/{id}` | — | task + full thread history + receipt (if approved) |
| `GET /tasks?state=` | — | filtered list for the board view |

Every transition is validated against `app/state_machine.py` before it's
applied — e.g. calling `/review` on a task still in `proposed` returns `409`.
Rejection does not park the task in a resting `rejected` state; it goes
straight back to `in_progress`, with the bounce (`rejected_to_agent_id` +
the model's actual reason text) recorded on the critique message.

There is currently no endpoint to move a task to `blocked` directly — it's
only reached automatically, by an agent's Claude call failing (see below) or
council's cascade-depth breaker tripping. Add a manual endpoint when the
human-escalation flow (reviewing and unblocking) is built.

## Resolution-linked revisions

`docs/real-run-log-v3.md` found a real gap: `in_progress → in_review` used to
fire on the generic presence of a `proposal` + a `policy_tier`, which meant
*any* message posted while a rejection was outstanding — from anyone, about
anything — silently re-opened review with the actual defect untouched. Worse,
PM could never be re-invoked at all once a task had a contract, so a
PM-targeted rejection was a dead end.

Fixed by tracking the rejection explicitly, not inferring it from message
types:

- When the Reviewer rejects, `task.rejected_to_agent_id` and
  `task.pending_critique_message_id` are set to the target agent and the
  critique message that caused the rejection (both `apply_review` and
  `orchestrator.run_reviewer` do this).
- While `task.rejected_to_agent_id` is set, **every** `post_message` call —
  from a `run_*` function or a human via the API — must set
  `resolves_message_id` to exactly `task.pending_critique_message_id`, or
  it's rejected with `422`. A message can't silently advance the task
  without deliberately naming the critique it's answering.
- `advance_to_review_if_ready` no longer gates on type-presence once a
  rejection is outstanding. It looks for a message that (a) resolves the
  right critique, (b) comes from the agent it was rejected to
  (`author_id == task.rejected_to_agent_id`), and (c) is that role's real
  output type (`contract` for PM, `proposal` for Engineering, `decision`
  for Risk — a clarifying question doesn't count, even if linked). Only
  then does it clear the rejection and advance. The very first pass through
  `in_progress` (no rejection yet) still uses the original "Engineering has
  proposed and Risk has a tier" gate — there's no critique to link to yet.
- `run_pm` no longer hard-requires `state == "proposed"`. It accepts
  `("proposed", "in_progress")`, same pattern as Engineering and Risk, so a
  PM-targeted rejection has a real revision path for the first time. Its
  contract-fields update and `proposed → contracted` transition only fire on
  the first pass; a revision leaves `state` alone and lets
  `advance_to_review_if_ready` decide.

`tests/test_rejection_routing.py` replays task 1's exact scenario from
`real-run-log-v3.md` (needs `DATABASE_URL` pointed at a migrated + seeded
Postgres, no `ANTHROPIC_API_KEY` needed — Claude calls are monkeypatched):
posting the literal unrelated message from that log (`"just checking in on
this one"`) is now rejected with `422` and leaves the task untouched; a
correctly-linked PM revision advances it to `in_review` and clears the
rejection; and a PM clarifying question that reuses the same
`resolves_message_id` does *not* count as a resolution, since it isn't a
`contract`-type message.

## Agent-call retries and blocking on failure

Each `run_*` function's Claude call goes through `_call_claude_with_retries`:
up to `MAX_CLAUDE_RETRIES` (2) retries with exponential backoff
(`RETRY_BACKOFF_SECONDS` = `[1, 4]`) — 3 attempts total, not unbounded. If
every attempt fails, the task doesn't crash or dangle: a `system_error`
message tagged `[agent-call-failed]` (naming the role and the underlying
error) is posted to the thread, and the task transitions to `blocked` — a
handled outcome each `run_*` function returns normally from, not an
exception council or the `/run` endpoint has to catch.

`council.py`'s cascade-depth breaker (`MAX_DEPTH`, a defensive guard against
a reject/revise loop that never settles — unreachable in normal operation
now that a failed agent call blocks rather than looping) does the same:
`system_error` tagged `[cascade-depth-exceeded]`, then blocked. One state,
two possible causes, both greppable in the thread by their tag.

`tests/test_orchestrator_retry.py` (`python -m unittest
tests.test_orchestrator_retry`, needs `DATABASE_URL` pointed at a migrated +
seeded Postgres, no `ANTHROPIC_API_KEY` needed) monkeypatches `_call_claude`
to always raise and asserts: exactly 3 attempts, the `[1, 4]` backoff
schedule, the task ends up `blocked`, exactly one `system_error` message
exists, and — the actual point of the test — `council.on_task_updated`
itself never raises, even though the agent call underneath it never
succeeds.

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
