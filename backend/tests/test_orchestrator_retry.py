"""Tests app.orchestrator's Claude-call retry/backoff and the resulting
block-on-exhaustion behavior, exercised through council.on_task_updated
(not orchestrator directly) so this also proves no unhandled exception
escapes the cascade trigger loop when an agent's Claude call keeps failing.

Requires a running Postgres reachable via DATABASE_URL, with migrations
0001 and 0002 applied and seed.py already run (for the 4 agents). No real
Anthropic API call is made - _call_claude is monkeypatched to always raise.

Run: python -m unittest tests.test_orchestrator_retry
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import council, models, orchestrator  # noqa: E402
from app.database import SessionLocal  # noqa: E402


class RetryAndBlockTest(unittest.TestCase):
    def setUp(self):
        self.db = SessionLocal()
        self.engineering_agent = (
            self.db.query(models.Agent).filter(models.Agent.role == "engineering_lead").first()
        )
        self.risk_agent = self.db.query(models.Agent).filter(models.Agent.role == "risk_governance").first()
        if not self.engineering_agent or not self.risk_agent:
            self.skipTest("seed.py has not been run - engineering_lead/risk_governance agents not found")

        # A fresh, isolated task already 'contracted' so council goes straight to
        # Engineering + Risk without needing a (real or mocked) PM call first.
        self.task = models.Task(title="retry-test task", state="contracted")
        self.db.add(self.task)
        self.db.flush()
        thread = models.Thread(task_id=self.task.id)
        self.db.add(thread)
        self.db.flush()
        self.task.thread_id = thread.id
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_retries_exactly_twice_then_blocks_without_raising(self):
        call_count = 0

        def always_fails(system_prompt, user_content):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("simulated Claude outage")

        with (
            mock.patch.object(orchestrator, "_call_claude", side_effect=always_fails),
            mock.patch.object(orchestrator.time, "sleep") as mock_sleep,
        ):
            # The point of the test: this must not raise, even though the
            # underlying Claude call fails on every attempt.
            council.on_task_updated(self.db, self.task)

        expected_attempts = orchestrator.MAX_CLAUDE_RETRIES + 1
        self.assertEqual(call_count, expected_attempts, "expected 1 initial attempt + 2 retries, no more")
        self.assertEqual(
            [c.args[0] for c in mock_sleep.call_args_list],
            orchestrator.RETRY_BACKOFF_SECONDS,
            "expected the 1s, 4s backoff schedule between retries",
        )

        self.db.refresh(self.task)
        self.assertEqual(self.task.state, "blocked")

        messages = (
            self.db.query(models.Message).filter(models.Message.thread_id == self.task.thread_id).all()
        )
        system_errors = [m for m in messages if m.message_type == "system_error"]
        self.assertEqual(len(system_errors), 1, "engineering's failure should block before risk ever calls Claude")
        self.assertIn("[agent-call-failed]", system_errors[0].content)
        self.assertIn("engineering_lead", system_errors[0].content)
        self.assertEqual(system_errors[0].author_id, self.engineering_agent.id)


if __name__ == "__main__":
    unittest.main()
