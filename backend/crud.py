# crud.py
# Database CRUD operations for the AIXplore Capability Exchange

from sqlalchemy.orm import Session
from database.models import User, Workflow, WorkflowStep, WorkflowEvent


# ──────────────────────────────────────
# User Operations
# ──────────────────────────────────────

def create_user(db: Session, user_data: dict) -> User:
    new_user = User(
        name=user_data['name'],
        email=user_data['email'],
        role=user_data.get('role', 'researcher'),
        slack_user_id=user_data.get('slack_user_id'),
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
                    openclaw_session_id: str = None) -> Workflow:
    workflow = Workflow(
        user_id=user_id,
        workflow_type=workflow_type,
        title=title,
        status="pending",
        openclaw_session_id=openclaw_session_id,
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
    db.commit()
    db.refresh(event)
    return event


def get_events_for_workflow(db: Session, workflow_id: int) -> list[WorkflowEvent]:
    return (
        db.query(WorkflowEvent)
        .filter(WorkflowEvent.workflow_id == workflow_id)
        .order_by(WorkflowEvent.created_at.asc())
        .all()
    )
