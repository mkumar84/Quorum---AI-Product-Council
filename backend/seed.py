"""Seeds the 4 council agents and 3 intake requests, uncontracted.

Usage: python seed.py
"""

from app.database import SessionLocal
from app.models import Agent, Task, Thread

AGENTS = [
    {"name": "PM Agent", "role": "pm"},
    {"name": "Engineering Lead Agent", "role": "engineering_lead"},
    {"name": "Risk/Governance Agent", "role": "risk_governance"},
    {"name": "Reviewer Agent", "role": "reviewer"},
]

SAMPLE_REQUESTS = [
    "Support team has asked for a CSV export button on the Customer Reports dashboard. "
    "Should cover the three standard reports (usage, billing, activity log) and export "
    "exactly what's shown on screen with the user's current filters applied — not the "
    "full unfiltered dataset. No new permissions needed, this uses existing report-read "
    "access.",
    "Marketing wants a banner on the billing dashboard promoting the new reporting "
    "suite's Q3 launch, targeting logged-in admins only, not end users. The date isn't "
    "finalized with Engineering yet — this request came off a marketing calendar, not a "
    "confirmed ship date — so the banner copy needs to say \"coming this quarter\" "
    "rather than a specific date until Engineering signs off. No design assets exist "
    "yet; this is asking for the banner slot and copy, not final visuals.",
    "Support leadership has asked for a way for support agents to impersonate a "
    "customer account when debugging tickets that can't be reproduced from account "
    "data alone. Access should be read/view-only — no submitting forms, changing "
    "settings, or completing transactions as the customer — and every session must be "
    "time-limited (auto-expire after 15 minutes) and fully audit-logged against the "
    "ticket ID it's tied to. Requires the customer's consent flag to already be on "
    "file before an agent can start a session.",
]


def seed() -> None:
    db = SessionLocal()
    try:
        for agent_data in AGENTS:
            existing = db.query(Agent).filter(Agent.role == agent_data["role"]).first()
            if not existing:
                db.add(Agent(**agent_data))
        db.commit()

        if db.query(Task).count() == 0:
            for title in SAMPLE_REQUESTS:
                task = Task(title=title)
                db.add(task)
                db.flush()
                thread = Thread(task_id=task.id)
                db.add(thread)
                db.flush()
                task.thread_id = thread.id
            db.commit()

        agents = db.query(Agent).all()
        tasks = db.query(Task).all()
        print(f"Seeded {len(agents)} agents and {len(tasks)} tasks (all 'proposed', no contracts).")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
