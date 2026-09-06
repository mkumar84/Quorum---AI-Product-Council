import datetime
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class AgentCreate(BaseModel):
    name: str
    role: str
    status: str = "green"
    runtime: str = "claude"


class AgentOut(AgentCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime.datetime
    updated_at: datetime.datetime


class TaskCreate(BaseModel):
    """A raw feature request — no contract yet, that's the PM agent's job."""

    title: str


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


class MessageCreate(BaseModel):
    author_type: Literal["agent", "human"]
    author_id: uuid.UUID | None = None
    message_type: Literal["contract", "proposal", "critique", "decision", "receipt"]
    content: str
    rejected_to_agent_id: uuid.UUID | None = None


class MessageOut(MessageCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    thread_id: uuid.UUID
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ReceiptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    objective: str | None
    changed: list[str]
    verified: list[str]
    not_verified: list[str]
    risks: list[str]
    approval_needed: list[str]
    decided_by: uuid.UUID | None
    decided_at: datetime.datetime | None


class TaskDetailOut(TaskOut):
    messages: list[MessageOut]
    receipt: ReceiptOut | None = None


class ContractPayload(BaseModel):
    """Manually-typed stand-in for the PM agent's contract (build spec step 2)."""

    pm_agent_id: uuid.UUID
    objective: str
    scope: list[str] = []
    constraints: list[str] = []
    acceptance_criteria: list[str] = []


class ClaimPayload(BaseModel):
    agent_id: uuid.UUID


class ReviewPayload(BaseModel):
    """Manually-typed stand-in for the Reviewer's verdict (build spec step 2)."""

    reviewer_agent_id: uuid.UUID
    verdict: Literal["approve", "reject"]

    # required when verdict == "reject"
    rejected_to_agent_id: uuid.UUID | None = None
    reason: str | None = None

    # used to build the receipt when verdict == "approve"
    objective: str | None = None
    changed: list[str] = []
    verified: list[str] = []
    not_verified: list[str] = []
    risks: list[str] = []
    approval_needed: list[str] = []

    @model_validator(mode="after")
    def _require_rejection_fields(self) -> "ReviewPayload":
        if self.verdict == "reject" and (self.rejected_to_agent_id is None or not self.reason):
            raise ValueError("rejected_to_agent_id and reason are required when verdict is 'reject'")
        return self


class PolicyRuleCreate(BaseModel):
    action_type: str
    tier: str
    rationale: str | None = None


class PolicyRuleOut(PolicyRuleCreate):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
