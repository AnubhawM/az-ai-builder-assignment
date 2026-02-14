# crud.py
# Database CRUD operations for the AIXplore Capability Exchange

from sqlalchemy.orm import Session
from database.models import (
    User, Workflow, WorkflowStep, WorkflowEvent,
    WorkflowMessage, WorkflowApproval,
    WorkRequest, Volunteer
)


# ──────────────────────────────────────
# User Operations
# ──────────────────────────────────────

def create_user(db: Session, user_data: dict) -> User:
    new_user = User(
        name=user_data['name'],
        email=user_data['email'],
        role=user_data.get('role', 'researcher'),
        slack_user_id=user_data.get('slack_user_id'),
        is_agent=user_data.get('is_agent', False),
        is_active=user_data.get('is_active', True),
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.query(User).filter(User.id == user_id).first()


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email).first()


def get_all_users(db: Session) -> list[User]:
    return db.query(User).filter(User.is_active == True).all()


# ──────────────────────────────────────
# Workflow Operations
# ──────────────────────────────────────

def create_workflow(db: Session, user_id: int, title: str,
                    workflow_type: str = "ppt_generation",
                    openclaw_session_id: str = None,
                    parent_id: int = None) -> Workflow:
    workflow = Workflow(
        user_id=user_id,
        workflow_type=workflow_type,
        title=title,
        status="pending",
        openclaw_session_id=openclaw_session_id,
        parent_id=parent_id,
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return workflow


def get_workflow_by_id(db: Session, workflow_id: int) -> Workflow | None:
    return db.query(Workflow).filter(Workflow.id == workflow_id).first()


def get_workflows_by_user(db: Session, user_id: int) -> list[Workflow]:
    return (
        db.query(Workflow)
        .filter(Workflow.user_id == user_id)
        .order_by(Workflow.created_at.desc())
        .all()
    )


def get_all_workflows(db: Session) -> list[Workflow]:
    return (
        db.query(Workflow)
        .order_by(Workflow.created_at.desc())
        .all()
    )


def get_workflows_assigned_to_user(db: Session, user_id: int) -> list[Workflow]:
    """Get workflows where the user has a step assigned to them that needs attention."""
    return (
        db.query(Workflow)
        .join(WorkflowStep, Workflow.id == WorkflowStep.workflow_id)
        .filter(
            WorkflowStep.assigned_to == user_id,
            WorkflowStep.status.in_(["pending", "in_progress", "awaiting_input"])
        )
        .distinct()
        .order_by(Workflow.updated_at.desc())
        .all()
    )


def update_workflow_status(db: Session, workflow_id: int, status: str,
                           openclaw_session_id: str = None) -> Workflow | None:
    workflow = get_workflow_by_id(db, workflow_id)
    if workflow:
        workflow.status = status
        if openclaw_session_id:
            workflow.openclaw_session_id = openclaw_session_id
        db.commit()
        db.refresh(workflow)
    return workflow


# ──────────────────────────────────────
# WorkflowStep Operations
# ──────────────────────────────────────

def create_workflow_step(db: Session, workflow_id: int, step_order: int,
                         step_type: str, provider_type: str = "agent",
                         assigned_to: int = None,
                         input_data: dict = None) -> WorkflowStep:
    step = WorkflowStep(
        workflow_id=workflow_id,
        step_order=step_order,
        step_type=step_type,
        provider_type=provider_type,
        assigned_to=assigned_to,
        status="pending",
        input_data=input_data,
    )
    db.add(step)
    db.commit()
    db.refresh(step)
    return step


def get_step_by_id(db: Session, step_id: int) -> WorkflowStep | None:
    return db.query(WorkflowStep).filter(WorkflowStep.id == step_id).first()


def get_active_step(db: Session, workflow_id: int) -> WorkflowStep | None:
    """Get the current active step for a workflow."""
    return (
        db.query(WorkflowStep)
        .filter(
            WorkflowStep.workflow_id == workflow_id,
            WorkflowStep.status.in_(["pending", "in_progress", "awaiting_input"])
        )
        .order_by(WorkflowStep.step_order)
        .first()
    )


def get_active_step_by_type(db: Session, workflow_id: int, step_type: str) -> WorkflowStep | None:
    """Get the most recent active step for a workflow by step_type."""
    return (
        db.query(WorkflowStep)
        .filter(
            WorkflowStep.workflow_id == workflow_id,
            WorkflowStep.step_type == step_type,
            WorkflowStep.status.in_(["pending", "in_progress", "awaiting_input"])
        )
        .order_by(WorkflowStep.step_order.desc(), WorkflowStep.id.desc())
        .first()
    )


def update_step_status(db: Session, step_id: int, status: str,
                        output_data: dict = None,
                        feedback: str = None) -> WorkflowStep | None:
    step = get_step_by_id(db, step_id)
    if step:
        step.status = status
        if output_data is not None:
            step.output_data = output_data
        if feedback is not None:
            step.feedback = feedback
        db.commit()
        db.refresh(step)
    return step


def increment_step_iteration(db: Session, step_id: int) -> WorkflowStep | None:
    step = get_step_by_id(db, step_id)
    if step:
        step.iteration_count += 1
        db.commit()
        db.refresh(step)
    return step


# ──────────────────────────────────────
# WorkflowEvent Operations
# ──────────────────────────────────────

def create_event(db: Session, workflow_id: int, event_type: str,
                 actor_type: str = "system", step_id: int = None,
                 actor_id: int = None, channel: str = None,
                 message: str = None,
                 metadata_json: dict = None) -> WorkflowEvent:
    event = WorkflowEvent(
        workflow_id=workflow_id,
        step_id=step_id,
        event_type=event_type,
        actor_id=actor_id,
        actor_type=actor_type,
        channel=channel,
        message=message,
        metadata_json=metadata_json,
    )
    db.add(event)
    db.flush()  # assign PK before commit so we can fetch safely afterward
    event_id = event.id
    db.commit()
    # Avoid refresh-related identity-map conflicts; fetch by id after commit.
    return db.get(WorkflowEvent, event_id) or event


def get_events_for_workflow(db: Session, workflow_id: int) -> list[WorkflowEvent]:
    return (
        db.query(WorkflowEvent)
        .filter(WorkflowEvent.workflow_id == workflow_id)
        .order_by(WorkflowEvent.created_at.asc())
        .all()
    )


# ──────────────────────────────────────
# Workflow Chat Operations
# ──────────────────────────────────────

def create_workflow_message(
    db: Session,
    workflow_id: int,
    message: str,
    sender_id: int = None,
    sender_type: str = "human",
    channel: str = "web",
    metadata_json: dict = None
) -> WorkflowMessage:
    new_message = WorkflowMessage(
        workflow_id=workflow_id,
        sender_id=sender_id,
        sender_type=sender_type,
        channel=channel,
        message=message,
        metadata_json=metadata_json,
    )
    db.add(new_message)
    db.commit()
    db.refresh(new_message)
    return new_message


def get_messages_for_workflow(db: Session, workflow_id: int) -> list[WorkflowMessage]:
    return (
        db.query(WorkflowMessage)
        .filter(WorkflowMessage.workflow_id == workflow_id)
        .order_by(WorkflowMessage.created_at.asc())
        .all()
    )


# ──────────────────────────────────────
# Workflow Completion Operations
# ──────────────────────────────────────

def get_workflow_approval(db: Session, workflow_id: int, user_id: int) -> WorkflowApproval | None:
    return (
        db.query(WorkflowApproval)
        .filter(
            WorkflowApproval.workflow_id == workflow_id,
            WorkflowApproval.user_id == user_id
        )
        .first()
    )


def upsert_workflow_approval(
    db: Session,
    workflow_id: int,
    user_id: int,
    status: str
) -> WorkflowApproval:
    approval = get_workflow_approval(db, workflow_id, user_id)
    if approval:
        approval.status = status
    else:
        approval = WorkflowApproval(
            workflow_id=workflow_id,
            user_id=user_id,
            status=status
        )
        db.add(approval)
    db.commit()
    db.refresh(approval)
    return approval


def get_workflow_approvals(db: Session, workflow_id: int) -> list[WorkflowApproval]:
    return (
        db.query(WorkflowApproval)
        .filter(WorkflowApproval.workflow_id == workflow_id)
        .order_by(WorkflowApproval.created_at.asc())
        .all()
    )


# ──────────────────────────────────────
# Marketplace Operations
# ──────────────────────────────────────

def create_work_request(db: Session, request_data: dict) -> WorkRequest:
    new_request = WorkRequest(
        requester_id=request_data['requester_id'],
        title=request_data['title'],
        description=request_data['description'],
        required_capabilities=request_data.get('required_capabilities', []),
        parent_workflow_id=request_data.get('parent_workflow_id'),
        status="open"
    )
    db.add(new_request)
    db.commit()
    db.refresh(new_request)
    return new_request


def get_work_request_by_id(db: Session, request_id: int) -> WorkRequest | None:
    return db.query(WorkRequest).filter(WorkRequest.id == request_id).first()


def get_all_work_requests(db: Session) -> list[WorkRequest]:
    return (
        db.query(WorkRequest)
        .order_by(WorkRequest.created_at.desc())
        .all()
    )


def get_open_work_requests(db: Session) -> list[WorkRequest]:
    return (
        db.query(WorkRequest)
        .filter(WorkRequest.status == "open")
        .order_by(WorkRequest.created_at.desc())
        .all()
    )


def create_volunteer(db: Session, volunteer_data: dict) -> Volunteer:
    new_volunteer = Volunteer(
        request_id=volunteer_data['request_id'],
        user_id=volunteer_data['user_id'],
        note=volunteer_data.get('note'),
        status="pending"
    )
    db.add(new_volunteer)
    db.commit()
    db.refresh(new_volunteer)
    return new_volunteer


def get_volunteer_by_id(db: Session, volunteer_id: int) -> Volunteer | None:
    return db.query(Volunteer).filter(Volunteer.id == volunteer_id).first()


def update_volunteer_status(db: Session, volunteer_id: int, status: str) -> Volunteer | None:
    volunteer = get_volunteer_by_id(db, volunteer_id)
    if volunteer:
        volunteer.status = status
        db.commit()
        db.refresh(volunteer)
    return volunteer
