"""Replays the real production finding from docs/real-run-log-v7.md: a task tiered
`prohibited` (an audit-log bypass for regulated accounts) reached the Reviewer with
Risk correctly holding that no sign-off can ever clear it - yet the Reviewer's only
available verdicts were APPROVED or REJECTED (bounce-for-revision), so it was forced
into VERDICT: APPROVED, landing the task in the terminal `approved` state indistinguishable
from a real green light, even though its own receipt said "no build... proceeds."

Confirms the fix: a third verdict, VERDICT: PROHIBITED, transitions the task to the
`rejected` state instead - a permanent closure distinct from both `approved` (cleared to
build) and the ordinary `in_progress` bounce-for-revision (an agent's specific work needs
to change). No receipt is generated, since nothing was approved.

Requires a running Postgres reachable via DATABASE_URL, with migrations 0001-0003 applied
and seed.py already run (for the 4 agents). No real Anthropic API call is made.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import models, orchestrator, task_service  # noqa: E402
from app.database import SessionLocal  # noqa: E402


class ProhibitedClosureTest(unittest.TestCase):
    def setUp(self):
        self.db = SessionLocal()
        agents = {a.role: a for a in self.db.query(models.Agent).all()}
        self.reviewer = agents.get("reviewer")
        if not self.reviewer:
            self.skipTest("seed.py has not been run - agents not found")

        self.task = models.Task(
            title="Audit-log bypass for regulated accounts (real HQ-107 replay)",
            state="in_review",
            policy_tier="prohibited",
        )
        self.db.add(self.task)
        self.db.flush()
        thread = models.Thread(task_id=self.task.id)
        self.db.add(thread)
        self.db.flush()
        self.task.thread_id = thread.id
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_prohibited_verdict_closes_to_rejected_not_approved(self):
        def fake_call_claude(system_prompt, user_content):
            return (
                "VERDICT: PROHIBITED\n\n"
                "This creates an unrecoverable audit-trail gap for regulated accounts; no sign-off "
                "can waive it into existence. The only way forward is a materially rescoped contract."
            )

        with mock.patch.object(orchestrator, "_call_claude", side_effect=fake_call_claude):
            message = orchestrator.run_reviewer(self.db, self.task)

        self.assertEqual(message.message_type, "critique")
        self.assertIsNone(message.rejected_to_agent_id, "no agent to bounce it back to - this isn't a revision")

        self.db.refresh(self.task)
        self.assertEqual(
            self.task.state,
            "rejected",
            "a prohibited closure must be distinguishable from both approved (cleared to build) "
            "and in_progress (bounced for revision)",
        )
        self.assertIsNone(self.task.rejected_to_agent_id)

        receipt = self.db.query(models.Receipt).filter(models.Receipt.task_id == self.task.id).first()
        self.assertIsNone(receipt, "nothing was approved - no receipt should be generated")

    def test_ordinary_rejected_verdict_still_bounces_to_in_progress(self):
        """Confirms adding the PROHIBITED branch didn't change the existing REJECTED
        (bounce-for-revision) behavior for a normal, non-prohibited rejection."""
        self.task.policy_tier = "auto"
        self.db.commit()

        agents = {a.role: a for a in self.db.query(models.Agent).all()}
        pm = agents["pm"]

        def fake_call_claude(system_prompt, user_content):
            return "VERDICT: REJECTED\nREJECTED_TO: pm\n\nacceptance criteria are unmeasurable as written"

        with mock.patch.object(orchestrator, "_call_claude", side_effect=fake_call_claude):
            message = orchestrator.run_reviewer(self.db, self.task)

        self.assertEqual(message.message_type, "critique")
        self.assertEqual(message.rejected_to_agent_id, pm.id)

        self.db.refresh(self.task)
        self.assertEqual(self.task.state, "in_progress")
        self.assertEqual(self.task.rejected_to_agent_id, pm.id)


if __name__ == "__main__":
    unittest.main()
