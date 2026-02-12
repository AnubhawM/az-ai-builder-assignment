# database/schemas.py
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime


# ──────────────────────────────────────
# User Schemas
# ──────────────────────────────────────

class UserBase(BaseModel):
    name: str
    email: str
    role: str = "researcher"

class UserCreate(UserBase):
    slack_user_id: Optional[str] = None

class UserResponse(UserBase):
    id: int
    slack_user_id: Optional[str] = None
    is_agent: bool
    is_active: bool
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ──────────────────────────────────────
# Workflow Schemas
# ──────────────────────────────────────

class WorkflowCreate(BaseModel):
    topic: str
    workflow_type: str = "ppt_generation"
    user_id: int

class WorkflowResponse(BaseModel):
    id: int
    user_id: int
    workflow_type: str
    title: str
    status: str
    openclaw_session_id: Optional[str] = None
    parent_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class WorkflowDetailResponse(WorkflowResponse):
    owner: Optional[UserResponse] = None
    steps: List["WorkflowStepResponse"] = []
    events: List["WorkflowEventResponse"] = []


# ──────────────────────────────────────
# WorkflowStep Schemas
# ──────────────────────────────────────

class WorkflowStepResponse(BaseModel):
    id: int
    workflow_id: int
    step_order: int
    step_type: str
    assigned_to: Optional[int] = None
    provider_type: str
    status: str
    input_data: Optional[Dict[str, Any]] = None
    output_data: Optional[Dict[str, Any]] = None
    feedback: Optional[str] = None
    iteration_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    assignee: Optional[UserResponse] = None

    class Config:
        from_attributes = True


# ──────────────────────────────────────
# WorkflowEvent Schemas
# ──────────────────────────────────────

class WorkflowEventResponse(BaseModel):
    id: int
    workflow_id: int
    step_id: Optional[int] = None
    event_type: str
    actor_id: Optional[int] = None
    actor_type: str
    channel: Optional[str] = None
    message: Optional[str] = None
    metadata_json: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    actor: Optional[UserResponse] = None

    class Config:
        from_attributes = True


# ──────────────────────────────────────
# Review Action Schemas
# ──────────────────────────────────────

class ReviewAction(BaseModel):
    """Schema for approve/refine actions from web or Slack."""
    action: str  # "approve" or "refine"
    feedback: Optional[str] = None  # Required if action is "refine"
    user_id: int
    channel: str = "web"  # "web" or "slack"


# ──────────────────────────────────────
# Marketplace Store Schemas
# ──────────────────────────────────────

class WorkRequestBase(BaseModel):
    title: str
    description: str
    required_capabilities: Optional[List[str]] = None

class WorkRequestCreate(WorkRequestBase):
    requester_id: int
    parent_workflow_id: Optional[int] = None

class VolunteerCreate(BaseModel):
    request_id: int
    user_id: int
    note: Optional[str] = None

class VolunteerResponse(BaseModel):
    id: int
    request_id: int
    user_id: int
    note: Optional[str] = None
    status: str
    created_at: datetime
    user: Optional[UserResponse] = None

    class Config:
        from_attributes = True

class WorkRequestResponse(WorkRequestBase):
    id: int
    requester_id: int
    status: str
    parent_workflow_id: Optional[int] = None
    created_at: datetime
    requester: Optional[UserResponse] = None
    volunteers: List[VolunteerResponse] = []

    class Config:
        from_attributes = True

# Resolve forward references
WorkflowDetailResponse.model_rebuild()
WorkRequestResponse.model_rebuild()
