"""Replays HQ-102's real thread (the CSV export task - docs/real-run-log,
the live production run): contract #1 was tiered 'auto' at #3, Reviewer
rejected at #4 over an unmeasurable acceptance criterion, and PM's amended
contract at #7 changed the acceptance criteria substantively - yet sailed
straight back into in_review via the rejection-resolution path, letting the
Reviewer generate the receipt at #8 on the strength of a tier decision made
against the *original* contract text, which Risk never re-checked against
the amendment.

Confirms the fix: post_message resets task.policy_tier whenever a new
'contract' message lands on an already-tiered task, and
advance_to_review_if_ready now honors that reset on both paths (first-time
tiering and rejection-resolution alike), so Risk is forced to re-run and
issue a fresh decision before the Reviewer can ever see this task again.

Requires a running Postgres reachable via DATABASE_URL, with migrations
0001-0003 applied and seed.py already run (for the 4 agents). No real
Anthropic API call is made.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import models, schemas, task_service  # noqa: E402
from app.database import SessionLocal  # noqa: E402


class PolicyTierResetOnAmendmentTest(unittest.TestCase):
    def setUp(self):
        self.db = SessionLocal()
        agents = {a.role: a for a in self.db.query(models.Agent).all()}
        self.pm = agents.get("pm")
        self.engineering = agents.get("engineering_lead")
        self.risk = agents.get("risk_governance")
        self.reviewer = agents.get("reviewer")
        if not all([self.pm, self.engineering, self.risk, self.reviewer]):
            self.skipTest("seed.py has not been run - agents not found")

        self.task = models.Task(title="HQ-102 replay: CSV export pagination fix", state="contracted")
        self.db.add(self.task)
        self.db.flush()
        thread = models.Thread(task_id=self.task.id)
        self.db.add(thread)
        self.db.flush()
        self.task.thread_id = thread.id
        self.db.commit()

        # #1 - PM's initial contract
        task_service.post_message(
            self.db,
            self.task,
            schemas.MessageCreate(
                author_type="agent",
                author_id=self.pm.id,
                message_type="contract",
                content="CONTRACT: READY - export exactly what's shown on screen with current filters",
            ),
        )
        task_service.claim(self.db, self.task, self.engineering.id)

        # #2 - Engineering's proposal, flagging the pagination ambiguity
        task_service.post_message(
            self.db,
            self.task,
            schemas.MessageCreate(
                author_type="agent",
                author_id=self.engineering.id,
                message_type="proposal",
                content="proposal flagging the pagination ambiguity, not resolving it",
            ),
        )

        # #3 - Risk tiers it auto against the original contract
        task_service.post_message(
            self.db,
            self.task,
            schemas.MessageCreate(
                author_type="agent", author_id=self.risk.id, message_type="decision", content="TIER: auto"
            ),
        )
        self.task.policy_tier = "auto"
        task_service.advance_to_review_if_ready(self.db, self.task)
        self.db.commit()
        self.assertEqual(self.task.state, "in_review", "sanity check: reaches review before the amendment")

        # #4 - Reviewer rejects back to PM over the unmeasurable acceptance criterion
        self.critique = task_service.post_message(
            self.db,
            self.task,
            schemas.MessageCreate(
                author_type="agent",
                author_id=self.reviewer.id,
                message_type="critique",
                content="VERDICT: REJECTED\nREJECTED_TO: pm\n\nacceptance criterion is unmeasurable while paginated",
                rejected_to_agent_id=self.pm.id,
            ),
        )
        task_service.apply_transition(self.db, self.task, "in_progress")
        self.task.rejected_to_agent_id = self.pm.id
        self.task.pending_critique_message_id = self.critique.id
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_amended_contract_resets_tier_and_blocks_review_until_risk_reruns(self):
        # #7 - PM resolves the rejection with an amended contract (the real
        # HQ-102 fix: "all rows matching filters, across all pages")
        task_service.post_message(
            self.db,
            self.task,
            schemas.MessageCreate(
                author_type="agent",
                author_id=self.pm.id,
                message_type="contract",
                content="CONTRACT: READY - all rows matching current filters, across all pages",
                resolves_message_id=self.critique.id,
            ),
        )
        task_service.advance_to_review_if_ready(self.db, self.task)
        self.db.commit()
        self.db.refresh(self.task)

        self.assertIsNone(self.task.policy_tier, "amending an already-tiered contract must reset the tier")
        self.assertIsNone(self.task.rejected_to_agent_id, "the rejection itself is still resolved")
        self.assertIsNone(self.task.pending_critique_message_id)
        self.assertEqual(
            self.task.state,
            "in_progress",
            "must NOT reach in_review (and thus must NOT let #8's receipt happen) on the "
            "strength of a tier decision Risk made against the pre-amendment contract",
        )

        # Risk re-runs and re-tiers against the amended contract - what should
        # have happened before any receipt could be generated.
        task_service.post_message(
            self.db,
            self.task,
            schemas.MessageCreate(
                author_type="agent",
                author_id=self.risk.id,
                message_type="decision",
                content="TIER: auto - amendment only clarifies acceptance criteria, no new risk surface",
            ),
        )
        self.task.policy_tier = "auto"
        task_service.advance_to_review_if_ready(self.db, self.task)
        self.db.commit()
        self.db.refresh(self.task)

        self.assertEqual(
            self.task.state, "in_review", "now reaches review, on the strength of the fresh tier decision"
        )

    def test_amendment_while_untiered_is_a_no_op(self):
        """A contract-type message posted before Risk has ever tiered the task
        (policy_tier already None) must not error or do anything unusual -
        the reset only matters once there's a tier to invalidate."""
        self.task.policy_tier = None
        self.db.commit()

        task_service.post_message(
            self.db,
            self.task,
            schemas.MessageCreate(
                author_type="agent",
                author_id=self.pm.id,
                message_type="contract",
                content="CONTRACT: READY - some other revision",
                resolves_message_id=self.critique.id,
            ),
        )
        self.db.commit()
        self.db.refresh(self.task)
        self.assertIsNone(self.task.policy_tier)


if __name__ == "__main__":
    unittest.main()
