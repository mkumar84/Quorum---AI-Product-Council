"""Replays task 1's exact scenario from docs/real-run-log-v3.md: a task
rejected back to PM, where (a) an unrelated message falsely re-opened
review with the contract's ambiguity untouched, and (b) PM could never be
re-invoked at all (run_pm hard-required state == 'proposed'). Confirms the
resolution-linking fix (messages.resolves_message_id + tasks.
rejected_to_agent_id/pending_critique_message_id) closes both.

Requires a running Postgres reachable via DATABASE_URL, with migrations
0001-0003 applied and seed.py already run (for the 4 agents). No real
Anthropic API call is made - orchestrator._call_claude is monkeypatched.
"""

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import HTTPException  # noqa: E402

from app import models, orchestrator, schemas, task_service  # noqa: E402
from app.database import SessionLocal  # noqa: E402


class RejectionRoutingTest(unittest.TestCase):
    def setUp(self):
        self.db = SessionLocal()
        agents = {a.role: a for a in self.db.query(models.Agent).all()}
        self.pm = agents.get("pm")
        self.engineering = agents.get("engineering_lead")
        self.risk = agents.get("risk_governance")
        self.reviewer = agents.get("reviewer")
        if not all([self.pm, self.engineering, self.risk, self.reviewer]):
            self.skipTest("seed.py has not been run - agents not found")

        # Recreate task 1's exact position: in_progress, proposal + tier
        # already posted, then rejected back to PM over a real ambiguity.
        self.task = models.Task(
            title="CSV export pagination ambiguity",
            objective="Export matches what's shown on screen (ambiguous: loaded page vs full filtered set)",
            state="in_progress",
            policy_tier="auto",
        )
        self.db.add(self.task)
        self.db.flush()
        thread = models.Thread(task_id=self.task.id)
        self.db.add(thread)
        self.db.flush()
        self.task.thread_id = thread.id
        self.db.commit()

        task_service.post_message(
            self.db,
            self.task,
            schemas.MessageCreate(
                author_type="agent", author_id=self.engineering.id, message_type="proposal",
                content="proposal flagging the pagination ambiguity, not resolving it",
            ),
        )
        task_service.post_message(
            self.db,
            self.task,
            schemas.MessageCreate(
                author_type="agent", author_id=self.risk.id, message_type="decision", content="TIER: auto",
            ),
        )
        self.db.commit()

        self.critique = task_service.post_message(
            self.db,
            self.task,
            schemas.MessageCreate(
                author_type="agent",
                author_id=self.reviewer.id,
                message_type="critique",
                content="VERDICT: REJECTED\nREJECTED_TO: pm\n\npagination ambiguity blocks acceptance criteria",
                rejected_to_agent_id=self.pm.id,
            ),
        )
        self.task.rejected_to_agent_id = self.pm.id
        self.task.pending_critique_message_id = self.critique.id
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_unrelated_message_is_rejected_and_does_not_advance(self):
        """The exact real-run-log-v3.md repro: posting 'just checking in on this
        one' used to silently re-open review with nothing fixed. It must now be
        refused outright."""
        with self.assertRaises(HTTPException) as ctx:
            task_service.post_message(
                self.db,
                self.task,
                schemas.MessageCreate(
                    author_type="human", message_type="critique", content="just checking in on this one"
                ),
            )
        self.assertEqual(ctx.exception.status_code, 422)

        self.db.refresh(self.task)
        self.assertEqual(self.task.state, "in_progress")
        self.assertEqual(self.task.rejected_to_agent_id, self.pm.id)
        self.assertIn("ambiguous", self.task.objective)

    def test_message_pointing_at_the_wrong_critique_is_rejected(self):
        """A resolves_message_id naming some other real message - not the
        critique that actually caused the current rejection - is a 'stale/wrong
        critique' pointer and must be rejected exactly like a missing one."""
        with self.assertRaises(HTTPException) as ctx:
            task_service.post_message(
                self.db,
                self.task,
                schemas.MessageCreate(
                    author_type="agent",
                    author_id=self.pm.id,
                    message_type="contract",
                    content="revision, but pointing at the wrong prior message",
                    resolves_message_id=self.task.thread_id,  # a real UUID, just not the right one
                ),
            )
        self.assertEqual(ctx.exception.status_code, 422)

        self.db.refresh(self.task)
        self.assertEqual(self.task.state, "in_progress")
        self.assertEqual(self.task.rejected_to_agent_id, self.pm.id)

    def test_real_pm_revision_with_correct_resolves_id_advances_to_in_review(self):
        """PM can now be re-invoked (state == 'in_progress' is allowed), and its
        revised, correctly-linked contract is what actually clears the rejection."""

        def fake_call_claude(system_prompt, user_content):
            payload = {
                "objective": (
                    "Export reflects only the currently loaded/rendered rows per report page, "
                    "not the full filtered result set, for all three reports"
                ),
                "scope": [],
                "constraints": [],
                "acceptance_criteria": [
                    "Exported rows match exactly what is currently loaded on screen, "
                    "page-by-page, not the full server-side filtered set"
                ],
            }
            return "CONTRACT: READY\n```json\n" + json.dumps(payload) + "\n```"

        with mock.patch.object(orchestrator, "_call_claude", side_effect=fake_call_claude):
            message = orchestrator.run_pm(self.db, self.task)

        self.assertEqual(message.message_type, "contract")
        self.assertEqual(message.resolves_message_id, self.critique.id)
        self.assertEqual(message.author_id, self.pm.id)

        self.db.refresh(self.task)
        self.assertEqual(self.task.state, "in_review")
        self.assertIsNone(self.task.rejected_to_agent_id)
        self.assertIsNone(self.task.pending_critique_message_id)
        self.assertIn("loaded/rendered rows", self.task.objective)

    def test_pm_clarifying_question_alone_does_not_resolve_the_rejection(self):
        """A second PM 'critique' (still needs clarification) links to the same
        critique via resolves_message_id but is not PM's real output type
        (contract) - it must not be mistaken for a resolution."""

        def fake_call_claude(system_prompt, user_content):
            return "CONTRACT: NEEDS_CLARIFICATION\n\nstill unclear which reading you want"

        with mock.patch.object(orchestrator, "_call_claude", side_effect=fake_call_claude):
            message = orchestrator.run_pm(self.db, self.task)

        self.assertEqual(message.message_type, "critique")
        self.assertEqual(message.resolves_message_id, self.critique.id)

        self.db.refresh(self.task)
        self.assertEqual(self.task.state, "in_progress", "a clarifying question must not resolve the rejection")
        self.assertEqual(self.task.rejected_to_agent_id, self.pm.id)


if __name__ == "__main__":
    unittest.main()
