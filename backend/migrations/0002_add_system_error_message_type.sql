-- Migration 0002: add 'system_error' to message_type, for automated
-- blocking notices (agent-call failure, cascade-loop breaker) rather than
-- an agent- or human-authored message.

ALTER TYPE message_type ADD VALUE IF NOT EXISTS 'system_error';
