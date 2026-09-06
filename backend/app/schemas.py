import datetime
import uuid

from pydantic import BaseModel, ConfigDict


class AgentCreate(BaseModel):
    name: str
    role: str
    status: str = "green"
    runtime: str = "claude"


class AgentOut(AgentCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime.datetime


class TaskCreate(BaseModel):
    title: str
    objective: str | None = None
    scope: list[str] = []
    constraints: list[str] = []
    acceptance_criteria: list[str] = []


class TaskUpdate(BaseModel):
    title: str | None = None
    objective: str | None = None
    scope: list[str] | None = None
    constraints: list[str] | None = None
    acceptance_criteria: list[str] | None = None
    policy_tier: str | None = None
    owner_agent_id: uuid.UUID | None = None


class TaskTransition(BaseModel):
    to_state: str


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    objective: str | None
    scope: list[str]
    constraints: list[str]
    acceptance_criteria: list[str]
    policy_tier: str | None
    state: str
    owner_agent_id: uuid.UUID | None
    thread_id: uuid.UUID | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ThreadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID


class MessageCreate(BaseModel):
    author_type: str
    author_id: uuid.UUID | None = None
    message_type: str
    content: str


class MessageOut(MessageCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    thread_id: uuid.UUID
    created_at: datetime.datetime


class ReceiptCreate(BaseModel):
    objective: str | None = None
    changed: list[str] = []
    verified: list[str] = []
    not_verified: list[str] = []
    risks: list[str] = []
    approval_needed: list[str] = []
    decided_by: uuid.UUID | None = None


class ReceiptOut(ReceiptCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    decided_at: datetime.datetime | None


class PolicyRuleCreate(BaseModel):
    action_type: str
    tier: str
    rationale: str | None = None


class PolicyRuleOut(PolicyRuleCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
