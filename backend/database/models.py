# database/models.py
from sqlalchemy import Column, Integer, String, DateTime, Boolean, JSON, ForeignKey, Text, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from . import Base


class User(Base):
    """
    Pre-seeded user personas for the AIXplore Capability Exchange.
    Supports researchers, compliance experts, design reviewers, etc.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    role = Column(String, nullable=False, default="researcher")
    slack_user_id = Column(String, nullable=True)
    is_agent = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    workflows = relationship("Workflow", back_populates="owner", foreign_keys="Workflow.user_id")
    assigned_steps = relationship("WorkflowStep", back_populates="assignee", foreign_keys="WorkflowStep.assigned_to")
    events = relationship("WorkflowEvent", back_populates="actor", foreign_keys="WorkflowEvent.actor_id")
    messages = relationship("WorkflowMessage", back_populates="sender", foreign_keys="WorkflowMessage.sender_id")
    approvals = relationship("WorkflowApproval", back_populates="user", foreign_keys="WorkflowApproval.user_id")

    def __repr__(self):
        return f"<User(id={self.id}, name='{self.name}', role='{self.role}')>"

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "role": self.role,
            "slack_user_id": self.slack_user_id,
            "is_agent": self.is_agent,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Workflow(Base):
    """
    A generic workflow container for any task type in the Capability Exchange.
    Tracks the overall state, OpenClaw session memory, and ownership.
    """
    __tablename__ = "workflows"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    workflow_type = Column(String, nullable=False)  # e.g., "ppt_generation", "citation_check", "pii_scan"
    title = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")
    # Status values: pending, collaborating, researching, awaiting_review, refining,
    #                generating_ppt, awaiting_presentation_review, completed, failed
    openclaw_session_id = Column(String, nullable=True)
    parent_id = Column(Integer, ForeignKey("workflows.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    owner = relationship("User", back_populates="workflows", foreign_keys=[user_id])
    parent = relationship("Workflow", remote_side=[id], backref="sub_workflows")
    steps = relationship("WorkflowStep", back_populates="workflow", order_by="WorkflowStep.step_order",
                         cascade="all, delete-orphan")
    events = relationship("WorkflowEvent", back_populates="workflow", order_by="WorkflowEvent.created_at",
                          cascade="all, delete-orphan")
    messages = relationship("WorkflowMessage", back_populates="workflow", order_by="WorkflowMessage.created_at",
                            cascade="all, delete-orphan")
    approvals = relationship("WorkflowApproval", back_populates="workflow",
                             cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Workflow(id={self.id}, type='{self.workflow_type}', status='{self.status}')>"

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "workflow_type": self.workflow_type,
            "title": self.title,
            "status": self.status,
            "openclaw_session_id": self.openclaw_session_id,
            "parent_id": self.parent_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "owner": self.owner.to_dict() if self.owner else None,
            "steps": [step.to_dict() for step in self.steps] if self.steps else [],
            "events": [event.to_dict() for event in self.events] if self.events else [],
            "messages": [message.to_dict() for message in self.messages] if self.messages else [],
            "approvals": [approval.to_dict() for approval in self.approvals] if self.approvals else [],
        }


class WorkflowStep(Base):
    """
    An individual step in a workflow pipeline.
    Represents agent tasks, human reviews, specialist approvals, etc.
    Tracks the evolving content and the refinement loop history.
    """
    __tablename__ = "workflow_steps"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=False)
    step_order = Column(Integer, nullable=False, default=1)
    step_type = Column(String, nullable=False)
    # Step type values: agent_research, human_review, specialist_review,
    #                   human_research, agent_collaboration,
    #                   agent_generation, presentation_review
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)  # NULL for agent steps
    provider_type = Column(String, nullable=False, default="agent")  # "agent" or "human"
    status = Column(String, nullable=False, default="pending")
    # Status values: pending, in_progress, awaiting_input, completed, skipped, failed
    input_data = Column(JSON, nullable=True)   # JSON: prompt, instructions, context passed to this step
    output_data = Column(JSON, nullable=True)  # JSON: summary, slide_outline, raw_research, file_path, etc.
    feedback = Column(Text, nullable=True)      # Human feedback / refinement instructions
    iteration_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    workflow = relationship("Workflow", back_populates="steps")
    assignee = relationship("User", back_populates="assigned_steps", foreign_keys=[assigned_to])
    events = relationship("WorkflowEvent", back_populates="step", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<WorkflowStep(id={self.id}, type='{self.step_type}', status='{self.status}')>"

    def to_dict(self):
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "step_order": self.step_order,
            "step_type": self.step_type,
            "assigned_to": self.assigned_to,
            "provider_type": self.provider_type,
            "status": self.status,
            "input_data": self.input_data,
            "output_data": self.output_data,
            "feedback": self.feedback,
            "iteration_count": self.iteration_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "assignee": self.assignee.to_dict() if self.assignee else None,
        }


class WorkflowEvent(Base):
    """
    Append-only audit log of every interaction across all channels.
    Tracks who did what, when, and from where (web or Slack).
    """
    __tablename__ = "workflow_events"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=False)
    step_id = Column(Integer, ForeignKey("workflow_steps.id"), nullable=True)
    event_type = Column(String, nullable=False)
    # Event type values: created, research_started, research_completed,
    #                    review_requested, approved, refined, escalated,
    #                    generation_requested, generation_started, generation_completed,
    #                    message_posted, completion_marked, reopened,
    #                    agent_replied, notification_sent, failed
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # NULL for system/agent events
    actor_type = Column(String, nullable=False, default="system")  # "human", "agent", "system"
    channel = Column(String, nullable=True)  # "web", "slack", or NULL for system events
    message = Column(Text, nullable=True)
    metadata_json = Column(JSON, nullable=True)  # Additional context (e.g., Slack message_ts)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    workflow = relationship("Workflow", back_populates="events")
    step = relationship("WorkflowStep", back_populates="events")
    actor = relationship("User", back_populates="events", foreign_keys=[actor_id])

    def __repr__(self):
        return f"<WorkflowEvent(id={self.id}, type='{self.event_type}', channel='{self.channel}')>"

    def to_dict(self):
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "step_id": self.step_id,
            "event_type": self.event_type,
            "actor_id": self.actor_id,
            "actor_type": self.actor_type,
            "channel": self.channel,
            "message": self.message,
            "metadata_json": self.metadata_json,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "actor": self.actor.to_dict() if self.actor else None,
        }


class WorkflowMessage(Base):
    """
    Chat messages exchanged inside a workflow between humans, agent, and system.
    """
    __tablename__ = "workflow_messages"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=False)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    sender_type = Column(String, nullable=False, default="human")  # human, agent, system
    channel = Column(String, nullable=False, default="web")  # web, slack, system
    message = Column(Text, nullable=False)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    workflow = relationship("Workflow", back_populates="messages")
    sender = relationship("User", back_populates="messages", foreign_keys=[sender_id])

    def to_dict(self):
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "sender_id": self.sender_id,
            "sender_type": self.sender_type,
            "channel": self.channel,
            "message": self.message,
            "metadata_json": self.metadata_json,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "sender": self.sender.to_dict() if self.sender else None,
        }


class WorkflowApproval(Base):
    """
    Tracks participant completion intent for human collaboration workflows.
    """
    __tablename__ = "workflow_approvals"
    __table_args__ = (
        UniqueConstraint("workflow_id", "user_id", name="uq_workflow_approval_user"),
    )

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String, nullable=False, default="pending")  # pending, ready, approved
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    workflow = relationship("Workflow", back_populates="approvals")
    user = relationship("User", back_populates="approvals", foreign_keys=[user_id])

    def to_dict(self):
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "user_id": self.user_id,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "user": self.user.to_dict() if self.user else None,
        }


class WorkRequest(Base):
    """
    Marketplace board entry for a new task or sub-task.
    Enables discovery and volunteering before a workflow is officially created.
    """
    __tablename__ = "work_requests"

    id = Column(Integer, primary_key=True, index=True)
    requester_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    required_capabilities = Column(JSON, nullable=True)  # List of tags like ["research", "compliance"]
    status = Column(String, nullable=False, default="open")  # open, assigned, completed
    parent_workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    requester = relationship("User", foreign_keys=[requester_id])
    volunteers = relationship("Volunteer", back_populates="request", cascade="all, delete-orphan")
    workflow = relationship("Workflow", backref="origin_request", uselist=False)

    def to_dict(self):
        return {
            "id": self.id,
            "requester_id": self.requester_id,
            "title": self.title,
            "description": self.description,
            "required_capabilities": self.required_capabilities or [],
            "status": self.status,
            "parent_workflow_id": self.parent_workflow_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "requester": self.requester.to_dict() if self.requester else None,
            "volunteers": [v.to_dict() for v in self.volunteers] if self.volunteers else []
        }


class Volunteer(Base):
    """
    Bids/claims for a work request. 
    Links users (humans/agents) to work requests they want to work on.
    """
    __tablename__ = "volunteers"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(Integer, ForeignKey("work_requests.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    note = Column(Text, nullable=True)  # Optional "Why I'm a good match"
    status = Column(String, nullable=False, default="pending")  # pending, accepted, rejected
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    request = relationship("WorkRequest", back_populates="volunteers")
    user = relationship("User", foreign_keys=[user_id])

    def to_dict(self):
        return {
            "id": self.id,
            "request_id": self.request_id,
            "user_id": self.user_id,
            "note": self.note,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "user": self.user.to_dict() if self.user else None,
        }
