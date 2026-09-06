import uuid

from sqlalchemy import ARRAY, TIMESTAMP, Enum, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

AgentStatus = Enum("green", "yellow", "gray", "orange", name="agent_status")
PolicyTier = Enum("auto", "approval_required", "prohibited", name="policy_tier")
TaskState = Enum(
    "proposed",
    "contracted",
    "in_progress",
    "in_review",
    "approved",
    "rejected",
    "blocked",
    name="task_state",
)
AuthorType = Enum("agent", "human", name="author_type")
MessageType = Enum(
    "contract", "proposal", "critique", "decision", "receipt", name="message_type"
)


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(AgentStatus, nullable=False, default="green")
    runtime: Mapped[str] = mapped_column(Text, nullable=False, default="claude")
    created_at: Mapped[object] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    objective: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    constraints: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    acceptance_criteria: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    policy_tier: Mapped[str | None] = mapped_column(PolicyTier)
    state: Mapped[str] = mapped_column(TaskState, nullable=False, default="proposed")
    owner_agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id"))
    thread_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("threads.id"))
    created_at: Mapped[object] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[object] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    thread: Mapped["Thread"] = relationship(back_populates="task", foreign_keys=[thread_id])


class Thread(Base):
    __tablename__ = "threads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=False)

    task: Mapped["Task"] = relationship(back_populates="thread", foreign_keys=[Task.thread_id])
    messages: Mapped[list["Message"]] = relationship(back_populates="thread")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("threads.id"), nullable=False)
    author_type: Mapped[str] = mapped_column(AuthorType, nullable=False)
    author_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    message_type: Mapped[str] = mapped_column(MessageType, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[object] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    thread: Mapped["Thread"] = relationship(back_populates="messages")


class Receipt(Base):
    __tablename__ = "receipts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=False)
    objective: Mapped[str | None] = mapped_column(Text)
    changed: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    verified: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    not_verified: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    risks: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    approval_needed: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id"))
    decided_at: Mapped[object | None] = mapped_column(TIMESTAMP(timezone=True))


class PolicyRule(Base):
    __tablename__ = "policy_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    action_type: Mapped[str] = mapped_column(Text, nullable=False)
    tier: Mapped[str] = mapped_column(PolicyTier, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
