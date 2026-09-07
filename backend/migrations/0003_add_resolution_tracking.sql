-- Migration 0003: resolution-linked revisions.
--
-- Fixes the rejection-routing gap found in docs/real-run-log-v3.md: any
-- message posted while a task was rejected could falsely advance it back to
-- review, regardless of whether the actual defect was addressed, and PM
-- could never be re-invoked once a task had a contract.
--
-- messages.resolves_message_id names exactly which critique a message is
-- answering. tasks.rejected_to_agent_id / pending_critique_message_id are
-- its companion: set together when the Reviewer rejects, cleared together
-- once the targeted agent's resolving message (linked via
-- resolves_message_id) lands - see task_service.advance_to_review_if_ready.

ALTER TABLE messages ADD COLUMN resolves_message_id UUID REFERENCES messages(id);

ALTER TABLE tasks ADD COLUMN rejected_to_agent_id UUID REFERENCES agents(id);
ALTER TABLE tasks ADD COLUMN pending_critique_message_id UUID REFERENCES messages(id);
