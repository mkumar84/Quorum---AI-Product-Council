"""Loads the role-scoped system prompts from backend/agents/system-prompts.md.

Keeping the prompts in one markdown file (rather than duplicated into Python
strings) means editing an agent's brief never risks the code and the
human-readable draft drifting apart.
"""

import re
from functools import lru_cache
from pathlib import Path

# Resolved relative to this package's own location (app/ -> backend/ ->
# backend/agents/), not the repo root: Railway's Root Directory=/backend
# deploys only the backend/ subtree, so a path reaching above it (e.g. a
# sibling repo-root agents/ dir) is absent in production even though it
# resolves fine in local dev - this bit us with a FileNotFoundError there.
PROMPTS_PATH = Path(__file__).resolve().parent.parent / "agents" / "system-prompts.md"

ROLE_TO_HEADING = {
    "pm": "PM Agent",
    "engineering_lead": "Engineering Lead Agent",
    "risk_governance": "Risk/Governance Agent",
    "reviewer": "Reviewer Agent",
}


@lru_cache
def _sections() -> dict[str, str]:
    text = PROMPTS_PATH.read_text()
    parts = re.split(r"^## (.+)$", text, flags=re.MULTILINE)
    # parts = [preamble, heading1, body1, heading2, body2, ...]
    sections = {}
    for heading, body in zip(parts[1::2], parts[2::2]):
        sections[heading.strip()] = body.strip()
    return sections


def get_system_prompt(role: str) -> str:
    heading = ROLE_TO_HEADING.get(role)
    if heading is None:
        raise KeyError(f"unknown agent role: {role}")
    sections = _sections()
    if heading not in sections:
        raise KeyError(f"no system prompt section found for '{heading}' in {PROMPTS_PATH}")
    return sections[heading]
