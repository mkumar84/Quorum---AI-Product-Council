# Quorum backend

FastAPI service implementing the schema, CRUD, task state machine, and Claude
API wiring from `../quorum-spec.pdf`.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env  # fill in DATABASE_URL and ANTHROPIC_API_KEY
psql "$DATABASE_URL" -f ../schema.sql
python seed.py         # 4 agents + sample feature requests
uvicorn app.main:app --reload
```

## Layout

- `app/models.py` / `app/schemas.py` — SQLAlchemy models and Pydantic schemas for the data model in the spec
- `app/state_machine.py` — valid task state transitions
- `app/routers/` — CRUD endpoints for agents, tasks, threads, messages, receipts, policy rules
- `app/prompts.py` — loads each agent's system prompt from `../agents/system-prompts.md`
- `app/orchestrator.py` — calls the Anthropic Messages API per agent role and applies the result to the task (contract fields, policy tier, state transitions, receipt)
- `app/routers/council.py` — endpoints that trigger one agent's turn on a task: `POST /tasks/{id}/agents/{pm|engineering|risk|reviewer}/run`

## Notes

- The PM and Reviewer agents are asked to prefix their reply with a
  machine-readable verdict line (`CONTRACT: READY`/`NEEDS_CLARIFICATION`,
  `VERDICT: APPROVED`/`REJECTED`) followed by a fenced JSON block, so the
  orchestrator can populate the task contract / receipt without a separate
  structured-output pass. This is a v1 convention, not part of the agents'
  system prompts themselves.
- `run_engineering_proposal` and `run_risk_assessment` both "claim" the task
  (`contracted -> in_progress`) and the task advances to `in_review` once
  both a proposal message and a policy tier exist, per the spec's state
  machine.
