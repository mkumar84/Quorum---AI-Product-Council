-- Quorum — AI Product Council
-- Migration 0001: initial schema (build spec section 1)

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TYPE agent_status AS ENUM ('green', 'yellow', 'gray', 'orange');
CREATE TYPE policy_tier AS ENUM ('auto', 'approval_required', 'prohibited');
CREATE TYPE task_state AS ENUM (
    'proposed', 'contracted', 'in_progress', 'in_review',
    'approved', 'rejected', 'blocked'
);
CREATE TYPE author_type AS ENUM ('agent', 'human');
CREATE TYPE message_type AS ENUM ('contract', 'proposal', 'critique', 'decision', 'receipt');

CREATE TABLE agents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    status agent_status NOT NULL DEFAULT 'green',
    runtime TEXT NOT NULL DEFAULT 'claude',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    objective TEXT,
    scope TEXT[] NOT NULL DEFAULT '{}',
    constraints TEXT[] NOT NULL DEFAULT '{}',
    acceptance_criteria TEXT[] NOT NULL DEFAULT '{}',
    policy_tier policy_tier,
    state task_state NOT NULL DEFAULT 'proposed',
    owner_agent_id UUID REFERENCES agents(id),
    thread_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE threads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES tasks(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE tasks
    ADD CONSTRAINT tasks_thread_id_fkey FOREIGN KEY (thread_id) REFERENCES threads(id);

CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id UUID NOT NULL REFERENCES threads(id),
    author_type author_type NOT NULL,
    author_id UUID,
    message_type message_type NOT NULL,
    content TEXT NOT NULL,
    -- set only on a Reviewer rejection: which agent the task bounces back to.
    rejected_to_agent_id UUID REFERENCES agents(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE receipts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES tasks(id),
    objective TEXT,
    changed TEXT[] NOT NULL DEFAULT '{}',
    verified TEXT[] NOT NULL DEFAULT '{}',
    not_verified TEXT[] NOT NULL DEFAULT '{}',
    risks TEXT[] NOT NULL DEFAULT '{}',
    approval_needed TEXT[] NOT NULL DEFAULT '{}',
    decided_by UUID REFERENCES agents(id),
    decided_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE policy_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    action_type TEXT NOT NULL,
    tier policy_tier NOT NULL,
    rationale TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_tasks_state ON tasks(state);
CREATE INDEX idx_messages_thread_id ON messages(thread_id);
CREATE INDEX idx_threads_task_id ON threads(task_id);
