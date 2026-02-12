"""
Workflow API Routes — Flask Blueprint for the AIXplore Capability Exchange.

Endpoints:
    GET  /api/users                  — List all personas
    POST /api/workflows              — Create a new workflow (triggers research)
    GET  /api/workflows              — List workflows (filtered by user/role)
    GET  /api/workflows/<id>         — Get full workflow detail
    POST /api/workflows/<id>/review  — Submit approve/refine action
    POST /api/slack/interactions     — Handle inbound Slack button clicks
"""

import os
import json
import time
import hmac
import hashlib
import threading
from flask import Blueprint, request, jsonify

from database import SessionLocal
from crud import (
    get_all_users, get_user_by_id,
    create_workflow, get_workflow_by_id,
    get_all_workflows, get_workflows_by_user,
    get_workflows_assigned_to_user,
    update_workflow_status,
    create_workflow_step, get_active_step,
    update_step_status,
    create_event,
    get_open_work_requests, get_work_request_by_id,
    create_work_request, create_volunteer,
    update_volunteer_status, get_volunteer_by_id
)
from openclaw_client import generate_session_id
from workflow_service import start_research, start_refinement, start_ppt_generation

workflow_bp = Blueprint('workflows', __name__)

SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")


# ──────────────────────────────────────
# User Endpoints
# ──────────────────────────────────────

@workflow_bp.route('/api/users', methods=['GET'])
def list_users():
    """List all active personas for the persona selector."""
    db = SessionLocal()
    try:
        users = get_all_users(db)
        return jsonify({
            "users": [u.to_dict() for u in users]
        }), 200
    finally:
        db.close()


# ──────────────────────────────────────
# Workflow CRUD Endpoints
# ──────────────────────────────────────

@workflow_bp.route('/api/workflows', methods=['POST'])
def create_new_workflow():
    """
    Create a new workflow and start the research process.

    Request body:
    {
        "topic": "Sustainable energy technologies",
        "workflow_type": "ppt_generation",  (optional, defaults to ppt_generation)
        "user_id": 1
    }
    """
    db = SessionLocal()
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Request body is required"}), 400

        topic = data.get("topic", "").strip()
        user_id = data.get("user_id")
        workflow_type = data.get("workflow_type", "ppt_generation")

        if not topic:
            return jsonify({"error": "Topic is required"}), 400
        if not user_id:
            return jsonify({"error": "user_id is required"}), 400

        # Verify user exists
        user = get_user_by_id(db, user_id)
        if not user:
            return jsonify({"error": f"User {user_id} not found"}), 404

        # Generate a unique OpenClaw session ID for this workflow
        session_id = f"workflow-{generate_session_id()}"

        # Create the workflow record
        workflow = create_workflow(
            db, user_id=user_id, title=topic,
            workflow_type=workflow_type,
            openclaw_session_id=session_id
        )

        # Create the initial research step
        research_step = create_workflow_step(
            db, workflow_id=workflow.id, step_order=1,
            step_type="agent_research", provider_type="agent",
            input_data={"topic": topic}
        )

        # Log the creation event
        create_event(
            db, workflow_id=workflow.id, event_type="created",
            actor_id=user_id, actor_type="human", channel="web",
            message=f"Workflow created: {topic}"
        )

        # Start research in a background thread
        start_research(workflow.id, topic, session_id)

        return jsonify({
            "message": "Workflow created! Research is starting...",
            "workflow": workflow.to_dict()
        }), 201

    except Exception as e:
        print(f"Error creating workflow: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@workflow_bp.route('/api/workflows', methods=['GET'])
def list_workflows():
    """
    List workflows. Supports filtering by user.

    Query params:
        - user_id: Filter to workflows owned by this user
        - assigned_to: Filter to workflows with steps assigned to this user
        - all: If true, return all workflows (for dashboard)
    """
    db = SessionLocal()
    try:
        user_id = request.args.get("user_id", type=int)
        assigned_to = request.args.get("assigned_to", type=int)
        show_all = request.args.get("all", "false").lower() == "true"

        if show_all:
            workflows = get_all_workflows(db)
        elif assigned_to:
            workflows = get_workflows_assigned_to_user(db, assigned_to)
        elif user_id:
            workflows = get_workflows_by_user(db, user_id)
        else:
            workflows = get_all_workflows(db)

        return jsonify({
            "workflows": [w.to_dict() for w in workflows]
        }), 200
    finally:
        db.close()


@workflow_bp.route('/api/workflows/<int:workflow_id>', methods=['GET'])
def get_workflow_detail(workflow_id):
    """Get the full detail of a workflow including steps, events, and content."""
    db = SessionLocal()
    try:
        workflow = get_workflow_by_id(db, workflow_id)
        if not workflow:
            return jsonify({"error": "Workflow not found"}), 404

        return jsonify({
            "workflow": workflow.to_dict()
        }), 200
    finally:
        db.close()


# ──────────────────────────────────────
# Review / Approve / Refine
# ──────────────────────────────────────

@workflow_bp.route('/api/workflows/<int:workflow_id>/review', methods=['POST'])
def submit_review(workflow_id):
    """
    Submit a review action (approve or refine) for a workflow.

    Request body:
    {
        "action": "approve" | "refine",
        "feedback": "Please add more data about cost analysis...",  (required for refine)
        "user_id": 1,
        "channel": "web"  (optional, defaults to "web")
    }
    """
    db = SessionLocal()
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Request body is required"}), 400

        action = data.get("action")
        feedback = data.get("feedback", "")
        user_id = data.get("user_id")
        channel = data.get("channel", "web")

        if action not in ("approve", "refine"):
            return jsonify({"error": "Action must be 'approve' or 'refine'"}), 400
        if not user_id:
            return jsonify({"error": "user_id is required"}), 400
        if action == "refine" and not feedback.strip():
            return jsonify({"error": "Feedback is required for refinement"}), 400

        # Get the workflow
        workflow = get_workflow_by_id(db, workflow_id)
        if not workflow:
            return jsonify({"error": "Workflow not found"}), 404

        if workflow.status not in ("awaiting_review",):
            return jsonify({
                "error": f"Workflow is not awaiting review (current status: {workflow.status})"
            }), 400

        # Get the reviewer user
        user = get_user_by_id(db, user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404

        # Find the research step to get the accumulated research
        research_step = None
        for step in workflow.steps:
            if step.step_type == "agent_research":
                research_step = step
                break

        if not research_step or not research_step.output_data:
            return jsonify({"error": "No research data found"}), 400

        if action == "approve":
            # ── APPROVE: Mark review as done, start PPT generation ──

            # Update the review step
            review_step = None
            for step in workflow.steps:
                if step.step_type == "human_review":
                    review_step = step
                    break
            if review_step:
                update_step_status(db, review_step.id, "completed")

            # Log the approval event
            create_event(
                db, workflow_id=workflow_id, event_type="approved",
                actor_id=user_id, actor_type="human", channel=channel,
                message=f"Research approved by {user.name}"
            )

            # Extract research text for PPT generation
            research_data = research_step.output_data
            research_text = research_data.get("raw_research") or research_data.get("summary") or ""

            # Start PPT generation in background thread
            start_ppt_generation(workflow_id, research_text, workflow.title)

            return jsonify({
                "message": f"Research approved by {user.name}! PowerPoint generation starting...",
                "workflow": get_workflow_by_id(db, workflow_id).to_dict()
            }), 200

        elif action == "refine":
            # ── REFINE: Log feedback, restart research with context ──

            # Log the refinement event
            create_event(
                db, workflow_id=workflow_id, event_type="refined",
                actor_id=user_id, actor_type="human", channel=channel,
                message=f"Refinement requested by {user.name}: {feedback[:200]}"
            )

            # Start refinement in background thread (uses same session)
            start_refinement(
                workflow_id, feedback, workflow.openclaw_session_id
            )

            return jsonify({
                "message": f"Refinement requested! OpenClaw is updating the research based on your feedback.",
                "workflow": get_workflow_by_id(db, workflow_id).to_dict()
            }), 200

    except Exception as e:
        print(f"Error in review: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ──────────────────────────────────────
# Slack Inbound Interactions
# ──────────────────────────────────────

def _verify_slack_signature(req) -> bool:
    """Verify that the incoming request is actually from Slack."""
    if not SLACK_SIGNING_SECRET or SLACK_SIGNING_SECRET == "your-signing-secret-here":
        print("[Slack] Signing secret not configured — skipping verification")
        return True  # Allow in development

    timestamp = req.headers.get("X-Slack-Request-Timestamp", "")
    signature = req.headers.get("X-Slack-Signature", "")

    # Reject requests older than 5 minutes (replay attack protection)
    if abs(time.time() - int(timestamp)) > 300:
        return False

    sig_basestring = f"v0:{timestamp}:{req.get_data(as_text=True)}"
    my_signature = "v0=" + hmac.new(
        SLACK_SIGNING_SECRET.encode(),
        sig_basestring.encode(),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(my_signature, signature)


@workflow_bp.route('/api/slack/interactions', methods=['POST'])
def handle_slack_interaction():
    """
    Handle interactive button clicks from Slack.
    Responds immediately with 200 and processes the action in a background thread
    to meet Slack's 3-second response requirement.
    """
    # Verify the request is from Slack
    if not _verify_slack_signature(request):
        return jsonify({"error": "Invalid signature"}), 401

    # Parse the Slack payload
    try:
        payload = json.loads(request.form.get("payload", "{}"))
    except json.JSONDecodeError:
        return jsonify({"error": "Invalid payload"}), 400

    # Extract action details
    actions = payload.get("actions", [])
    if not actions:
        return "", 200

    action = actions[0]
    action_id = action.get("action_id", "")
    action_value = json.loads(action.get("value", "{}"))
    slack_user_id = payload.get("user", {}).get("id", "")
    slack_username = payload.get("user", {}).get("username", "Unknown")

    workflow_id = action_value.get("workflow_id")
    if not workflow_id:
        return "", 200

    # Process the action in a background thread (Slack needs a response within 3s)
    if action_id == "approve_research":
        thread = threading.Thread(
            target=_process_slack_approval,
            args=(workflow_id, slack_user_id, slack_username, payload),
            daemon=True
        )
        thread.start()

        # Immediate acknowledgment to Slack
        return jsonify({
            "response_type": "in_channel",
            "text": f"✅ {slack_username} approved the research! PPT generation starting..."
        }), 200

    elif action_id == "refine_research":
        # For refinement, we need feedback text. Send a modal or ask for input.
        # For now, respond with a prompt to use the web app for detailed feedback.
        return jsonify({
            "response_type": "ephemeral",
            "text": (
                "📝 To provide refinement feedback, please use the web app:\n"
                f"http://localhost:5173/workflows/{workflow_id}\n\n"
                "_Detailed feedback input via Slack coming soon!_"
            )
        }), 200

    return "", 200


def _process_slack_approval(workflow_id: int, slack_user_id: str,
                            slack_username: str, payload: dict):
    """Background thread: process a Slack approval (runs after the 200 response)."""
    db = SessionLocal()
    try:
        workflow = get_workflow_by_id(db, workflow_id)
        if not workflow or workflow.status != "awaiting_review":
            print(f"[Slack] Workflow {workflow_id} not in reviewable state")
            return

        # Try to map Slack user to internal user
        from crud import get_all_users
        users = get_all_users(db)
        actor_id = None
        for user in users:
            if user.slack_user_id == slack_user_id:
                actor_id = user.id
                break

        # If no match, use the workflow owner as a fallback
        if not actor_id:
            actor_id = workflow.user_id

        # Mark review step as completed
        for step in workflow.steps:
            if step.step_type == "human_review":
                update_step_status(db, step.id, "completed")
                break

        # Log the approval event
        create_event(
            db, workflow_id=workflow_id, event_type="approved",
            actor_id=actor_id, actor_type="human", channel="slack",
            message=f"Research approved by {slack_username} via Slack",
            metadata_json={"slack_user_id": slack_user_id}
        )

        # Get research text for PPT generation
        research_text = ""
        for step in workflow.steps:
            if step.step_type == "agent_research" and step.output_data:
                research_text = (
                    step.output_data.get("raw_research") or
                    step.output_data.get("summary") or
                    ""
                )
                break

        # Start PPT generation
        start_ppt_generation(workflow_id, research_text, workflow.title)

        print(f"[Slack] Approval processed for workflow {workflow_id}")

    except Exception as e:
        print(f"[Slack] Error processing approval: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


# ──────────────────────────────────────
# Marketplace Endpoints
# ──────────────────────────────────────

@workflow_bp.route('/api/marketplace', methods=['GET'])
def list_marketplace():
    """List all open work requests on the marketplace board."""
    db = SessionLocal()
    try:
        requests = get_open_work_requests(db)
        return jsonify({
            "requests": [r.to_dict() for r in requests]
        }), 200
    finally:
        db.close()


@workflow_bp.route('/api/marketplace', methods=['POST'])
def post_work_request():
    """
    Post a new need to the marketplace.
    Triggers agent auto-selection logic.
    """
    db = SessionLocal()
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Request body missing"}), 400

        # Create the request
        work_request = create_work_request(db, data)

        # ── AGENT AUTO-VOLUNTEER LOGIC ──
        # Check if any agents match the required capabilities
        required_caps = data.get("required_capabilities", [])
        from database.models import User
        agents = db.query(User).filter(User.is_agent == True).all()

        for agent in agents:
            # Simple matching: if agent role matches or "research" is in caps and agent is OpenClaw
            if "research" in required_caps and agent.email == "agent@openclaw.ai":
                create_volunteer(db, {
                    "request_id": work_request.id,
                    "user_id": agent.id,
                    "note": "I'm the OpenClaw research agent. I can perform web searches and generate reports."
                })

        return jsonify({
            "message": "Work request posted to marketplace!",
            "request": work_request.to_dict()
        }), 201
    except Exception as e:
        print(f"Error posting work request: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@workflow_bp.route('/api/marketplace/<int:request_id>', methods=['GET'])
def get_marketplace_detail(request_id):
    """View a specific work request and its volunteers."""
    db = SessionLocal()
    try:
        work_request = get_work_request_by_id(db, request_id)
        if not work_request:
            return jsonify({"error": "Request not found"}), 404
        return jsonify({"request": work_request.to_dict()}), 200
    finally:
        db.close()


@workflow_bp.route('/api/marketplace/<int:request_id>/volunteer', methods=['POST'])
def volunteer_for_task(request_id):
    """A human user manually volunteers for a task."""
    db = SessionLocal()
    try:
        data = request.json
        user_id = data.get("user_id")
        note = data.get("note", "")

        if not user_id:
            return jsonify({"error": "user_id is required"}), 400

        volunteer = create_volunteer(db, {
            "request_id": request_id,
            "user_id": user_id,
            "note": note
        })

        return jsonify({
            "message": "Successfully volunteered!",
            "volunteer": volunteer.to_dict()
        }), 201
    finally:
        db.close()


@workflow_bp.route('/api/marketplace/<int:request_id>/accept', methods=['POST'])
def accept_volunteer(request_id):
    """
    The Handshake: Requester accepts a volunteer to start the work.
    This replaces the old direct-create-workflow logic.
    """
    db = SessionLocal()
    try:
        data = request.json
        volunteer_id = data.get("volunteer_id")

        if not volunteer_id:
            return jsonify({"error": "volunteer_id is required"}), 400

        work_request = get_work_request_by_id(db, request_id)
        volunteer = get_volunteer_by_id(db, volunteer_id)

        if not work_request or not volunteer:
            return jsonify({"error": "Request or Volunteer not found"}), 404

        # 1. Update statuses
        update_volunteer_status(db, volunteer_id, "accepted")
        work_request.status = "assigned"

        # 2. Create the actual Workflow from the request
        user = volunteer.user
        session_id = f"workflow-{generate_session_id()}"

        workflow = create_workflow(
            db,
            user_id=work_request.requester_id,
            title=work_request.title,
            workflow_type="ppt_generation", # Default
            openclaw_session_id=session_id,
            parent_id=work_request.parent_workflow_id
        )

        # 3. Create the first step and assign it
        step_type = "agent_research" if user.is_agent else "human_research"
        provider_type = "agent" if user.is_agent else "human"

        create_workflow_step(
            db, workflow_id=workflow.id, step_order=1,
            step_type=step_type, provider_type=provider_type,
            assigned_to=user.id,
            input_data={"topic": work_request.title, "description": work_request.description}
        )

        # 4. Success event
        create_event(
            db, workflow_id=workflow.id, event_type="created",
            actor_id=work_request.requester_id, actor_type="human", channel="web",
            message=f"Handshake complete! {user.name} is starting work on: {work_request.title}"
        )

        # 5. If it's an agent, trigger the service logic
        if user.is_agent and user.email == "agent@openclaw.ai":
            start_research(workflow.id, work_request.title, session_id)

        db.commit()
        return jsonify({
            "message": "Handshake complete! Work has begun.",
            "workflow_id": workflow.id
        }), 200

    except Exception as e:
        db.rollback()
        print(f"Error accepting volunteer: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ──────────────────────────────────────
# OPTIONS handlers for CORS
# ──────────────────────────────────────

@workflow_bp.route('/api/marketplace', methods=['OPTIONS'])
@workflow_bp.route('/api/marketplace/<int:request_id>', methods=['OPTIONS'])
@workflow_bp.route('/api/marketplace/<int:request_id>/volunteer', methods=['OPTIONS'])
@workflow_bp.route('/api/marketplace/<int:request_id>/accept', methods=['OPTIONS'])
@workflow_bp.route('/api/users', methods=['OPTIONS'])
@workflow_bp.route('/api/workflows', methods=['OPTIONS'])
@workflow_bp.route('/api/workflows/<int:workflow_id>', methods=['OPTIONS'])
@workflow_bp.route('/api/workflows/<int:workflow_id>/review', methods=['OPTIONS'])
@workflow_bp.route('/api/slack/interactions', methods=['OPTIONS'])
def handle_workflow_options(**kwargs):
    """Handle preflight CORS requests for workflow endpoints."""
    from flask import make_response
    response = make_response()
    origin = request.headers.get('Origin')
    if origin in ["http://localhost:5173", "http://localhost:5174"]:
        response.headers['Access-Control-Allow-Origin'] = origin
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response
