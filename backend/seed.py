"""Seeds the 4 council agents and a few sample feature requests (build spec section 6, step 2).

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
    "Let customers export their reports to CSV.",
    "Add a banner promising a Q3 launch date for the new billing dashboard.",
    "Write comparison copy for the pricing page against our top two competitors.",
    "Let support agents impersonate a customer account to debug issues.",
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
        print(f"Seeded {len(agents)} agents and {len(tasks)} tasks.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
