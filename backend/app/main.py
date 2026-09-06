from fastapi import FastAPI

from .routers import agents, policy_rules, tasks

app = FastAPI(title="Quorum — AI Product Council")

app.include_router(agents.router)
app.include_router(tasks.router)
app.include_router(policy_rules.router)


@app.get("/health")
def health():
    return {"status": "ok"}
