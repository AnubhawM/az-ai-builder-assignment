"""
Workflow API Routes — Flask Blueprint for the AIXplore Capability Exchange.

Endpoints:
    GET  /api/users                  — List all personas
    POST /api/workflows              — Create a new workflow (triggers research)
    GET  /api/workflows              — List workflows (filtered by user/role)
    GET  /api/workflows/<id>         — Get full workflow detail
    POST /api/workflows/<id>/review  — Submit approve/refine action
    GET  /api/workflows/<id>/messages — List workflow chat messages
    POST /api/workflows/<id>/messages — Post workflow chat message
    POST /api/workflows/<id>/completion — Mark/reopen collaborative completion
    POST /api/workflows/<id>/generate-ppt — Trigger PPT from chat context
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
    update_volunteer_status, get_volunteer_by_id,
    create_workflow_message, get_messages_for_workflow,
    upsert_workflow_approval, get_workflow_approvals
)
from openclaw_client import generate_session_id
from workflow_service import (
    start_research, start_refinement, start_ppt_generation,
    start_agent_chat_reply
)

workflow_bp = Blueprint('workflows', __name__)

SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")


def _normalize_caps(capabilities: list[str] | None) -> list[str]:
    return [c.strip().lower() for c in (capabilities or []) if isinstance(c, str) and c.strip()]


def _infer_workflow_type(title: str, description: str, required_capabilities: list[str] | None) -> str:
    caps = _normalize_caps(required_capabilities)
    haystack = f"{title} {description} {' '.join(caps)}".lower()

    if any(k in haystack for k in ["compliance", "audit", "regulatory", "policy", "risk"]):
        return "compliance_review"
    if any(k in haystack for k in ["design", "branding", "brand", "logo", "color", "style"]):
        return "design_alignment"
    if any(k in haystack for k in ["research", "ppt", "powerpoint", "slides", "presentation"]):
        return "ppt_generation"
    return "general_collaboration"


def _should_auto_start_agent(required_capabilities: list[str] | None) -> bool:
    caps = set(_normalize_caps(required_capabilities))
    auto_caps = {
        "research", "ppt", "ppt_generation", "powerpoint", "slides", "presentation"
    }
    return bool(caps.intersection(auto_caps))


def _participant_user_ids(workflow) -> set[int]:
    participant_ids = {workflow.user_id}
    for step in workflow.steps:
        if step.assigned_to:
            participant_ids.add(step.assigned_to)
    return participant_ids


def _has_agent_participant(workflow) -> bool:
    for step in workflow.steps:
        assignee = step.assignee
        if assignee and assignee.is_agent:
            return True
        if step.provider_type == "agent":
            return True
    return False


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

        workflow_payload = []
        for workflow in workflows:
            data = workflow.to_dict()
            # Keep list payload lightweight for polling-heavy dashboard views.
            data.pop("messages", None)
            data.pop("approvals", None)
            workflow_payload.append(data)

        return jsonify({
            "workflows": workflow_payload
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
# Workflow Chat + Collaboration Completion
# ──────────────────────────────────────

@workflow_bp.route('/api/workflows/<int:workflow_id>/messages', methods=['GET'])
def list_workflow_messages(workflow_id):
    """List chat messages for a workflow."""
    db = SessionLocal()
    try:
        workflow = get_workflow_by_id(db, workflow_id)
        if not workflow:
            return jsonify({"error": "Workflow not found"}), 404

        user_id = request.args.get("user_id", type=int)
        if user_id and user_id not in _participant_user_ids(workflow):
            return jsonify({"error": "User is not a participant in this workflow"}), 403

        messages = get_messages_for_workflow(db, workflow_id)
        return jsonify({
            "messages": [m.to_dict() for m in messages]
        }), 200
    finally:
        db.close()


@workflow_bp.route('/api/workflows/<int:workflow_id>/messages', methods=['POST'])
def post_workflow_message(workflow_id):
    """Post a chat message to a workflow and optionally trigger an OpenClaw reply."""
    db = SessionLocal()
    try:
        data = request.json or {}
        user_id = data.get("user_id")
        raw_message = data.get("message", "")
        channel = data.get("channel", "web")
        ask_agent = data.get("ask_agent")

        if not user_id:
            return jsonify({"error": "user_id is required"}), 400
        if not raw_message or not str(raw_message).strip():
            return jsonify({"error": "message is required"}), 400

        workflow = get_workflow_by_id(db, workflow_id)
        if not workflow:
            return jsonify({"error": "Workflow not found"}), 404

        user = get_user_by_id(db, user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404

        participant_ids = _participant_user_ids(workflow)
        if user_id not in participant_ids:
            return jsonify({"error": "User is not a participant in this workflow"}), 403

        text = str(raw_message).strip()
        msg = create_workflow_message(
            db,
            workflow_id=workflow_id,
            sender_id=user_id,
            sender_type="agent" if user.is_agent else "human",
            channel=channel,
            message=text
        )
        create_event(
            db, workflow_id=workflow_id, event_type="message_posted",
            actor_id=user_id, actor_type="agent" if user.is_agent else "human",
            channel=channel,
            message=f"{user.name} posted a message"
        )

        has_agent = _has_agent_participant(workflow)
        auto_agent_reply = ask_agent if isinstance(ask_agent, bool) else has_agent
        agent_reply_started = False
        if auto_agent_reply and has_agent and not user.is_agent:
            start_agent_chat_reply(workflow_id, text)
            agent_reply_started = True

        return jsonify({
            "message": "Message posted",
            "chat_message": msg.to_dict(),
            "agent_reply_started": agent_reply_started
        }), 201
    finally:
        db.close()


@workflow_bp.route('/api/workflows/<int:workflow_id>/completion', methods=['POST'])
def update_workflow_completion(workflow_id):
    """
    Mark collaboration readiness for human participants.
    Workflow is auto-completed when all human participants mark ready.
    """
    db = SessionLocal()
    try:
        data = request.json or {}
        user_id = data.get("user_id")
        action = data.get("action")

        if not user_id:
            return jsonify({"error": "user_id is required"}), 400
        if action not in ("mark_ready", "reopen"):
            return jsonify({"error": "action must be mark_ready or reopen"}), 400

        workflow = get_workflow_by_id(db, workflow_id)
        if not workflow:
            return jsonify({"error": "Workflow not found"}), 404

        user = get_user_by_id(db, user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404
        if user_id not in _participant_user_ids(workflow):
            return jsonify({"error": "User is not a participant in this workflow"}), 403
        if user.is_agent:
            return jsonify({"error": "Agents cannot mark human workflow completion"}), 400
        if not workflow.approvals and workflow.workflow_type not in (
            "compliance_review", "design_alignment", "general_collaboration"
        ):
            return jsonify({"error": "This workflow does not use collaborative completion"}), 400

        new_status = "ready" if action == "mark_ready" else "pending"
        upsert_workflow_approval(db, workflow_id, user_id, new_status)

        create_event(
            db, workflow_id=workflow_id,
            event_type="completion_marked" if action == "mark_ready" else "reopened",
            actor_id=user_id, actor_type="human", channel="web",
            message=(
                f"{user.name} marked this collaboration as ready"
                if action == "mark_ready"
                else f"{user.name} reopened the collaboration"
            )
        )

        participant_ids = _participant_user_ids(workflow)
        human_participant_ids = []
        for pid in participant_ids:
            participant = get_user_by_id(db, pid)
            if participant and not participant.is_agent:
                human_participant_ids.append(pid)

        approvals = get_workflow_approvals(db, workflow_id)
        approval_by_user = {a.user_id: a.status for a in approvals}
        all_humans_ready = (
            len(human_participant_ids) >= 2
            and all(approval_by_user.get(pid) == "ready" for pid in human_participant_ids)
        )

        if all_humans_ready:
            update_workflow_status(db, workflow_id, "completed")
            active_step = get_active_step(db, workflow_id)
            if active_step:
                update_step_status(db, active_step.id, "completed")
            create_workflow_message(
                db,
                workflow_id=workflow_id,
                sender_type="system",
                channel="system",
                message="All human participants marked ready. Workflow marked as completed."
            )
            create_event(
                db, workflow_id=workflow_id, event_type="approved",
                actor_type="system", channel="web",
                message="Collaboration approved by all human participants"
            )
        else:
            update_workflow_status(db, workflow_id, "collaborating")

        return jsonify({
            "message": "Completion state updated",
            "workflow": get_workflow_by_id(db, workflow_id).to_dict()
        }), 200
    finally:
        db.close()


@workflow_bp.route('/api/workflows/<int:workflow_id>/generate-ppt', methods=['POST'])
def generate_ppt_from_workflow_chat(workflow_id):
    """Trigger PPT generation from collaborative chat context."""
    db = SessionLocal()
    try:
        data = request.json or {}
        user_id = data.get("user_id")
        instructions = (data.get("instructions") or "").strip()

        if not user_id:
            return jsonify({"error": "user_id is required"}), 400

        workflow = get_workflow_by_id(db, workflow_id)
        if not workflow:
            return jsonify({"error": "Workflow not found"}), 404
        if workflow.status == "generating_ppt":
            return jsonify({"error": "PPT generation is already in progress"}), 400

        user = get_user_by_id(db, user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404
        if user_id not in _participant_user_ids(workflow):
            return jsonify({"error": "User is not a participant in this workflow"}), 403
        if not _has_agent_participant(workflow):
            return jsonify({"error": "No agent collaborator is assigned to this workflow"}), 400

        recent_messages = workflow.messages[-12:] if workflow.messages else []
        context_lines = []
        for msg in recent_messages:
            if msg.sender_type == "system":
                speaker = "System"
            elif msg.sender and msg.sender.name:
                speaker = msg.sender.name
            elif msg.sender_type == "agent":
                speaker = "OpenClaw"
            else:
                speaker = "Human"
            context_lines.append(f"{speaker}: {msg.message}")
        chat_context = "\n".join(context_lines)

        combined_instructions = "\n\n".join(
            part for part in [instructions, f"Chat context:\n{chat_context}"] if part
        )
        if not combined_instructions.strip():
            combined_instructions = workflow.title

        create_workflow_message(
            db,
            workflow_id=workflow_id,
            sender_type="system",
            channel="system",
            message=f"{user.name} requested PPT generation from workflow chat context."
        )
        create_event(
            db, workflow_id=workflow_id, event_type="generation_requested",
            actor_id=user_id, actor_type="human", channel="web",
            message=f"{user.name} requested PPT generation from collaboration chat"
        )

        start_ppt_generation(workflow_id, combined_instructions, workflow.title)

        return jsonify({
            "message": "PPT generation started from workflow chat context.",
            "workflow": get_workflow_by_id(db, workflow_id).to_dict()
        }), 202
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
        required_caps = _normalize_caps(data.get("required_capabilities", []))
        from database.models import User
        agents = db.query(User).filter(User.is_agent == True).all()

        auto_agent_caps = {
            "research", "ppt", "ppt_generation", "powerpoint",
            "slides", "presentation", "design", "branding", "brand"
        }
        should_autovolunteer = bool(set(required_caps).intersection(auto_agent_caps))

        if should_autovolunteer:
            for agent in agents:
                if agent.email != "agent@openclaw.ai":
                    continue
                create_volunteer(db, {
                    "request_id": work_request.id,
                    "user_id": agent.id,
                    "note": (
                        "I can collaborate on research, content refinement, and "
                        "SlideSpeak-based PowerPoint generation."
                    )
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

        work_request = get_work_request_by_id(db, request_id)
        if not work_request:
            return jsonify({"error": "Request not found"}), 404
        if work_request.status != "open":
            return jsonify({"error": "This request is no longer open for volunteers"}), 400

        # Avoid duplicate bids by the same user for the same request
        for existing in work_request.volunteers:
            if existing.user_id == user_id:
                return jsonify({"error": "User has already volunteered for this request"}), 400

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
        data = request.json or {}
        volunteer_id = data.get("volunteer_id")
        requester_id = data.get("user_id")

        if not volunteer_id:
            return jsonify({"error": "volunteer_id is required"}), 400

        work_request = get_work_request_by_id(db, request_id)
        volunteer = get_volunteer_by_id(db, volunteer_id)

        if not work_request or not volunteer:
            return jsonify({"error": "Request or Volunteer not found"}), 404
        if volunteer.request_id != request_id:
            return jsonify({"error": "Volunteer does not belong to this request"}), 400
        if work_request.status != "open":
            return jsonify({"error": f"Request is already {work_request.status}"}), 400
        if volunteer.status != "pending":
            return jsonify({"error": f"Volunteer is already {volunteer.status}"}), 400
        if requester_id and requester_id != work_request.requester_id:
            return jsonify({"error": "Only the requester can accept a volunteer"}), 403

        # 1. Update statuses
        update_volunteer_status(db, volunteer_id, "accepted")
        work_request.status = "assigned"
        for other in work_request.volunteers:
            if other.id != volunteer_id and other.status == "pending":
                update_volunteer_status(db, other.id, "rejected")

        # 2. Create the actual Workflow from the request
        user = volunteer.user
        session_id = f"workflow-{generate_session_id()}"
        workflow_type = _infer_workflow_type(
            work_request.title,
            work_request.description,
            work_request.required_capabilities
        )
        auto_start_agent = user.is_agent and _should_auto_start_agent(work_request.required_capabilities)

        workflow = create_workflow(
            db,
            user_id=work_request.requester_id,
            title=work_request.title,
            workflow_type=workflow_type,
            openclaw_session_id=session_id,
            parent_id=work_request.parent_workflow_id
        )

        # 3. Create the first step and assign it
        if user.is_agent:
            step_type = "agent_research" if auto_start_agent else "agent_collaboration"
        elif workflow_type in ("compliance_review", "design_alignment"):
            step_type = "specialist_review"
        else:
            step_type = "human_research"
        provider_type = "agent" if user.is_agent else "human"

        initial_step = create_workflow_step(
            db, workflow_id=workflow.id, step_order=1,
            step_type=step_type, provider_type=provider_type,
            assigned_to=user.id,
            input_data={
                "topic": work_request.title,
                "description": work_request.description,
                "workflow_type": workflow_type
            }
        )

        # 4. Success event
        create_event(
            db, workflow_id=workflow.id, event_type="created",
            actor_id=work_request.requester_id, actor_type="human", channel="web",
            message=f"Handshake complete! {user.name} is starting work on: {work_request.title}"
        )

        # 5. Seed collaboration chat + approvals for collaborative paths
        if not auto_start_agent:
            update_step_status(db, initial_step.id, "in_progress")
            update_workflow_status(db, workflow.id, "collaborating")
            create_workflow_message(
                db,
                workflow_id=workflow.id,
                sender_type="system",
                channel="system",
                message=(
                    f"{work_request.requester.name} and {user.name} are now connected. "
                    "Use this chat to collaborate, refine, and confirm completion."
                )
            )

        if not user.is_agent:
            upsert_workflow_approval(db, workflow.id, work_request.requester_id, "pending")
            upsert_workflow_approval(db, workflow.id, user.id, "pending")

        # 6. If it's an auto-start agent workflow, trigger service logic immediately
        if auto_start_agent and user.email == "agent@openclaw.ai":
            start_research(
                workflow.id,
                work_request.title,
                session_id,
                request_description=work_request.description or ""
            )

        db.commit()
        return jsonify({
            "message": "Handshake complete! Work has begun.",
            "workflow_id": workflow.id,
            "workflow_type": workflow.workflow_type
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
@workflow_bp.route('/api/workflows/<int:workflow_id>/messages', methods=['OPTIONS'])
@workflow_bp.route('/api/workflows/<int:workflow_id>/completion', methods=['OPTIONS'])
@workflow_bp.route('/api/workflows/<int:workflow_id>/generate-ppt', methods=['OPTIONS'])
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
