from fastapi import FastAPI

from .routers import agents, council, policy_rules, receipts, tasks, threads

app = FastAPI(title="Quorum — AI Product Council")

app.include_router(agents.router)
app.include_router(tasks.router)
app.include_router(threads.router)
app.include_router(receipts.router)
app.include_router(policy_rules.router)
app.include_router(council.router)


@app.get("/health")
def health():
    return {"status": "ok"}
