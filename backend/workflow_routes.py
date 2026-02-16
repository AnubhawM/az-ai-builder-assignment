"""
Workflow API Routes — Flask Blueprint for the AIXplore Capability Exchange.

Endpoints:
    GET  /api/users                  — List all personas
    POST /api/workflows              — Create a new workflow (triggers research)
    GET  /api/workflows              — List workflows (filtered by user/role)
    GET  /api/workflows/<id>         — Get full workflow detail
    GET  /api/workflows/<id>/attachments — List uploaded workflow attachments
    POST /api/workflows/<id>/attachments — Upload workflow attachment (.pdf/.txt/.ppt/.pptx)
    GET  /api/workflows/<id>/attachments/<filename> — Download workflow attachment
    GET  /api/workflows/<id>/submission-documents — List uploaded submission documents
    POST /api/workflows/<id>/submission-documents — Upload submission document (.pdf/.txt/.ppt/.pptx)
    GET  /api/workflows/<id>/submission-documents/<filename> — Download submission document
    DELETE /api/workflows/<id>       — Delete a workflow owned by the requester
    POST /api/workflows/<id>/review  — Submit approve/refine action
    GET  /api/workflows/<id>/messages — List workflow chat messages
    POST /api/workflows/<id>/messages — Post workflow chat message
    POST /api/workflows/<id>/completion — Mark/reopen collaborative completion
    POST /api/workflows/<id>/generate-ppt — Trigger PPT from chat context
    POST /api/workflows/<id>/cancel-run — Cancel an active run
    POST /api/workflows/<id>/retry-run — Retry a failed/stalled run
    POST /api/slack/interactions     — Handle inbound Slack button clicks
"""

import os
import json
import time
import hmac
import hashlib
import threading
import shutil
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, send_file
from werkzeug.utils import secure_filename

from database import SessionLocal
from crud import (
    get_all_users, get_user_by_id,
    create_workflow, get_workflow_by_id,
    get_all_workflows,
    delete_workflow,
    update_workflow_status,
    create_workflow_step, get_active_step,
    update_step_status,
    create_event,
    get_open_work_requests, get_work_request_by_id,
    create_work_request, create_volunteer,
    get_pending_invites_for_user,
    get_volunteer_by_id,
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


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


RUNNING_WORKFLOW_STATUSES = {"researching", "refining", "generating_ppt"}
RUN_STALE_TIMEOUT_SECONDS = max(180, _env_int("WORKFLOW_RUN_STALE_TIMEOUT_SECONDS", 330))
WORKFLOW_UPLOADS_DIR = os.getenv(
    "WORKFLOW_UPLOADS_DIR",
    os.path.join(os.path.dirname(__file__), "uploads", "workflows")
)
WORKFLOW_SUBMISSION_UPLOADS_DIR = os.getenv(
    "WORKFLOW_SUBMISSION_UPLOADS_DIR",
    os.path.join(os.path.dirname(__file__), "uploads", "workflow_submissions")
)
WORKFLOW_ATTACHMENT_MAX_BYTES = max(1024, _env_int("WORKFLOW_ATTACHMENT_MAX_BYTES", 15 * 1024 * 1024))
WORKFLOW_ATTACHMENT_ALLOWED_EXTENSIONS = {".pdf", ".txt", ".ppt", ".pptx"}
DOCUMENT_ATTACHMENT_EXTENSIONS = {".pdf", ".txt"}
MAX_DOCUMENT_CONTEXT_CHARS = max(2000, _env_int("MAX_DOCUMENT_CONTEXT_CHARS", 45000))
MAX_DOCUMENT_FILES = max(1, _env_int("MAX_DOCUMENT_FILES", 6))
MARKETPLACE_REQUEST_UPLOADS_DIR = os.getenv(
    "MARKETPLACE_REQUEST_UPLOADS_DIR",
    os.path.join(os.path.dirname(__file__), "uploads", "marketplace")
)


def _normalize_caps(capabilities: list[str] | None) -> list[str]:
    return [c.strip().lower() for c in (capabilities or []) if isinstance(c, str) and c.strip()]


def _workflow_upload_dir(workflow_id: int) -> str:
    return os.path.join(WORKFLOW_UPLOADS_DIR, str(workflow_id))


def _workflow_submission_upload_dir(workflow_id: int) -> str:
    return os.path.join(WORKFLOW_SUBMISSION_UPLOADS_DIR, str(workflow_id))


def _request_upload_dir(request_id: int) -> str:
    return os.path.join(MARKETPLACE_REQUEST_UPLOADS_DIR, str(request_id))


def _is_allowed_attachment(filename: str) -> bool:
    _, ext = os.path.splitext((filename or "").lower())
    return ext in WORKFLOW_ATTACHMENT_ALLOWED_EXTENSIONS


def _attachment_display_name(stored_filename: str) -> str:
    if "__" in stored_filename:
        return stored_filename.split("__", 1)[1]
    return stored_filename


def _list_attachments_in_dir(base_dir: str) -> list[dict]:
    if not os.path.isdir(base_dir):
        return []

    attachments = []
    for filename in os.listdir(base_dir):
        file_path = os.path.join(base_dir, filename)
        if not os.path.isfile(file_path):
            continue
        _, ext = os.path.splitext(filename.lower())
        stat = os.stat(file_path)
        attachments.append({
            "filename": filename,
            "display_name": _attachment_display_name(filename),
            "extension": ext,
            "size_bytes": stat.st_size,
            "size_formatted": f"{stat.st_size / 1024:.1f} KB",
            "uploaded_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "_path": file_path,
            "_mtime": stat.st_mtime,
        })

    attachments.sort(key=lambda item: item["_mtime"], reverse=True)
    return attachments


def _list_workflow_attachments(workflow_id: int) -> list[dict]:
    return _list_attachments_in_dir(_workflow_upload_dir(workflow_id))


def _list_request_attachments(request_id: int) -> list[dict]:
    return _list_attachments_in_dir(_request_upload_dir(request_id))


def _list_workflow_submission_attachments(workflow_id: int) -> list[dict]:
    return _list_attachments_in_dir(_workflow_submission_upload_dir(workflow_id))


def _serialize_attachments(items: list[dict]) -> list[dict]:
    return [
        {
            "filename": item["filename"],
            "display_name": item["display_name"],
            "extension": item["extension"],
            "size_bytes": item["size_bytes"],
            "size_formatted": item["size_formatted"],
            "uploaded_at": item["uploaded_at"],
        }
        for item in items
    ]


def _parse_json_list_field(raw_value) -> list:
    if raw_value is None:
        return []
    if isinstance(raw_value, list):
        return raw_value
    if not isinstance(raw_value, str):
        return []
    text = raw_value.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass
    return [part.strip() for part in text.split(",") if part.strip()]


def _validate_attachments(uploads: list) -> tuple[bool, str | None]:
    for upload in uploads:
        original_name = (upload.filename or "").strip()
        safe_name = secure_filename(original_name)
        if not safe_name:
            return False, "Invalid attachment filename."
        if not _is_allowed_attachment(safe_name):
            return False, "Only .pdf, .txt, .ppt, and .pptx files are supported"
        upload.stream.seek(0, os.SEEK_END)
        size_bytes = upload.stream.tell()
        upload.stream.seek(0)
        if size_bytes > WORKFLOW_ATTACHMENT_MAX_BYTES:
            max_mb = WORKFLOW_ATTACHMENT_MAX_BYTES // (1024 * 1024)
            return False, f"Attachment '{safe_name}' exceeds max size of {max_mb} MB."
    return True, None


def _save_attachments_to_dir(target_dir: str, uploads: list) -> list[dict]:
    os.makedirs(target_dir, exist_ok=True)
    saved = []
    for upload in uploads:
        safe_name = secure_filename((upload.filename or "").strip())
        if not safe_name:
            continue

        stored_name = f"{int(time.time())}__{safe_name}"
        target_path = os.path.join(target_dir, stored_name)
        suffix = 1
        while os.path.exists(target_path):
            stored_name = f"{int(time.time())}_{suffix}__{safe_name}"
            target_path = os.path.join(target_dir, stored_name)
            suffix += 1

        upload.save(target_path)
        stat = os.stat(target_path)
        saved.append({
            "filename": stored_name,
            "display_name": safe_name,
            "extension": os.path.splitext(safe_name.lower())[1],
            "size_bytes": stat.st_size,
            "size_formatted": f"{stat.st_size / 1024:.1f} KB",
            "uploaded_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "_path": target_path,
        })
    return saved


def _copy_request_attachments_to_workflow(request_id: int, workflow_id: int) -> list[str]:
    source_items = _list_request_attachments(request_id)
    if not source_items:
        return []

    target_dir = _workflow_upload_dir(workflow_id)
    os.makedirs(target_dir, exist_ok=True)
    copied_names: list[str] = []

    for item in source_items:
        src = item["_path"]
        if not os.path.isfile(src):
            continue
        dest_name = item["filename"]
        dest_path = os.path.join(target_dir, dest_name)
        suffix = 1
        while os.path.exists(dest_path):
            dest_name = f"{int(time.time())}_{suffix}__{item['display_name']}"
            dest_path = os.path.join(target_dir, dest_name)
            suffix += 1
        shutil.copy2(src, dest_path)
        copied_names.append(item["display_name"])

    return copied_names


def _work_request_payload(work_request) -> dict:
    payload = work_request.to_dict()
    payload["attachments"] = _serialize_attachments(_list_request_attachments(work_request.id))
    return payload


def _extract_document_text(file_path: str, extension: str) -> str:
    if extension == ".txt":
        with open(file_path, "r", encoding="utf-8", errors="ignore") as handle:
            return handle.read()

    if extension == ".pdf":
        try:
            from pypdf import PdfReader
        except Exception as exc:
            raise RuntimeError("PDF parsing requires pypdf to be installed.") from exc

        reader = PdfReader(file_path)
        chunks: list[str] = []
        for page in reader.pages:
            try:
                chunks.append(page.extract_text() or "")
            except Exception:
                continue
        return "\n\n".join(chunk for chunk in chunks if chunk.strip())

    return ""


def _build_uploaded_document_context(workflow_id: int) -> tuple[str, list[str]]:
    attachments = _list_workflow_attachments(workflow_id)
    document_attachments = [
        item for item in attachments
        if item["extension"] in DOCUMENT_ATTACHMENT_EXTENSIONS
    ][:MAX_DOCUMENT_FILES]

    if not document_attachments:
        return "", []

    included_docs: list[str] = []
    sections: list[str] = []
    remaining_chars = MAX_DOCUMENT_CONTEXT_CHARS

    for item in document_attachments:
        if remaining_chars <= 0:
            break
        text = _extract_document_text(item["_path"], item["extension"])
        text = (text or "").strip()
        if not text:
            continue

        excerpt = text[:remaining_chars]
        remaining_chars -= len(excerpt)
        included_docs.append(item["display_name"])
        sections.append(f"SOURCE DOCUMENT: {item['display_name']}\n{excerpt}")

    if not sections:
        return "", []

    return "\n\n---\n\n".join(sections), included_docs


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


def _get_request_description(workflow) -> str:
    """Return requester description captured in step input payloads."""
    ordered_steps = sorted(
        workflow.steps,
        key=lambda step: ((step.step_order or 0), (step.id or 0))
    )
    for step in ordered_steps:
        payload = step.input_data or {}
        if not isinstance(payload, dict):
            continue
        desc = payload.get("description")
        if isinstance(desc, str) and desc.strip():
            return desc.strip()
    return ""


def _get_primary_focus(workflow) -> str:
    """
    Description-first focus for both research and PPT generation.
    Falls back to title when no description exists.
    """
    description = _get_request_description(workflow)
    return description or (workflow.title or "").strip()


def _as_utc(dt: datetime | None) -> datetime | None:
    if not dt:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _get_latest_step_by_type(workflow, step_type: str):
    matches = [step for step in workflow.steps if step.step_type == step_type]
    if not matches:
        return None
    matches.sort(key=lambda step: ((step.step_order or 0), (step.id or 0)))
    return matches[-1]


def _get_latest_research_step_with_output(workflow):
    ordered_steps = sorted(
        workflow.steps,
        key=lambda step: ((step.step_order or 0), (step.id or 0))
    )
    for step in reversed(ordered_steps):
        if step.step_type == "agent_research" and isinstance(step.output_data, dict) and step.output_data:
            return step
    return None


def _get_operation_step_for_status(workflow):
    if workflow.status in ("researching", "refining"):
        return _get_latest_step_by_type(workflow, "agent_research")
    if workflow.status == "generating_ppt":
        return _get_latest_step_by_type(workflow, "agent_generation")
    return None


def _build_chat_context(workflow, limit: int = 12) -> str:
    recent_messages = workflow.messages[-limit:] if workflow.messages else []
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
    return "\n".join(context_lines)


def _get_recent_refinement_feedback(workflow, limit: int = 6) -> list[str]:
    feedback_items: list[str] = []
    ordered_events = sorted(
        workflow.events,
        key=lambda event: ((event.created_at or datetime.min), (event.id or 0))
    )
    for event in ordered_events:
        if event.event_type != "refined":
            continue
        message = (event.message or "").strip()
        if not message:
            continue
        if ":" in message:
            message = message.split(":", 1)[1].strip()
        if message:
            feedback_items.append(message)
    return feedback_items[-limit:]


def _build_generation_research_context(workflow, research_step, include_chat: bool = True) -> str:
    payload = research_step.output_data if research_step and isinstance(research_step.output_data, dict) else {}
    sections: list[str] = []

    summary = (payload.get("summary") or "").strip()
    slide_outline = (payload.get("slide_outline") or "").strip()
    raw_research = (payload.get("raw_research") or "").strip()

    if summary:
        sections.append(f"EXECUTIVE SUMMARY:\n{summary}")
    if slide_outline:
        sections.append(f"SLIDE OUTLINE (TARGET STRUCTURE):\n{slide_outline}")
    if raw_research:
        sections.append(f"RAW RESEARCH DETAILS:\n{raw_research}")

    refinement_feedback = _get_recent_refinement_feedback(workflow)
    if refinement_feedback:
        sections.append(
            "REFINEMENT REQUIREMENTS (MUST BE SATISFIED):\n"
            + "\n".join(f"- {item}" for item in refinement_feedback)
        )

    if include_chat:
        chat_context = _build_chat_context(workflow, limit=14)
        if chat_context:
            sections.append(f"COLLABORATION CHAT CONTEXT:\n{chat_context}")

    if not sections:
        return _get_primary_focus(workflow)
    return "\n\n".join(sections)


def _maybe_fail_stalled_workflow(db, workflow):
    """
    Auto-fail stale runs so UI/actions never stay stuck indefinitely.
    Triggered opportunistically during normal API reads/writes.
    """
    if not workflow or workflow.status not in RUNNING_WORKFLOW_STATUSES:
        return workflow

    updated_at = _as_utc(workflow.updated_at)
    if not updated_at:
        return workflow

    elapsed_seconds = (datetime.now(timezone.utc) - updated_at).total_seconds()
    if elapsed_seconds < RUN_STALE_TIMEOUT_SECONDS:
        return workflow

    timeout_minutes = max(1, RUN_STALE_TIMEOUT_SECONDS // 60)
    stale_message = (
        f"{workflow.status.replace('_', ' ').title()} timed out after "
        f"{timeout_minutes} minutes with no progress."
    )
    op_step = _get_operation_step_for_status(workflow)
    if op_step and op_step.status in ("pending", "in_progress", "awaiting_input"):
        existing_output = op_step.output_data if isinstance(op_step.output_data, dict) else {}
        failed_output = {
            **existing_output,
            "error": stale_message,
            "timed_out": True,
        }
        update_step_status(db, op_step.id, "failed", output_data=failed_output)

    update_workflow_status(db, workflow.id, "failed")
    create_workflow_message(
        db,
        workflow_id=workflow.id,
        sender_type="system",
        channel="system",
        message=f"{stale_message} Marked as failed automatically. You can retry the run."
    )
    create_event(
        db, workflow_id=workflow.id, event_type="failed",
        actor_type="system", step_id=op_step.id if op_step else None,
        channel="system",
        message=stale_message,
        metadata_json={
            "timed_out": True,
            "timeout_seconds": RUN_STALE_TIMEOUT_SECONDS,
        }
    )
    return get_workflow_by_id(db, workflow.id)


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
        start_research(
            workflow.id,
            topic,
            session_id,
            research_step_id=research_step.id
        )

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
        - user_id: Required. Returns workflows where this user is a participant.
    """
    db = SessionLocal()
    try:
        user_id = request.args.get("user_id", type=int)
        if not user_id:
            return jsonify({"error": "user_id is required"}), 400

        workflows = get_all_workflows(db)
        workflows = [w for w in workflows if user_id in _participant_user_ids(w)]

        workflow_payload = []
        for workflow in workflows:
            workflow = _maybe_fail_stalled_workflow(db, workflow)
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
        user_id = request.args.get("user_id", type=int)
        if not user_id:
            return jsonify({"error": "user_id is required"}), 400

        workflow = get_workflow_by_id(db, workflow_id)
        if not workflow:
            return jsonify({"error": "Workflow not found"}), 404
        if user_id not in _participant_user_ids(workflow):
            return jsonify({"error": "User is not a participant in this workflow"}), 403
        workflow = _maybe_fail_stalled_workflow(db, workflow)

        return jsonify({
            "workflow": workflow.to_dict()
        }), 200
    finally:
        db.close()


@workflow_bp.route('/api/workflows/<int:workflow_id>/attachments', methods=['GET'])
def list_workflow_attachments(workflow_id):
    """List uploaded attachments for a workflow."""
    db = SessionLocal()
    try:
        user_id = request.args.get("user_id", type=int)
        if not user_id:
            return jsonify({"error": "user_id is required"}), 400

        workflow = get_workflow_by_id(db, workflow_id)
        if not workflow:
            return jsonify({"error": "Workflow not found"}), 404
        if user_id not in _participant_user_ids(workflow):
            return jsonify({"error": "User is not a participant in this workflow"}), 403

        items = _list_workflow_attachments(workflow_id)
        payload = [
            {
                "filename": item["filename"],
                "display_name": item["display_name"],
                "extension": item["extension"],
                "size_bytes": item["size_bytes"],
                "size_formatted": item["size_formatted"],
                "uploaded_at": item["uploaded_at"],
            }
            for item in items
        ]
        return jsonify({"attachments": payload}), 200
    finally:
        db.close()


@workflow_bp.route('/api/workflows/<int:workflow_id>/attachments', methods=['POST'])
def upload_workflow_attachment(workflow_id):
    """Upload a local attachment (PDF/TXT/PPT/PPTX) for workflow collaboration."""
    db = SessionLocal()
    try:
        user_id_raw = request.form.get("user_id")
        if user_id_raw is None:
            return jsonify({"error": "user_id is required"}), 400
        try:
            user_id = int(user_id_raw)
        except (TypeError, ValueError):
            return jsonify({"error": "user_id must be a number"}), 400

        workflow = get_workflow_by_id(db, workflow_id)
        if not workflow:
            return jsonify({"error": "Workflow not found"}), 404
        if user_id not in _participant_user_ids(workflow):
            return jsonify({"error": "User is not a participant in this workflow"}), 403

        upload = request.files.get("file")
        if not upload or not upload.filename:
            return jsonify({"error": "file is required"}), 400

        original_name = upload.filename.strip()
        safe_name = secure_filename(original_name)
        if not safe_name:
            return jsonify({"error": "Invalid filename"}), 400
        if not _is_allowed_attachment(safe_name):
            return jsonify({"error": "Only .pdf, .txt, .ppt, and .pptx files are supported"}), 400

        upload.stream.seek(0, os.SEEK_END)
        size_bytes = upload.stream.tell()
        upload.stream.seek(0)
        if size_bytes > WORKFLOW_ATTACHMENT_MAX_BYTES:
            return jsonify({
                "error": f"File too large. Max allowed is {WORKFLOW_ATTACHMENT_MAX_BYTES // (1024 * 1024)} MB."
            }), 400

        os.makedirs(_workflow_upload_dir(workflow_id), exist_ok=True)
        stored_name = f"{int(time.time())}__{safe_name}"
        target_path = os.path.join(_workflow_upload_dir(workflow_id), stored_name)
        suffix = 1
        while os.path.exists(target_path):
            stored_name = f"{int(time.time())}_{suffix}__{safe_name}"
            target_path = os.path.join(_workflow_upload_dir(workflow_id), stored_name)
            suffix += 1

        upload.save(target_path)

        actor = get_user_by_id(db, user_id)
        actor_name = actor.name if actor else f"User {user_id}"
        create_workflow_message(
            db,
            workflow_id=workflow_id,
            sender_id=user_id,
            sender_type="human",
            channel="web",
            message=f"{actor_name} uploaded a document: {safe_name}",
            metadata_json={
                "attachment_filename": stored_name,
                "attachment_display_name": safe_name
            }
        )
        create_event(
            db,
            workflow_id=workflow_id,
            event_type="message_posted",
            actor_id=user_id,
            actor_type="human",
            channel="web",
            message=f"Document uploaded: {safe_name}",
            metadata_json={
                "attachment_filename": stored_name,
                "attachment_display_name": safe_name
            }
        )

        stat = os.stat(target_path)
        return jsonify({
            "message": "Attachment uploaded",
            "attachment": {
                "filename": stored_name,
                "display_name": safe_name,
                "extension": os.path.splitext(safe_name.lower())[1],
                "size_bytes": stat.st_size,
                "size_formatted": f"{stat.st_size / 1024:.1f} KB",
                "uploaded_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            }
        }), 201
    finally:
        db.close()


@workflow_bp.route('/api/workflows/<int:workflow_id>/attachments/<path:filename>', methods=['GET'])
def download_workflow_attachment(workflow_id, filename):
    """Download an uploaded workflow attachment."""
    db = SessionLocal()
    try:
        user_id = request.args.get("user_id", type=int)
        if not user_id:
            return jsonify({"error": "user_id is required"}), 400

        workflow = get_workflow_by_id(db, workflow_id)
        if not workflow:
            return jsonify({"error": "Workflow not found"}), 404
        if user_id not in _participant_user_ids(workflow):
            return jsonify({"error": "User is not a participant in this workflow"}), 403

        safe_filename = os.path.basename(filename)
        if not safe_filename or safe_filename != filename:
            return jsonify({"error": "Invalid filename"}), 400

        file_path = os.path.join(_workflow_upload_dir(workflow_id), safe_filename)
        if not os.path.isfile(file_path):
            return jsonify({"error": "Attachment not found"}), 404

        return send_file(
            file_path,
            as_attachment=True,
            download_name=_attachment_display_name(safe_filename)
        )
    finally:
        db.close()


@workflow_bp.route('/api/workflows/<int:workflow_id>/submission-documents', methods=['GET'])
def list_submission_documents(workflow_id):
    """List uploaded submission documents for a workflow."""
    db = SessionLocal()
    try:
        user_id = request.args.get("user_id", type=int)
        if not user_id:
            return jsonify({"error": "user_id is required"}), 400

        workflow = get_workflow_by_id(db, workflow_id)
        if not workflow:
            return jsonify({"error": "Workflow not found"}), 404
        if user_id not in _participant_user_ids(workflow):
            return jsonify({"error": "User is not a participant in this workflow"}), 403

        items = _list_workflow_submission_attachments(workflow_id)
        return jsonify({"documents": _serialize_attachments(items)}), 200
    finally:
        db.close()


@workflow_bp.route('/api/workflows/<int:workflow_id>/submission-documents', methods=['POST'])
def upload_submission_document(workflow_id):
    """Upload a local submission document for workflow delivery/review."""
    db = SessionLocal()
    try:
        user_id_raw = request.form.get("user_id")
        if user_id_raw is None:
            return jsonify({"error": "user_id is required"}), 400
        try:
            user_id = int(user_id_raw)
        except (TypeError, ValueError):
            return jsonify({"error": "user_id must be a number"}), 400

        workflow = get_workflow_by_id(db, workflow_id)
        if not workflow:
            return jsonify({"error": "Workflow not found"}), 404
        if user_id not in _participant_user_ids(workflow):
            return jsonify({"error": "User is not a participant in this workflow"}), 403

        upload = request.files.get("file")
        if not upload or not upload.filename:
            return jsonify({"error": "file is required"}), 400

        original_name = upload.filename.strip()
        safe_name = secure_filename(original_name)
        if not safe_name:
            return jsonify({"error": "Invalid filename"}), 400
        if not _is_allowed_attachment(safe_name):
            return jsonify({"error": "Only .pdf, .txt, .ppt, and .pptx files are supported"}), 400

        upload.stream.seek(0, os.SEEK_END)
        size_bytes = upload.stream.tell()
        upload.stream.seek(0)
        if size_bytes > WORKFLOW_ATTACHMENT_MAX_BYTES:
            return jsonify({
                "error": f"File too large. Max allowed is {WORKFLOW_ATTACHMENT_MAX_BYTES // (1024 * 1024)} MB."
            }), 400

        os.makedirs(_workflow_submission_upload_dir(workflow_id), exist_ok=True)
        stored_name = f"{int(time.time())}__{safe_name}"
        target_path = os.path.join(_workflow_submission_upload_dir(workflow_id), stored_name)
        suffix = 1
        while os.path.exists(target_path):
            stored_name = f"{int(time.time())}_{suffix}__{safe_name}"
            target_path = os.path.join(_workflow_submission_upload_dir(workflow_id), stored_name)
            suffix += 1

        upload.save(target_path)

        actor = get_user_by_id(db, user_id)
        actor_name = actor.name if actor else f"User {user_id}"
        create_workflow_message(
            db,
            workflow_id=workflow_id,
            sender_id=user_id,
            sender_type="human",
            channel="web",
            message=f"{actor_name} uploaded a submission document: {safe_name}",
            metadata_json={
                "submission_document_filename": stored_name,
                "submission_document_display_name": safe_name
            }
        )
        create_event(
            db,
            workflow_id=workflow_id,
            event_type="message_posted",
            actor_id=user_id,
            actor_type="human",
            channel="web",
            message=f"Submission document uploaded: {safe_name}",
            metadata_json={
                "submission_document_filename": stored_name,
                "submission_document_display_name": safe_name
            }
        )

        stat = os.stat(target_path)
        return jsonify({
            "message": "Submission document uploaded",
            "document": {
                "filename": stored_name,
                "display_name": safe_name,
                "extension": os.path.splitext(safe_name.lower())[1],
                "size_bytes": stat.st_size,
                "size_formatted": f"{stat.st_size / 1024:.1f} KB",
                "uploaded_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            }
        }), 201
    finally:
        db.close()


@workflow_bp.route('/api/workflows/<int:workflow_id>/submission-documents/<path:filename>', methods=['GET'])
def download_submission_document(workflow_id, filename):
    """Download an uploaded workflow submission document."""
    db = SessionLocal()
    try:
        user_id = request.args.get("user_id", type=int)
        if not user_id:
            return jsonify({"error": "user_id is required"}), 400

        workflow = get_workflow_by_id(db, workflow_id)
        if not workflow:
            return jsonify({"error": "Workflow not found"}), 404
        if user_id not in _participant_user_ids(workflow):
            return jsonify({"error": "User is not a participant in this workflow"}), 403

        safe_filename = os.path.basename(filename)
        if not safe_filename or safe_filename != filename:
            return jsonify({"error": "Invalid filename"}), 400

        file_path = os.path.join(_workflow_submission_upload_dir(workflow_id), safe_filename)
        if not os.path.isfile(file_path):
            return jsonify({"error": "Submission document not found"}), 404

        return send_file(
            file_path,
            as_attachment=True,
            download_name=_attachment_display_name(safe_filename)
        )
    finally:
        db.close()


@workflow_bp.route('/api/workflows/<int:workflow_id>', methods=['DELETE'])
def delete_workflow_route(workflow_id):
    """Delete a workflow from dashboard listings."""
    db = SessionLocal()
    try:
        payload = request.get_json(silent=True) or {}
        user_id_raw = payload.get("user_id")
        if user_id_raw is None:
            user_id_raw = request.args.get("user_id", type=int)
        if user_id_raw is None:
            return jsonify({"error": "user_id is required"}), 400
        try:
            user_id = int(user_id_raw)
        except (TypeError, ValueError):
            return jsonify({"error": "user_id must be a number"}), 400

        workflow = get_workflow_by_id(db, workflow_id)
        if not workflow:
            return jsonify({"error": "Workflow not found"}), 404

        workflow = _maybe_fail_stalled_workflow(db, workflow)

        if user_id != workflow.user_id:
            return jsonify({"error": "Only the workflow owner can delete this workflow"}), 403

        if workflow.status in RUNNING_WORKFLOW_STATUSES:
            return jsonify({
                "error": (
                    "Workflow is currently running. Cancel the active run before deleting."
                )
            }), 400

        delete_workflow(db, workflow)
        return jsonify({"message": "Workflow deleted"}), 200
    except Exception as e:
        db.rollback()
        print(f"Error deleting workflow {workflow_id}: {e}")
        return jsonify({"error": str(e)}), 500
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
        "generation_options": {"verbosity": "concise|standard|text-heavy"},  (optional; approve only)
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
        generation_options = data.get("generation_options") or {}
        user_id = data.get("user_id")
        channel = data.get("channel", "web")

        if action not in ("approve", "refine"):
            return jsonify({"error": "Action must be 'approve' or 'refine'"}), 400
        if not user_id:
            return jsonify({"error": "user_id is required"}), 400
        if action == "refine" and not feedback.strip():
            return jsonify({"error": "Feedback is required for refinement"}), 400
        if generation_options and not isinstance(generation_options, dict):
            return jsonify({"error": "generation_options must be an object"}), 400

        # Get the workflow
        workflow = get_workflow_by_id(db, workflow_id)
        if not workflow:
            return jsonify({"error": "Workflow not found"}), 404

        # Get the reviewer user
        user = get_user_by_id(db, user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404
        if user_id not in _participant_user_ids(workflow):
            return jsonify({"error": "User is not a participant in this workflow"}), 403
        workflow = _maybe_fail_stalled_workflow(db, workflow)

        if action == "approve" and workflow.status != "awaiting_review":
            return jsonify({
                "error": f"Approve is only allowed in awaiting_review (current status: {workflow.status})"
            }), 400
        if action == "refine" and workflow.status not in ("awaiting_review", "completed"):
            return jsonify({
                "error": (
                    "Refinement is only allowed in awaiting_review or completed "
                    f"(current status: {workflow.status})"
                )
            }), 400

        # Find latest research output and current review step.
        research_step = _get_latest_research_step_with_output(workflow)
        review_step = _get_latest_step_by_type(workflow, "human_review")

        if not research_step or not research_step.output_data:
            return jsonify({"error": "No research data found"}), 400
        if review_step and review_step.assigned_to and review_step.assigned_to != user_id:
            return jsonify({"error": "Only the assigned reviewer can submit this review"}), 403

        if action == "approve":
            verbosity_override = str(generation_options.get("verbosity") or "").strip().lower()
            allowed_verbosity = {"concise", "standard", "text-heavy"}
            if verbosity_override and verbosity_override not in allowed_verbosity:
                return jsonify({
                    "error": "generation_options.verbosity must be one of concise, standard, text-heavy"
                }), 400

            # ── APPROVE: Mark review as done, start PPT generation ──

            # Update the review step
            if review_step:
                update_step_status(db, review_step.id, "completed")

            # Log the approval event
            create_event(
                db, workflow_id=workflow_id, event_type="approved",
                actor_id=user_id, actor_type="human", channel=channel,
                message=f"Research approved by {user.name}"
            )

            # Build rich research+outline+refinement context for PPT generation.
            research_text = _build_generation_research_context(workflow, research_step)
            presentation_focus = _get_primary_focus(workflow)

            # Start PPT generation in background thread
            start_ppt_generation(
                workflow_id,
                research_text,
                presentation_focus,
                filename_hint=workflow.title,
                generation_overrides={"verbosity": verbosity_override} if verbosity_override else None
            )

            return jsonify({
                "message": f"Research approved by {user.name}! PowerPoint generation starting...",
                "workflow": get_workflow_by_id(db, workflow_id).to_dict()
            }), 200

        elif action == "refine":
            # ── REFINE: Log feedback, restart research with context ──
            was_completed = workflow.status == "completed"

            # If refining after completion, reopen the previous generation stage and linked request.
            if was_completed:
                latest_generation_step = _get_latest_step_by_type(workflow, "agent_generation")
                if latest_generation_step and latest_generation_step.status == "completed":
                    update_step_status(db, latest_generation_step.id, "pending")

                linked_request_id = None
                for step in workflow.steps:
                    payload = step.input_data or {}
                    if isinstance(payload, dict) and payload.get("request_id"):
                        linked_request_id = payload.get("request_id")
                        break
                if linked_request_id:
                    linked_request = get_work_request_by_id(db, linked_request_id)
                    if linked_request and linked_request.status == "completed":
                        linked_request.status = "assigned"

            if review_step:
                update_step_status(db, review_step.id, "completed", feedback=feedback)

            # Log the refinement event
            create_event(
                db, workflow_id=workflow_id, event_type="refined",
                actor_id=user_id, actor_type="human", channel=channel,
                message=f"Refinement requested by {user.name}: {feedback[:200]}"
            )
            if was_completed:
                create_event(
                    db, workflow_id=workflow_id, event_type="reopened",
                    actor_id=user_id, actor_type="human", channel=channel,
                    message=f"{user.name} reopened the workflow for further refinement"
                )

            update_workflow_status(db, workflow_id, "refining")

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
        if not user_id:
            return jsonify({"error": "user_id is required"}), 400
        if user_id not in _participant_user_ids(workflow):
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
        linked_request_id = None
        for step in workflow.steps:
            payload = step.input_data or {}
            if isinstance(payload, dict) and payload.get("request_id"):
                linked_request_id = payload.get("request_id")
                break

        if all_humans_ready:
            if linked_request_id:
                linked_request = get_work_request_by_id(db, linked_request_id)
                if linked_request and linked_request.status != "completed":
                    linked_request.status = "completed"

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
            if linked_request_id:
                linked_request = get_work_request_by_id(db, linked_request_id)
                if linked_request and linked_request.status == "completed":
                    linked_request.status = "assigned"
            update_workflow_status(db, workflow_id, "collaborating")

        return jsonify({
            "message": "Completion state updated",
            "workflow": get_workflow_by_id(db, workflow_id).to_dict()
        }), 200
    finally:
        db.close()


@workflow_bp.route('/api/workflows/<int:workflow_id>/start-research', methods=['POST'])
def start_research_from_collaboration(workflow_id):
    """
    Manually start OpenClaw research after requester approval in collaboration chat.
    """
    db = SessionLocal()
    try:
        data = request.json or {}
        user_id = data.get("user_id")
        skip_web_search = bool(data.get("skip_web_search"))

        if not user_id:
            return jsonify({"error": "user_id is required"}), 400

        workflow = get_workflow_by_id(db, workflow_id)
        if not workflow:
            return jsonify({"error": "Workflow not found"}), 404
        if user_id not in _participant_user_ids(workflow):
            return jsonify({"error": "User is not a participant in this workflow"}), 403
        workflow = _maybe_fail_stalled_workflow(db, workflow)
        if user_id != workflow.user_id:
            return jsonify({"error": "Only the requester can start research"}), 403
        if workflow.status != "collaborating":
            return jsonify({"error": f"Workflow is not in collaborating state (current: {workflow.status})"}), 400
        if not _has_agent_participant(workflow):
            return jsonify({"error": "No agent collaborator is assigned to this workflow"}), 400

        for step in workflow.steps:
            if step.step_type == "agent_research" and step.status in ("pending", "in_progress", "awaiting_input", "completed"):
                return jsonify({"error": "Research has already started for this workflow"}), 400

        active_step = get_active_step(db, workflow_id)
        if active_step and active_step.status in ("pending", "in_progress", "awaiting_input"):
            update_step_status(db, active_step.id, "completed")

        base_description = _get_request_description(workflow)
        document_context = ""
        document_names: list[str] = []

        if skip_web_search:
            try:
                document_context, document_names = _build_uploaded_document_context(workflow_id)
            except Exception as exc:
                return jsonify({"error": f"Failed to read uploaded documents: {exc}"}), 400

            if not document_context:
                return jsonify({
                    "error": "No readable uploaded PDF/TXT documents found. Upload at least one document first."
                }), 400

            research_context = "\n\n".join(
                part for part in [
                    base_description,
                    "Use only the uploaded source documents below. Do not perform web search.",
                    document_context,
                ] if part
            )
            research_focus = base_description or (workflow.title or "").strip() or "Uploaded document analysis"
        else:
            chat_context = _build_chat_context(workflow)
            research_context = "\n\n".join(
                part for part in [
                    base_description,
                    f"Collaboration context:\n{chat_context}" if chat_context else "",
                ] if part
            )
            research_focus = base_description or (workflow.title or "").strip()

        session_id = workflow.openclaw_session_id or f"workflow-{generate_session_id()}"
        if not workflow.openclaw_session_id:
            update_workflow_status(db, workflow_id, workflow.status, openclaw_session_id=session_id)

        next_step_order = max((s.step_order for s in workflow.steps), default=0) + 1
        research_step = create_workflow_step(
            db,
            workflow_id=workflow_id,
            step_order=next_step_order,
            step_type="agent_research",
            provider_type="agent",
            input_data={
                "topic": research_focus,
                "description": research_context,
                "skip_web_search": skip_web_search,
                "source_documents": document_names,
            }
        )

        create_workflow_message(
            db,
            workflow_id=workflow_id,
            sender_type="system",
            channel="system",
            message=(
                "Requester approved the plan. OpenClaw document-based research is starting now."
                if skip_web_search else
                "Requester approved the plan. OpenClaw research is starting now."
            )
        )
        create_event(
            db, workflow_id=workflow_id, event_type="research_started",
            actor_id=user_id, actor_type="human", channel="web",
            message=(
                "Requester started agent research from uploaded documents"
                if skip_web_search else
                "Requester approved and started agent research from collaboration chat"
            ),
            metadata_json={"skip_web_search": skip_web_search, "source_documents": document_names}
        )

        start_research(
            workflow_id,
            research_focus,
            session_id,
            request_description=research_context,
            research_step_id=research_step.id,
            use_web_search=not skip_web_search
        )

        return jsonify({
            "message": "Research started from collaboration workflow.",
            "workflow": get_workflow_by_id(db, workflow_id).to_dict()
        }), 202
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

        user = get_user_by_id(db, user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404
        if user_id not in _participant_user_ids(workflow):
            return jsonify({"error": "User is not a participant in this workflow"}), 403
        workflow = _maybe_fail_stalled_workflow(db, workflow)
        if workflow.status == "generating_ppt":
            return jsonify({"error": "PPT generation is already in progress"}), 400
        if not _has_agent_participant(workflow):
            return jsonify({"error": "No agent collaborator is assigned to this workflow"}), 400

        chat_context = _build_chat_context(workflow)
        research_step = _get_latest_research_step_with_output(workflow)
        research_context = _build_generation_research_context(
            workflow,
            research_step,
            include_chat=False
        ) if research_step else ""

        presentation_focus = _get_primary_focus(workflow)
        combined_instructions = "\n\n".join(
            part for part in [
                research_context,
                f"Requester brief:\n{presentation_focus}" if presentation_focus else "",
                f"Additional generation instructions:\n{instructions}" if instructions else "",
                f"Chat context:\n{chat_context}" if chat_context else "",
            ] if part
        )
        if not combined_instructions.strip():
            combined_instructions = presentation_focus or workflow.title

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

        start_ppt_generation(
            workflow_id,
            combined_instructions,
            presentation_focus or workflow.title,
            filename_hint=workflow.title
        )

        return jsonify({
            "message": "PPT generation started from workflow chat context.",
            "workflow": get_workflow_by_id(db, workflow_id).to_dict()
        }), 202
    finally:
        db.close()


@workflow_bp.route('/api/workflows/<int:workflow_id>/retry-ppt', methods=['POST'])
def retry_failed_ppt_generation(workflow_id):
    """Retry PPT generation using existing workflow research output."""
    db = SessionLocal()
    try:
        data = request.json or {}
        user_id = data.get("user_id")
        if not user_id:
            return jsonify({"error": "user_id is required"}), 400

        workflow = get_workflow_by_id(db, workflow_id)
        if not workflow:
            return jsonify({"error": "Workflow not found"}), 404

        user = get_user_by_id(db, user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404
        if user_id not in _participant_user_ids(workflow):
            return jsonify({"error": "User is not a participant in this workflow"}), 403
        workflow = _maybe_fail_stalled_workflow(db, workflow)
        if workflow.status == "generating_ppt":
            return jsonify({"error": "PPT generation is already in progress"}), 400

        latest_generation_step = None
        for step in workflow.steps:
            if step.step_type == "agent_generation":
                latest_generation_step = step
        if not latest_generation_step or latest_generation_step.status != "failed":
            return jsonify({"error": "No failed PPT generation step found to retry"}), 400

        research_step = _get_latest_research_step_with_output(workflow)
        if not research_step:
            return jsonify({"error": "No completed research output found for retry"}), 400

        presentation_focus = _get_primary_focus(workflow)
        research_text = _build_generation_research_context(workflow, research_step)

        create_workflow_message(
            db,
            workflow_id=workflow_id,
            sender_type="system",
            channel="system",
            message=f"{user.name} retried PPT generation after a failed attempt."
        )
        create_event(
            db, workflow_id=workflow_id, event_type="generation_requested",
            actor_id=user_id, actor_type="human", channel="web",
            message=f"{user.name} retried PPT generation"
        )

        start_ppt_generation(
            workflow_id,
            research_text,
            presentation_focus or workflow.title,
            filename_hint=workflow.title
        )

        return jsonify({
            "message": "PPT generation retry started.",
            "workflow": get_workflow_by_id(db, workflow_id).to_dict()
        }), 202
    finally:
        db.close()


@workflow_bp.route('/api/workflows/<int:workflow_id>/cancel-run', methods=['POST'])
def cancel_active_run(workflow_id):
    """Cancel an in-flight research/refinement/PPT run and mark it failed."""
    db = SessionLocal()
    try:
        data = request.json or {}
        user_id = data.get("user_id")
        reason = str(data.get("reason", "")).strip()
        if not user_id:
            return jsonify({"error": "user_id is required"}), 400

        workflow = get_workflow_by_id(db, workflow_id)
        if not workflow:
            return jsonify({"error": "Workflow not found"}), 404

        user = get_user_by_id(db, user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404
        if user_id not in _participant_user_ids(workflow):
            return jsonify({"error": "User is not a participant in this workflow"}), 403
        workflow = _maybe_fail_stalled_workflow(db, workflow)
        if user_id != workflow.user_id:
            return jsonify({"error": "Only the requester can cancel an active run"}), 403

        if workflow.status not in RUNNING_WORKFLOW_STATUSES:
            return jsonify({
                "error": f"No active run to cancel (current status: {workflow.status})"
            }), 400

        operation_step = _get_operation_step_for_status(workflow)
        cancel_message = f"Run cancelled by {user.name}"
        if reason:
            cancel_message = f"{cancel_message}: {reason[:180]}"

        if operation_step and operation_step.status in ("pending", "in_progress", "awaiting_input"):
            existing_output = operation_step.output_data if isinstance(operation_step.output_data, dict) else {}
            failed_output = {
                **existing_output,
                "error": cancel_message,
                "cancelled": True,
            }
            update_step_status(db, operation_step.id, "failed", output_data=failed_output)

        update_workflow_status(db, workflow_id, "failed")
        create_workflow_message(
            db,
            workflow_id=workflow_id,
            sender_type="system",
            channel="system",
            message=f"{cancel_message}. You can retry from the workflow page."
        )
        create_event(
            db, workflow_id=workflow_id, event_type="failed",
            actor_id=user_id, actor_type="human", channel="web",
            step_id=operation_step.id if operation_step else None,
            message=cancel_message,
            metadata_json={"cancelled": True}
        )

        return jsonify({
            "message": "Active run cancelled.",
            "workflow": get_workflow_by_id(db, workflow_id).to_dict()
        }), 200
    finally:
        db.close()


@workflow_bp.route('/api/workflows/<int:workflow_id>/retry-run', methods=['POST'])
def retry_failed_run(workflow_id):
    """
    Retry a failed/stalled run.
    If PPT generation failed, retries PPT.
    Otherwise restarts agent research from description-first context.
    """
    db = SessionLocal()
    try:
        data = request.json or {}
        user_id = data.get("user_id")
        if not user_id:
            return jsonify({"error": "user_id is required"}), 400

        workflow = get_workflow_by_id(db, workflow_id)
        if not workflow:
            return jsonify({"error": "Workflow not found"}), 404

        user = get_user_by_id(db, user_id)
        if not user:
            return jsonify({"error": "User not found"}), 404
        if user_id not in _participant_user_ids(workflow):
            return jsonify({"error": "User is not a participant in this workflow"}), 403
        workflow = _maybe_fail_stalled_workflow(db, workflow)
        if user_id != workflow.user_id:
            return jsonify({"error": "Only the requester can retry a failed run"}), 403
        if workflow.status in RUNNING_WORKFLOW_STATUSES:
            return jsonify({"error": "Run is still active. Cancel it before retrying."}), 400
        if not _has_agent_participant(workflow):
            return jsonify({"error": "No agent collaborator is assigned to this workflow"}), 400

        latest_generation_step = _get_latest_step_by_type(workflow, "agent_generation")
        if latest_generation_step and latest_generation_step.status == "failed":
            research_step = _get_latest_research_step_with_output(workflow)
            if not research_step:
                return jsonify({"error": "No completed research output found for PPT retry"}), 400

            presentation_focus = _get_primary_focus(workflow)
            research_text = _build_generation_research_context(workflow, research_step)

            create_workflow_message(
                db,
                workflow_id=workflow_id,
                sender_type="system",
                channel="system",
                message=f"{user.name} retried PPT generation after a failed/stalled run."
            )
            create_event(
                db, workflow_id=workflow_id, event_type="generation_requested",
                actor_id=user_id, actor_type="human", channel="web",
                message=f"{user.name} retried PPT generation"
            )
            start_ppt_generation(
                workflow_id,
                research_text,
                presentation_focus or workflow.title,
                filename_hint=workflow.title
            )
            return jsonify({
                "message": "PPT generation retry started.",
                "workflow": get_workflow_by_id(db, workflow_id).to_dict()
            }), 202

        base_description = _get_request_description(workflow)
        chat_context = _build_chat_context(workflow)
        research_context = "\n\n".join(
            part for part in [
                base_description,
                f"Collaboration context:\n{chat_context}" if chat_context else "",
            ] if part
        )
        research_focus = base_description or (workflow.title or "").strip()

        session_id = workflow.openclaw_session_id or f"workflow-{generate_session_id()}"
        if not workflow.openclaw_session_id:
            update_workflow_status(db, workflow_id, workflow.status, openclaw_session_id=session_id)

        next_step_order = max((s.step_order for s in workflow.steps), default=0) + 1
        research_step = create_workflow_step(
            db,
            workflow_id=workflow_id,
            step_order=next_step_order,
            step_type="agent_research",
            provider_type="agent",
            input_data={
                "topic": research_focus,
                "description": research_context,
                "retry": True
            }
        )
        create_workflow_message(
            db,
            workflow_id=workflow_id,
            sender_type="system",
            channel="system",
            message=f"{user.name} retried agent research after a failed/stalled run."
        )
        create_event(
            db, workflow_id=workflow_id, event_type="research_started",
            actor_id=user_id, actor_type="human", channel="web",
            message=f"{user.name} retried agent research"
        )
        start_research(
            workflow_id,
            research_focus,
            session_id,
            request_description=research_context,
            research_step_id=research_step.id
        )

        return jsonify({
            "message": "Research retry started.",
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
        workflow = _maybe_fail_stalled_workflow(db, workflow)
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
        presentation_focus = _get_primary_focus(workflow)
        research_text = presentation_focus
        for step in workflow.steps:
            if step.step_type == "agent_research" and step.output_data:
                research_text = (
                    step.output_data.get("raw_research") or
                    step.output_data.get("summary") or
                    presentation_focus
                )
                break

        # Start PPT generation
        start_ppt_generation(
            workflow_id,
            research_text,
            presentation_focus or workflow.title,
            filename_hint=workflow.title
        )

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

def _complete_marketplace_handshake(db, work_request, volunteer):
    """
    Accept a volunteer/invite and create the collaboration workflow.
    Returns (workflow, should_send_agent_kickoff, kickoff_prompt).
    """
    user = volunteer.user
    if not user:
        raise ValueError("Selected volunteer user not found")

    # 1. Update marketplace statuses
    volunteer.status = "accepted"
    work_request.status = "assigned"
    for other in work_request.volunteers:
        if other.id != volunteer.id and other.status == "pending":
            other.status = "rejected"

    # 2. Create the actual Workflow from the request
    session_id = f"workflow-{generate_session_id()}"
    workflow_type = _infer_workflow_type(
        work_request.title,
        work_request.description,
        work_request.required_capabilities
    )
    requires_research = user.is_agent and _should_auto_start_agent(work_request.required_capabilities)
    auto_start_agent = False

    workflow = create_workflow(
        db,
        user_id=work_request.requester_id,
        title=work_request.title,
        workflow_type=workflow_type,
        openclaw_session_id=session_id,
        parent_id=work_request.parent_workflow_id
    )
    copied_source_documents = _copy_request_attachments_to_workflow(work_request.id, workflow.id)

    # 3. Create the first step and assign it
    if user.is_agent:
        step_type = "agent_collaboration"
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
            "topic": (work_request.description or "").strip() or work_request.title,
            "title": work_request.title,
            "description": work_request.description,
            "workflow_type": workflow_type,
            "request_id": work_request.id,
            "requires_research": requires_research,
            "source_documents": copied_source_documents
        }
    )

    # 4. Success event
    create_event(
        db, workflow_id=workflow.id, event_type="created",
        actor_id=work_request.requester_id, actor_type="human", channel="web",
        message=f"Handshake complete! {user.name} is starting work on: {work_request.title}"
    )

    # 5. Seed collaboration chat + approvals for collaborative paths
    should_send_agent_kickoff = False
    kickoff_prompt = (
        "Please acknowledge the requester description for this workflow, "
        "summarize the requirements you will follow, and ask whether they "
        "want to refine anything before pressing 'Start Agent Research'."
    )

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
        if requires_research:
            create_workflow_message(
                db,
                workflow_id=workflow.id,
                sender_type="system",
                channel="system",
                message=(
                    "Research has not started yet. Let the agent propose a first-step plan in chat, "
                    "then requester uses 'Start Agent Research' when ready."
                )
            )
            should_send_agent_kickoff = True

    if not user.is_agent:
        upsert_workflow_approval(db, workflow.id, work_request.requester_id, "pending")
        upsert_workflow_approval(db, workflow.id, user.id, "pending")

    db.commit()
    return workflow, should_send_agent_kickoff, kickoff_prompt


@workflow_bp.route('/api/marketplace/invites', methods=['GET'])
def list_marketplace_invites():
    """List pending marketplace invites for a user."""
    db = SessionLocal()
    try:
        user_id = request.args.get("user_id", type=int)
        if not user_id:
            return jsonify({"error": "user_id is required"}), 400

        invites = get_pending_invites_for_user(db, user_id)
        invite_payload = []
        for invite in invites:
            work_request = invite.request
            if not work_request:
                continue
            invite_payload.append({
                "volunteer_id": invite.id,
                "request": work_request.to_dict()
            })

        return jsonify({"invites": invite_payload}), 200
    finally:
        db.close()


@workflow_bp.route('/api/marketplace', methods=['GET'])
def list_marketplace():
    """List all open work requests on the marketplace board."""
    db = SessionLocal()
    try:
        requests = get_open_work_requests(db)
        return jsonify({
            "requests": [_work_request_payload(r) for r in requests]
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
        data = None
        uploaded_files = []
        content_type = (request.content_type or "").lower()
        if content_type.startswith("multipart/form-data"):
            data = {
                "title": (request.form.get("title") or "").strip(),
                "description": (request.form.get("description") or "").strip(),
                "requester_id": request.form.get("requester_id"),
                "required_capabilities": _parse_json_list_field(request.form.get("required_capabilities")),
                "selected_persona_ids": _parse_json_list_field(request.form.get("selected_persona_ids")),
                "parent_workflow_id": request.form.get("parent_workflow_id"),
            }
            uploaded_files = [f for f in request.files.getlist("attachments") if f and f.filename]
        elif request.form:
            data = {
                "title": (request.form.get("title") or "").strip(),
                "description": (request.form.get("description") or "").strip(),
                "requester_id": request.form.get("requester_id"),
                "required_capabilities": _parse_json_list_field(request.form.get("required_capabilities")),
                "selected_persona_ids": _parse_json_list_field(request.form.get("selected_persona_ids")),
                "parent_workflow_id": request.form.get("parent_workflow_id"),
            }
        else:
            data = request.get_json(silent=True)

        if not data:
            return jsonify({"error": "Request body missing"}), 400
        if not str(data.get("title") or "").strip():
            return jsonify({"error": "title is required"}), 400
        if not str(data.get("description") or "").strip():
            return jsonify({"error": "description is required"}), 400

        requester_id_raw = data.get("requester_id")
        if requester_id_raw is None:
            return jsonify({"error": "requester_id is required"}), 400
        try:
            requester_id = int(requester_id_raw)
        except (TypeError, ValueError):
            return jsonify({"error": "requester_id must be a number"}), 400

        requester = get_user_by_id(db, requester_id)
        if not requester:
            return jsonify({"error": "Requester not found"}), 404
        data["requester_id"] = requester_id
        parent_workflow_id_raw = data.get("parent_workflow_id")
        if parent_workflow_id_raw in ("", None):
            data["parent_workflow_id"] = None
        else:
            try:
                data["parent_workflow_id"] = int(parent_workflow_id_raw)
            except (TypeError, ValueError):
                return jsonify({"error": "parent_workflow_id must be a number"}), 400

        is_valid_attachments, attachment_error = _validate_attachments(uploaded_files)
        if not is_valid_attachments:
            return jsonify({"error": attachment_error}), 400

        # Create the request
        work_request = create_work_request(db, data)

        if uploaded_files:
            _save_attachments_to_dir(_request_upload_dir(work_request.id), uploaded_files)

        # Optional targeted personas from the post form.
        selected_persona_ids_raw = data.get("selected_persona_ids") or []
        selected_persona_ids: list[int] = []
        if isinstance(selected_persona_ids_raw, list):
            for raw_id in selected_persona_ids_raw:
                try:
                    persona_id = int(raw_id)
                except (TypeError, ValueError):
                    continue
                if persona_id <= 0 or persona_id == requester_id or persona_id in selected_persona_ids:
                    continue
                selected_persona_ids.append(persona_id)

        selected_personas = []
        for persona_id in selected_persona_ids:
            user = get_user_by_id(db, persona_id)
            if user and user.is_active:
                selected_personas.append(user)

        invited_user_ids: set[int] = set()
        auto_accept_invite = None
        for persona in selected_personas:
            volunteer = create_volunteer(db, {
                "request_id": work_request.id,
                "user_id": persona.id,
                "note": f"Direct invite from {requester.name}."
            })
            invited_user_ids.add(persona.id)
            if persona.is_agent and auto_accept_invite is None:
                auto_accept_invite = volunteer

        # ── AGENT AUTO-VOLUNTEER LOGIC ──
        required_caps = _normalize_caps(data.get("required_capabilities", []))
        from database.models import User
        agents = db.query(User).filter(User.is_agent == True).all()

        auto_agent_caps = {
            "research", "ppt", "ppt_generation", "powerpoint",
            "slides", "presentation"
        }
        should_autovolunteer = bool(set(required_caps).intersection(auto_agent_caps))

        if should_autovolunteer:
            for agent in agents:
                if agent.email != "agent@openclaw.ai":
                    continue
                if agent.id in invited_user_ids:
                    continue
                create_volunteer(db, {
                    "request_id": work_request.id,
                    "user_id": agent.id,
                    "note": (
                        "I can collaborate on research, content refinement, and "
                        "SlideSpeak-based PowerPoint generation."
                    )
                })

        # If an agent was explicitly selected, auto-accept immediately.
        if auto_accept_invite and work_request.status == "open" and auto_accept_invite.status == "pending":
            workflow, should_send_agent_kickoff, kickoff_prompt = _complete_marketplace_handshake(
                db, work_request, auto_accept_invite
            )
            if should_send_agent_kickoff:
                start_agent_chat_reply(workflow.id, kickoff_prompt)
            return jsonify({
                "message": "Work request posted and agent accepted automatically.",
                "request": _work_request_payload(work_request),
                "workflow_id": workflow.id,
                "workflow_type": workflow.workflow_type
            }), 201

        return jsonify({
            "message": "Work request posted to marketplace!",
            "request": _work_request_payload(work_request)
        }), 201
    except Exception as e:
        db.rollback()
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
        return jsonify({"request": _work_request_payload(work_request)}), 200
    finally:
        db.close()


@workflow_bp.route('/api/marketplace/<int:request_id>/attachments/<path:filename>', methods=['GET'])
def download_marketplace_attachment(request_id, filename):
    """Download an attachment uploaded with a marketplace request."""
    db = SessionLocal()
    try:
        work_request = get_work_request_by_id(db, request_id)
        if not work_request:
            return jsonify({"error": "Request not found"}), 404

        safe_filename = os.path.basename(filename)
        if not safe_filename or safe_filename != filename:
            return jsonify({"error": "Invalid filename"}), 400

        file_path = os.path.join(_request_upload_dir(request_id), safe_filename)
        if not os.path.isfile(file_path):
            return jsonify({"error": "Attachment not found"}), 404

        return send_file(
            file_path,
            as_attachment=True,
            download_name=_attachment_display_name(safe_filename)
        )
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
        volunteer_id_raw = data.get("volunteer_id")
        actor_id_raw = data.get("user_id")

        if volunteer_id_raw is None:
            return jsonify({"error": "volunteer_id is required"}), 400
        if actor_id_raw is None:
            return jsonify({"error": "user_id is required"}), 400
        try:
            volunteer_id = int(volunteer_id_raw)
            actor_id = int(actor_id_raw)
        except (TypeError, ValueError):
            return jsonify({"error": "volunteer_id and user_id must be numbers"}), 400

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
        if actor_id not in (work_request.requester_id, volunteer.user_id):
            return jsonify({"error": "Only the requester or invited persona can accept"}), 403
        if actor_id == volunteer.user_id and not (volunteer.note or "").startswith("Direct invite"):
            return jsonify({"error": "Only requesters can accept non-invite volunteers"}), 403

        workflow, should_send_agent_kickoff, kickoff_prompt = _complete_marketplace_handshake(
            db, work_request, volunteer
        )
        if should_send_agent_kickoff:
            start_agent_chat_reply(workflow.id, kickoff_prompt)
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
@workflow_bp.route('/api/marketplace/invites', methods=['OPTIONS'])
@workflow_bp.route('/api/marketplace/<int:request_id>', methods=['OPTIONS'])
@workflow_bp.route('/api/marketplace/<int:request_id>/attachments/<path:filename>', methods=['OPTIONS'])
@workflow_bp.route('/api/marketplace/<int:request_id>/volunteer', methods=['OPTIONS'])
@workflow_bp.route('/api/marketplace/<int:request_id>/accept', methods=['OPTIONS'])
@workflow_bp.route('/api/users', methods=['OPTIONS'])
@workflow_bp.route('/api/workflows', methods=['OPTIONS'])
@workflow_bp.route('/api/workflows/<int:workflow_id>', methods=['OPTIONS'])
@workflow_bp.route('/api/workflows/<int:workflow_id>/attachments', methods=['OPTIONS'])
@workflow_bp.route('/api/workflows/<int:workflow_id>/attachments/<path:filename>', methods=['OPTIONS'])
@workflow_bp.route('/api/workflows/<int:workflow_id>/submission-documents', methods=['OPTIONS'])
@workflow_bp.route('/api/workflows/<int:workflow_id>/submission-documents/<path:filename>', methods=['OPTIONS'])
@workflow_bp.route('/api/workflows/<int:workflow_id>/review', methods=['OPTIONS'])
@workflow_bp.route('/api/workflows/<int:workflow_id>/messages', methods=['OPTIONS'])
@workflow_bp.route('/api/workflows/<int:workflow_id>/completion', methods=['OPTIONS'])
@workflow_bp.route('/api/workflows/<int:workflow_id>/start-research', methods=['OPTIONS'])
@workflow_bp.route('/api/workflows/<int:workflow_id>/generate-ppt', methods=['OPTIONS'])
@workflow_bp.route('/api/workflows/<int:workflow_id>/retry-ppt', methods=['OPTIONS'])
@workflow_bp.route('/api/workflows/<int:workflow_id>/cancel-run', methods=['OPTIONS'])
@workflow_bp.route('/api/workflows/<int:workflow_id>/retry-run', methods=['OPTIONS'])
@workflow_bp.route('/api/slack/interactions', methods=['OPTIONS'])
def handle_workflow_options(**kwargs):
    """Handle preflight CORS requests for workflow endpoints."""
    from flask import make_response
    response = make_response()
    origin = request.headers.get('Origin')
    if origin in ["http://localhost:5173", "http://localhost:5174"]:
        response.headers['Access-Control-Allow-Origin'] = origin
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response
