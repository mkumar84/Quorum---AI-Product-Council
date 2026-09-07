import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import agents, policy_rules, tasks

app = FastAPI(title="Quorum — AI Product Council")

# Comma-separated list of allowed origins, e.g. "https://my-frontend.lovable.app".
# Defaults to "*" (weekend-v1: no frontend origin is known yet) - tighten this
# once the Lovable frontend's real domain exists.
_allowed_origins = os.environ.get("CORS_ALLOWED_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _allowed_origins == "*" else _allowed_origins.split(","),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agents.router)
app.include_router(tasks.router)
app.include_router(policy_rules.router)


@app.get("/health")
def health():
    return {"status": "ok"}
