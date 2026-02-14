"""
Workflow Service — Core orchestration logic for the AIXplore Capability Exchange.

Handles:
- Background thread management for async OpenClaw calls
- Research → Review → Generation pipeline
- Iterative refinement loop
- PPT file polling after SlideSpeak generation
"""

import threading
import time
import os
import re
import json
import subprocess
from typing import Any

import requests
from database import SessionLocal
from database.models import Workflow, WorkflowStep
from crud import (
    get_workflow_by_id, update_workflow_status,
    create_workflow_step, get_active_step_by_type, get_step_by_id,
    update_step_status, increment_step_iteration,
    create_event, create_workflow_message,
    get_user_by_email, get_work_request_by_id
)
from openclaw_client import ask_openclaw, generate_session_id

# PPT output + SlideSpeak paths (override in backend/.env for portability)
PPT_OUTPUT_DIR = os.getenv("PPT_OUTPUT_DIR", "/Users/anubhawmathur/development/ppt-output")
SLIDESPEAK_SKILL_DIR = os.getenv(
    "SLIDESPEAK_SKILL_DIR",
    "/Users/anubhawmathur/.openclaw/workspace/skills/slidespeak"
)
SLIDESPEAK_SCRIPT_PATH = os.getenv("SLIDESPEAK_SCRIPT_PATH", "scripts/slidespeak.mjs")
SLIDESPEAK_MAX_WAIT_SECONDS = 300
SLIDESPEAK_GENERATE_TIMEOUT_SECONDS = 240
SLIDESPEAK_STATUS_POLL_INTERVAL_SECONDS = 5
SLIDESPEAK_COMMAND_BUFFER_SECONDS = 20
SLIDESPEAK_DOWNLOAD_TIMEOUT_SECONDS = 60
PROMPT_RECONCILIATION_TIMEOUT_SECONDS = 120


# ──────────────────────────────────────
# Research Output Parsing
# ──────────────────────────────────────

SECTION_HEADER_VARIANTS = (
    r"EXECUTIVE\s+SUMMARY",
    r"SLIDE(?:\s*[-/]?\s*BY\s*[-/]?\s*SLIDE)?\s+(?:OUTLINE|BREAKDOWN)",
    r"RAW\s+RESEARCH(?:\s+DATA)?",
)
SECTION_HEADER_ALT = "|".join(SECTION_HEADER_VARIANTS)
SECTION_HEADER_PATTERN = re.compile(
    r"^\s*(?:={3,}\s*)?(?P<header_a>" + SECTION_HEADER_ALT + r")(?:\s*={3,})?\s*:?\s*$"
    r"|^\s*#{1,6}\s*(?P<header_b>" + SECTION_HEADER_ALT + r")\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _canonicalize_header_label(header_text: str) -> str | None:
    token = re.sub(r"[^a-z]+", " ", header_text.lower()).strip()
    if "executive" in token and "summary" in token:
        return "summary"
    if "slide" in token and ("outline" in token or "breakdown" in token):
        return "slide_outline"
    if "raw" in token and "research" in token:
        return "raw_research"
    return None


def _extract_section_map(normalized_text: str) -> dict:
    section_map = {
        "summary": "",
        "slide_outline": "",
        "raw_research": "",
    }
    matches = list(SECTION_HEADER_PATTERN.finditer(normalized_text))
    if not matches:
        return section_map

    for idx, match in enumerate(matches):
        header = match.group("header_a") or match.group("header_b") or ""
        key = _canonicalize_header_label(header)
        if not key:
            continue

        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(normalized_text)
        chunk = normalized_text[start:end].strip()

        if not chunk:
            continue

        # If the model nested another recognizable heading inside a chunk,
        # keep only content up to that heading boundary.
        nested = SECTION_HEADER_PATTERN.search(chunk)
        if nested:
            chunk = chunk[:nested.start()].strip()

        if chunk and not section_map[key]:
            section_map[key] = chunk

    return section_map


def parse_research_output(raw_text: str) -> dict:
    """
    Parse structured research output from OpenClaw into components.
    Handles both well-formatted and messy agent responses gracefully.

    Returns dict with keys: summary, slide_outline, raw_research, raw_text
    """
    result = {
        "summary": "",
        "slide_outline": "",
        "raw_research": "",
        "raw_text": raw_text,
    }

    if not raw_text:
        return result

    normalized_text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    extracted = _extract_section_map(normalized_text)
    result["summary"] = extracted["summary"]
    result["slide_outline"] = extracted["slide_outline"]
    result["raw_research"] = extracted["raw_research"]

    # Fallback: if no sections were found, use the entire text
    if not result["summary"] and not result["slide_outline"]:
        # Try to create a summary from the first few paragraphs
        paragraphs = [p.strip() for p in normalized_text.split("\n\n") if p.strip()]
        if len(paragraphs) >= 2:
            result["summary"] = "\n\n".join(paragraphs[:2])
            result["raw_research"] = normalized_text
        else:
            result["summary"] = normalized_text[:500] + ("..." if len(normalized_text) > 500 else "")
            result["raw_research"] = normalized_text

    return result


# ──────────────────────────────────────
# Research Pipeline
# ──────────────────────────────────────

def _build_research_prompt(topic: str, num_slides: int = 8, request_description: str = "") -> str:
    """Build the structured research prompt for OpenClaw."""
    description_block = ""
    if request_description and request_description.strip():
        description_block = f"""
ADDITIONAL REQUEST CONTEXT:
{request_description.strip()}

Use both the topic and this context when selecting what to research, which facts to prioritize, and how to structure the final slides.
"""

    return f"""You are a research assistant for the AIXplore Capability Exchange.

TASK: Research the following topic thoroughly using web_search: "{topic}"
{description_block}

After completing your research, return your findings in this EXACT format (use the section headers exactly as shown):

=== EXECUTIVE SUMMARY ===
Write a 2-3 paragraph executive summary of your findings. Include the most important facts, trends, and implications.

=== SLIDE OUTLINE ===
Create a {num_slides}-slide presentation outline. For each slide, provide:
Slide 1: [Title]
- [Content-rich bullet 1: full sentence with concrete detail]
- [Content-rich bullet 2: full sentence with concrete detail]
- [Content-rich bullet 3: full sentence with concrete detail]
- [Content-rich bullet 4: full sentence with concrete detail]
- [Content-rich bullet 5: full sentence with concrete detail]

Slide 2: [Title]
- [Content-rich bullet 1: full sentence with concrete detail]
- [Content-rich bullet 2: full sentence with concrete detail]
- [Content-rich bullet 3: full sentence with concrete detail]
- [Content-rich bullet 4: full sentence with concrete detail]
- [Content-rich bullet 5: full sentence with concrete detail]

(Continue for all {num_slides} slides)

=== RAW RESEARCH ===
Include your complete research findings with all data points, statistics, sources, and detailed information gathered from your web search.

QUALITY REQUIREMENTS:
- Each slide must have at least 5 substantial bullets.
- Bullets should be 12-28 words each, not fragments.
- Include specific names, dates, figures, and examples where available.
- Avoid generic filler statements.

IMPORTANT: Execute the web_search NOW, then organize and return your findings in the format above."""


def _build_refinement_prompt(feedback: str) -> str:
    """Build a refinement prompt that references the previous research session."""
    return f"""The human reviewer has provided feedback on your previous research. 
Please refine and improve your research based on their instructions.

REVIEWER FEEDBACK:
{feedback}

INSTRUCTIONS:
1. Do NOT start over. Build upon your previous research.
2. Address the specific feedback points above.
3. If the reviewer asks for more depth on a topic, use web_search to gather additional information.
4. Return your UPDATED findings in the same format:

=== EXECUTIVE SUMMARY ===
[Updated summary incorporating the feedback]

=== SLIDE OUTLINE ===
[Updated slide outline incorporating the feedback]

=== RAW RESEARCH ===
[Updated research with any new findings added to the previous research]

QUALITY REQUIREMENTS:
- Keep the same number of slides unless feedback asks otherwise.
- For every slide include at least 5 substantial bullets (12-28 words each).
- Add concrete details, evidence, and specific examples wherever possible.
- Do not return terse placeholder bullets.

Make sure to incorporate the reviewer's feedback while preserving the valuable parts of your original research."""


def start_research(
    workflow_id: int,
    topic: str,
    openclaw_session_id: str,
    request_description: str = "",
    research_step_id: int | None = None
):
    """
    Launch a background thread to run OpenClaw research.
    Updates the database with results when complete.
    """
    thread = threading.Thread(
        target=_run_research_thread,
        args=(workflow_id, topic, openclaw_session_id, request_description, research_step_id),
        daemon=True
    )
    thread.start()
    return thread


def _run_research_thread(
    workflow_id: int,
    topic: str,
    openclaw_session_id: str,
    request_description: str = "",
    research_step_id: int | None = None
):
    """Background thread: executes OpenClaw research and updates DB."""
    db = SessionLocal()
    try:
        # Update workflow status to researching
        update_workflow_status(db, workflow_id, "researching")

        # Get the target research step for this run.
        if research_step_id:
            step = get_step_by_id(db, research_step_id)
            if (not step or step.workflow_id != workflow_id or step.step_type != "agent_research"
                    or step.status not in ("pending", "in_progress", "awaiting_input")):
                print(f"[Workflow {workflow_id}] ERROR: Provided research step {research_step_id} is not active/valid")
                return
        else:
            step = get_active_step_by_type(db, workflow_id, "agent_research")
        if not step:
            print(f"[Workflow {workflow_id}] ERROR: No active step found")
            return
        update_step_status(db, step.id, "in_progress")

        # Log the research start event
        topic_preview = re.sub(r"\s+", " ", (topic or "").strip())
        if len(topic_preview) > 120:
            topic_preview = topic_preview[:117] + "..."
        create_event(
            db, workflow_id=workflow_id, event_type="research_started",
            actor_type="agent", step_id=step.id,
            message=f"OpenClaw agent started researching: {topic_preview}"
        )

        # Build prompt and call OpenClaw (synchronous — blocks this thread)
        prompt = _build_research_prompt(topic, request_description=request_description)
        print(f"[Workflow {workflow_id}] Starting OpenClaw research...")

        result = ask_openclaw(
            message=prompt,
            session_id=openclaw_session_id,
            timeout=300  # 5 minutes
        )

        # Guardrail: if the workflow was cancelled/failed while the agent was running,
        # do not overwrite the newer terminal state with stale results.
        current_workflow = get_workflow_by_id(db, workflow_id)
        current_step = get_step_by_id(db, step.id)
        if (not current_workflow or current_workflow.status != "researching"
                or not current_step or current_step.status == "failed"):
            print(f"[Workflow {workflow_id}] Research result ignored because workflow state changed.")
            return

        if result.get("success"):
            output = result.get("output", "")
            parsed = parse_research_output(output)

            # Mark research step as complete
            update_step_status(db, step.id, "completed", output_data=parsed)

            # Get workflow owner for review assignment
            workflow = get_workflow_by_id(db, workflow_id)

            # Create the human review step (assigned to the workflow owner)
            next_step_order = max((s.step_order for s in workflow.steps), default=0) + 1
            review_step = create_workflow_step(
                db, workflow_id=workflow_id, step_order=next_step_order,
                step_type="human_review", provider_type="human",
                assigned_to=workflow.user_id,
                input_data={"instructions": "Review the research and approve or request refinements."}
            )

            # Update workflow to awaiting review
            update_workflow_status(db, workflow_id, "awaiting_review")

            # Log events
            create_event(
                db, workflow_id=workflow_id, event_type="research_completed",
                actor_type="agent", step_id=step.id,
                message="Research completed successfully"
            )
            create_event(
                db, workflow_id=workflow_id, event_type="review_requested",
                actor_type="system", step_id=review_step.id,
                message=f"Review assigned to {workflow.owner.name}"
            )

            # Attempt Slack notification (non-blocking)
            try:
                from slack_service import notify_research_complete
                notify_research_complete(workflow_id, topic, parsed.get("summary", ""))
            except Exception as slack_err:
                print(f"[Workflow {workflow_id}] Slack notification skipped: {slack_err}")

            print(f"[Workflow {workflow_id}] Research complete. Awaiting review.")

        else:
            # Research failed
            error_msg = result.get("error", "Unknown error")
            update_step_status(
                db, step.id, "failed",
                output_data={"error": error_msg}
            )
            update_workflow_status(db, workflow_id, "failed")
            create_event(
                db, workflow_id=workflow_id, event_type="failed",
                actor_type="agent", step_id=step.id,
                message=f"Research failed: {error_msg}"
            )
            print(f"[Workflow {workflow_id}] Research FAILED: {error_msg}")

    except Exception as e:
        print(f"[Workflow {workflow_id}] EXCEPTION in research thread: {e}")
        import traceback
        traceback.print_exc()
        try:
            update_workflow_status(db, workflow_id, "failed")
            create_event(
                db, workflow_id=workflow_id, event_type="failed",
                actor_type="system",
                message=f"Unexpected error: {str(e)}"
            )
        except Exception:
            pass
    finally:
        db.close()


# ──────────────────────────────────────
# Refinement Loop
# ──────────────────────────────────────

def start_refinement(workflow_id: int, feedback: str, openclaw_session_id: str):
    """
    Launch a background thread to refine research based on human feedback.
    Uses the same OpenClaw session to maintain context.
    """
    thread = threading.Thread(
        target=_run_refinement_thread,
        args=(workflow_id, feedback, openclaw_session_id),
        daemon=True
    )
    thread.start()
    return thread


def _run_refinement_thread(workflow_id: int, feedback: str, openclaw_session_id: str):
    """Background thread: refines OpenClaw research based on human feedback."""
    db = SessionLocal()
    try:
        # Update workflow status
        update_workflow_status(db, workflow_id, "refining")

        # Find the latest completed research step to update its output.
        workflow = get_workflow_by_id(db, workflow_id)
        research_step = None
        ordered_steps = sorted(
            workflow.steps,
            key=lambda step: ((step.step_order or 0), (step.id or 0))
        )
        for step in reversed(ordered_steps):
            if step.step_type == "agent_research" and step.output_data:
                research_step = step
                break
        if not research_step:
            for step in reversed(ordered_steps):
                if step.step_type == "agent_research":
                    research_step = step
                    break

        if not research_step:
            print(f"[Workflow {workflow_id}] ERROR: No research step found for refinement")
            return

        # Increment iteration count
        increment_step_iteration(db, research_step.id)

        # Mark research step as in_progress again
        update_step_status(db, research_step.id, "in_progress", feedback=feedback)

        create_event(
            db, workflow_id=workflow_id, event_type="research_started",
            actor_type="agent", step_id=research_step.id,
            message=f"Refinement round {research_step.iteration_count}: {feedback[:100]}..."
        )

        # Call OpenClaw with refinement prompt (same session maintains context)
        prompt = _build_refinement_prompt(feedback)
        print(f"[Workflow {workflow_id}] Starting refinement round {research_step.iteration_count}...")

        result = ask_openclaw(
            message=prompt,
            session_id=openclaw_session_id,
            timeout=300
        )

        # Guardrail: avoid applying stale refinement output after cancellation/failover.
        current_workflow = get_workflow_by_id(db, workflow_id)
        current_research_step = get_step_by_id(db, research_step.id)
        if (not current_workflow or current_workflow.status != "refining"
                or not current_research_step or current_research_step.status == "failed"):
            print(f"[Workflow {workflow_id}] Refinement result ignored because workflow state changed.")
            return

        if result.get("success"):
            output = result.get("output", "")
            parsed = parse_research_output(output)

            # Update research step with refined output
            update_step_status(db, research_step.id, "completed", output_data=parsed)

            # Update the latest review step back to awaiting_input.
            review_step = None
            for step in reversed(ordered_steps):
                if step.step_type == "human_review":
                    review_step = step
                    break

            if review_step:
                update_step_status(db, review_step.id, "awaiting_input")

            # Set workflow back to awaiting review
            update_workflow_status(db, workflow_id, "awaiting_review")

            create_event(
                db, workflow_id=workflow_id, event_type="research_completed",
                actor_type="agent", step_id=research_step.id,
                message=f"Refinement round {research_step.iteration_count} complete"
            )

            # Notify via Slack
            try:
                from slack_service import notify_research_complete
                notify_research_complete(
                    workflow_id, workflow.title, parsed.get("summary", ""),
                    is_refinement=True,
                    iteration=research_step.iteration_count
                )
            except Exception as slack_err:
                print(f"[Workflow {workflow_id}] Slack notification skipped: {slack_err}")

            print(f"[Workflow {workflow_id}] Refinement complete. Awaiting review again.")

        else:
            error_msg = result.get("error", "Unknown error")
            update_step_status(db, research_step.id, "failed",
                               output_data={"error": error_msg})
            update_workflow_status(db, workflow_id, "failed")
            create_event(
                db, workflow_id=workflow_id, event_type="failed",
                actor_type="agent", step_id=research_step.id,
                message=f"Refinement failed: {error_msg}"
            )

    except Exception as e:
        print(f"[Workflow {workflow_id}] EXCEPTION in refinement thread: {e}")
        import traceback
        traceback.print_exc()
        try:
            update_workflow_status(db, workflow_id, "failed")
        except Exception:
            pass
    finally:
        db.close()


# ──────────────────────────────────────
# Agent Chat Loop (Phase 1.5)
# ──────────────────────────────────────

def _build_agent_chat_prompt(
    workflow_title: str,
    workflow_type: str,
    latest_user_message: str,
    recent_chat_context: str,
    request_description: str = ""
) -> str:
    description_block = request_description.strip() or "No explicit requester description provided."
    return f"""You are OpenClaw, collaborating inside the AIXplore Capability Exchange.

WORKFLOW TITLE: {workflow_title}
WORKFLOW TYPE: {workflow_type}
REQUEST DESCRIPTION:
{description_block}

RECENT CHAT CONTEXT:
{recent_chat_context}

LATEST HUMAN MESSAGE:
{latest_user_message}

INSTRUCTIONS:
1. Reply as a practical collaborator in 1-4 short paragraphs.
2. If asked for revisions, return actionable edits and checks.
3. If the request is about presentation quality, include concrete guidance for SlideSpeak/PPT updates.
4. If information is missing, ask concise clarifying questions.
5. Do not mention internal tooling, hidden reasoning, or tool availability/errors.
6. If asked to generate slides, direct the requester to use the explicit "Approve & Generate PPT" workflow action.
"""


def _sanitize_agent_chat_reply(reply: str) -> str:
    """
    Keep collaboration chat user-facing and avoid internal tool-status leakage.
    """
    text = (reply or "").strip()
    if not text:
        return ""

    lowered = text.lower()
    blocked_signals = (
        "tool unavailable",
        "not currently available",
        "cannot create the presentation directly",
        "issue with the presentation generation tool",
        "presentation generation tool",
    )
    if any(signal in lowered for signal in blocked_signals):
        return (
            "I can help refine the content and slide direction here. "
            "When you're ready, use 'Approve & Generate PPT' to start presentation generation."
        )
    return text


def start_agent_chat_reply(workflow_id: int, latest_user_message: str):
    """Launch a background reply from OpenClaw for workflow chat."""
    thread = threading.Thread(
        target=_run_agent_chat_reply_thread,
        args=(workflow_id, latest_user_message),
        daemon=True
    )
    thread.start()
    return thread


def _run_agent_chat_reply_thread(workflow_id: int, latest_user_message: str):
    """Background thread: get OpenClaw reply and persist it as a workflow chat message."""
    db = SessionLocal()
    try:
        workflow = get_workflow_by_id(db, workflow_id)
        if not workflow:
            return

        # Ensure a session exists so OpenClaw can maintain collaboration context.
        session_id = workflow.openclaw_session_id
        if not session_id:
            session_id = f"workflow-{generate_session_id()}"
            update_workflow_status(db, workflow_id, workflow.status, openclaw_session_id=session_id)

        recent_messages = workflow.messages[-10:] if workflow.messages else []
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

        recent_chat_context = "\n".join(context_lines) if context_lines else "No prior chat context."
        request_description = ""
        for step in workflow.steps:
            payload = step.input_data or {}
            if isinstance(payload, dict):
                desc = (payload.get("description") or "").strip()
                if desc:
                    request_description = desc
                    break

        prompt = _build_agent_chat_prompt(
            workflow_title=workflow.title,
            workflow_type=workflow.workflow_type,
            latest_user_message=latest_user_message,
            recent_chat_context=recent_chat_context,
            request_description=request_description
        )

        result = ask_openclaw(
            message=prompt,
            session_id=session_id,
            timeout=180
        )

        openclaw_user = get_user_by_email(db, "agent@openclaw.ai")
        if result.get("success"):
            reply = _sanitize_agent_chat_reply((result.get("output") or "").strip())
            if reply:
                create_workflow_message(
                    db,
                    workflow_id=workflow_id,
                    message=reply,
                    sender_id=openclaw_user.id if openclaw_user else None,
                    sender_type="agent",
                    channel="web"
                )
                create_event(
                    db, workflow_id=workflow_id, event_type="agent_replied",
                    actor_id=openclaw_user.id if openclaw_user else None,
                    actor_type="agent", channel="web",
                    message="OpenClaw responded in workflow chat"
                )
        else:
            error_msg = result.get("error", "Unknown agent error")
            create_workflow_message(
                db,
                workflow_id=workflow_id,
                message=f"OpenClaw could not respond right now: {error_msg}",
                sender_id=openclaw_user.id if openclaw_user else None,
                sender_type="agent",
                channel="system"
            )
            create_event(
                db, workflow_id=workflow_id, event_type="failed",
                actor_type="agent", channel="web",
                message=f"Agent chat reply failed: {error_msg}"
            )

    except Exception as e:
        print(f"[Workflow {workflow_id}] EXCEPTION in agent chat thread: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


# ──────────────────────────────────────
# PPT Generation Pipeline
# ──────────────────────────────────────

def _sanitize_topic_for_filename(topic: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (topic or "").strip().lower()).strip("_")
    return (slug[:80] if slug else "presentation")


def _infer_slide_count_from_context(context_text: str, default: int = 8) -> int:
    matches = re.findall(r"(?im)^\s*slide\s+(\d{1,2})\s*[:\-]", context_text or "")
    if not matches:
        return default
    try:
        inferred = max(int(m) for m in matches)
    except ValueError:
        return default
    return max(4, min(15, inferred))


def _extract_json_payload(raw_output: str) -> dict | None:
    text = (raw_output or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    first = text.find("{")
    last = text.rfind("}")
    if first == -1 or last == -1 or last <= first:
        return None
    try:
        parsed = json.loads(text[first:last + 1])
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _deep_find_first(payload: Any, expected_keys: set[str]) -> str | None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized_key = re.sub(r"[^a-z0-9]+", "", str(key).lower())
            if normalized_key in expected_keys and isinstance(value, str) and value.strip():
                return value.strip()
        for value in payload.values():
            found = _deep_find_first(value, expected_keys)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _deep_find_first(item, expected_keys)
            if found:
                return found
    return None


def _run_slidespeak_command(args: list[str], timeout_seconds: int) -> dict:
    script_path = SLIDESPEAK_SCRIPT_PATH
    script_file = (
        script_path if os.path.isabs(script_path)
        else os.path.join(SLIDESPEAK_SKILL_DIR, script_path)
    )
    if not os.path.isfile(script_file):
        raise RuntimeError(
            f"SlideSpeak script not found at: {script_file}. "
            "Set SLIDESPEAK_SKILL_DIR/SLIDESPEAK_SCRIPT_PATH in backend/.env."
        )

    cmd = ["node", SLIDESPEAK_SCRIPT_PATH, *args]
    result = subprocess.run(
        cmd,
        cwd=SLIDESPEAK_SKILL_DIR,
        capture_output=True,
        text=True,
        timeout=timeout_seconds
    )
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    if result.returncode != 0:
        message = stderr or stdout or f"SlideSpeak command failed with exit code {result.returncode}"
        raise RuntimeError(message)

    payload = _extract_json_payload(stdout)
    if not payload:
        raise RuntimeError("SlideSpeak returned an unreadable response payload")

    if not payload.get("success"):
        raise RuntimeError(str(payload.get("error", "SlideSpeak returned success=false")))

    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("SlideSpeak returned an unexpected data payload")
    return data


def _poll_slidespeak_status(task_id: str, deadline_epoch: float) -> dict:
    while time.time() < deadline_epoch:
        status_data = _run_slidespeak_command(
            ["status", task_id],
            timeout_seconds=SLIDESPEAK_STATUS_POLL_INTERVAL_SECONDS + SLIDESPEAK_COMMAND_BUFFER_SECONDS
        )
        task_status = str(status_data.get("task_status", "")).upper()
        if task_status == "SUCCESS":
            return status_data
        if task_status in {"FAILURE", "ERROR"}:
            raise RuntimeError(f"SlideSpeak task failed with status {task_status}")
        time.sleep(SLIDESPEAK_STATUS_POLL_INTERVAL_SECONDS)
    raise TimeoutError("SlideSpeak status polling timed out")


def _download_to_file(download_url: str, file_path: str) -> int:
    response = requests.get(download_url, stream=True, timeout=SLIDESPEAK_DOWNLOAD_TIMEOUT_SECONDS)
    response.raise_for_status()
    with open(file_path, "wb") as handle:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                handle.write(chunk)
    return os.path.getsize(file_path)


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0"}:
            return False
    return None


def _normalize_reconciled_generation_spec(raw_spec: Any, default_slide_count: int) -> dict:
    spec: dict[str, Any] = raw_spec if isinstance(raw_spec, dict) else {}

    slide_count = default_slide_count
    raw_slide_count = spec.get("slide_count")
    if isinstance(raw_slide_count, int):
        slide_count = max(4, min(20, raw_slide_count))
    elif isinstance(raw_slide_count, str):
        try:
            slide_count = max(4, min(20, int(raw_slide_count.strip())))
        except ValueError:
            pass

    tone = str(spec.get("tone") or "professional").strip().lower()
    if tone not in {"professional", "formal", "executive", "academic", "technical", "conversational"}:
        tone = "professional"

    verbosity = str(spec.get("verbosity") or "text-heavy").strip().lower()
    # SlideSpeak expects: concise | standard | text-heavy.
    # Keep backward compatibility with older "balanced" values.
    if verbosity == "balanced":
        verbosity = "standard"
    if verbosity not in {"concise", "standard", "text-heavy"}:
        verbosity = "text-heavy"

    design_instructions = str(spec.get("design_instructions") or "").strip()[:1200]
    content_instructions = str(spec.get("content_instructions") or "").strip()[:1200]

    must_include = spec.get("must_include")
    must_avoid = spec.get("must_avoid")
    must_include_items = [
        str(item).strip()[:220]
        for item in (must_include if isinstance(must_include, list) else [])
        if str(item).strip()
    ][:12]
    must_avoid_items = [
        str(item).strip()[:220]
        for item in (must_avoid if isinstance(must_avoid, list) else [])
        if str(item).strip()
    ][:12]

    include_cover = _coerce_bool(spec.get("include_cover"))
    include_toc = _coerce_bool(spec.get("include_toc"))

    return {
        "slide_count": slide_count,
        "tone": tone,
        "verbosity": verbosity,
        "design_instructions": design_instructions,
        "content_instructions": content_instructions,
        "must_include": must_include_items,
        "must_avoid": must_avoid_items,
        "include_cover": include_cover,
        "include_toc": include_toc,
    }


def _build_prompt_reconciliation_prompt(presentation_focus: str, research_text: str, default_slide_count: int) -> str:
    focus_text = (presentation_focus or "").strip() or "the requester brief"
    focus_excerpt = focus_text[:1600] + ("..." if len(focus_text) > 1600 else "")
    context_excerpt = (research_text or "").strip()[:9000]

    return f"""You are preparing instructions for a presentation generator.

TASK:
Reconcile all requester instructions from the context into one generation spec.
Prioritize explicit requester requests in refinement notes and chat context.
If conflicts exist, choose the most recent explicit requester instruction.

RESPONSE FORMAT:
Return ONLY valid JSON with this exact schema:
{{
  "slide_count": number,
  "tone": "professional|formal|executive|academic|technical|conversational",
  "verbosity": "concise|standard|text-heavy",
  "design_instructions": "string",
  "content_instructions": "string",
  "must_include": ["string"],
  "must_avoid": ["string"],
  "include_cover": true|false|null,
  "include_toc": true|false|null
}}

RULES:
- Set slide_count from explicit requester intent when present; otherwise use {default_slide_count}.
- Keep design_instructions specific: style, visual direction, typography, color intent, chart/image preferences.
- Keep content_instructions specific: audience level, depth, structure preferences.
- If unknown, use sensible defaults and empty lists.
- Do not include markdown or explanations.

REQUESTER BRIEF:
{focus_excerpt}

CONTEXT:
{context_excerpt}
"""


def _reconcile_generation_spec_with_agent(
    presentation_focus: str,
    research_text: str,
    openclaw_session_id: str | None
) -> dict:
    default_slide_count = _infer_slide_count_from_context(research_text, default=8)
    fallback_spec = _normalize_reconciled_generation_spec({}, default_slide_count)
    prompt = _build_prompt_reconciliation_prompt(presentation_focus, research_text, default_slide_count)

    result = ask_openclaw(
        message=prompt,
        session_id=openclaw_session_id,
        timeout=PROMPT_RECONCILIATION_TIMEOUT_SECONDS
    )
    if not result.get("success"):
        return {**fallback_spec, "source": "fallback", "error": result.get("error", "reconciliation_failed")}

    payload = _extract_json_payload(result.get("output", ""))
    if not payload:
        return {**fallback_spec, "source": "fallback", "error": "reconciliation_unreadable_json"}

    normalized = _normalize_reconciled_generation_spec(payload, default_slide_count)
    normalized["source"] = "agent_reconciled"
    return normalized


def _generate_ppt_via_slidespeak(
    presentation_focus: str,
    research_text: str,
    generation_spec: dict | None = None,
    filename_hint: str | None = None
) -> dict:
    if not os.path.isdir(SLIDESPEAK_SKILL_DIR):
        raise RuntimeError(f"SlideSpeak skill directory not found: {SLIDESPEAK_SKILL_DIR}")
    if not os.environ.get("SLIDESPEAK_API_KEY"):
        raise RuntimeError("SLIDESPEAK_API_KEY is not set in backend environment")

    os.makedirs(PPT_OUTPUT_DIR, exist_ok=True)
    deadline_epoch = time.time() + SLIDESPEAK_MAX_WAIT_SECONDS

    focus_text = (presentation_focus or "").strip() or "the requester brief"
    focus_excerpt = focus_text[:2000] + ("..." if len(focus_text) > 2000 else "")
    normalized_spec = _normalize_reconciled_generation_spec(
        generation_spec,
        _infer_slide_count_from_context(research_text, default=8)
    )
    slide_count = normalized_spec["slide_count"]
    research_excerpt = research_text[:8000]

    extra_sections: list[str] = []
    if normalized_spec["design_instructions"]:
        extra_sections.append(f"Design/style instructions:\n{normalized_spec['design_instructions']}")
    if normalized_spec["content_instructions"]:
        extra_sections.append(f"Content shaping instructions:\n{normalized_spec['content_instructions']}")
    if normalized_spec["must_include"]:
        extra_sections.append(
            "Must include:\n" + "\n".join(f"- {item}" for item in normalized_spec["must_include"])
        )
    if normalized_spec["must_avoid"]:
        extra_sections.append(
            "Must avoid:\n" + "\n".join(f"- {item}" for item in normalized_spec["must_avoid"])
        )
    spec_block = "\n\n".join(extra_sections)

    generation_prompt = (
        "Create a high-content professional presentation.\n\n"
        "HARD REQUIREMENTS:\n"
        f"- Create exactly {slide_count} slides.\n"
        "- Follow the provided slide outline as the primary structure.\n"
        "- Each slide must contain a clear title plus 4-6 content-rich bullets.\n"
        "- Bullets should be specific and informative, with concrete facts, names, dates, or examples when available.\n"
        "- Incorporate all refinement requests and collaboration constraints from the context.\n"
        "- Avoid vague, generic, or one-line placeholder bullets.\n\n"
        f"Requester brief (highest priority):\n{focus_excerpt}\n\n"
        f"Research, outline, and refinement context:\n{research_excerpt}"
    )
    if spec_block:
        generation_prompt += f"\n\nRECONCILED REQUESTER INSTRUCTIONS (APPLY THESE):\n{spec_block}"

    generate_args = [
        "generate",
        "--text", generation_prompt,
        "--length", str(slide_count),
        "--tone", normalized_spec["tone"],
        "--verbosity", normalized_spec["verbosity"],
        "--timeout", str(SLIDESPEAK_GENERATE_TIMEOUT_SECONDS),
    ]
    if normalized_spec["include_cover"] is not True:
        generate_args.append("--no-cover")
    if normalized_spec["include_toc"] is not True:
        generate_args.append("--no-toc")

    generate_data = _run_slidespeak_command(
        generate_args,
        timeout_seconds=SLIDESPEAK_GENERATE_TIMEOUT_SECONDS + SLIDESPEAK_COMMAND_BUFFER_SECONDS
    )

    task_id = str(generate_data.get("task_id", "")).strip()
    if generate_data.get("complete") is False and task_id:
        generate_data = _poll_slidespeak_status(task_id, deadline_epoch)

    request_id = _deep_find_first(generate_data, {"requestid"})
    if not request_id:
        raise RuntimeError("SlideSpeak generation finished but no request_id was returned")

    download_data = _run_slidespeak_command(
        ["download", request_id],
        timeout_seconds=SLIDESPEAK_DOWNLOAD_TIMEOUT_SECONDS + SLIDESPEAK_COMMAND_BUFFER_SECONDS
    )
    download_url = _deep_find_first(download_data, {"downloadurl", "url"})
    if not download_url:
        raise RuntimeError("SlideSpeak download response did not include a download URL")

    base_name = _sanitize_topic_for_filename(filename_hint or focus_text)
    filename = f"{base_name}_{int(time.time())}.pptx"
    file_path = os.path.join(PPT_OUTPUT_DIR, filename)
    file_size = _download_to_file(download_url, file_path)
    if file_size <= 0:
        raise RuntimeError("Downloaded PPT file is empty")

    return {
        "file_name": filename,
        "file_path": file_path,
        "file_size": file_size,
        "file_size_formatted": f"{file_size / 1024:.1f} KB",
        "request_id": request_id,
        "task_id": task_id or None,
        "generation_spec": normalized_spec,
    }


def start_ppt_generation(
    workflow_id: int,
    research_text: str,
    presentation_focus: str,
    filename_hint: str | None = None
):
    """
    Launch a background thread to generate a PPT via SlideSpeak.
    """
    thread = threading.Thread(
        target=_run_ppt_generation_thread,
        args=(workflow_id, research_text, presentation_focus, filename_hint),
        daemon=True
    )
    thread.start()
    return thread


def _run_ppt_generation_thread(
    workflow_id: int,
    research_text: str,
    presentation_focus: str,
    filename_hint: str | None = None
):
    """Background thread: runs SlideSpeak generation and persists workflow updates."""
    db = SessionLocal()
    gen_step = None
    try:
        workflow = get_workflow_by_id(db, workflow_id)
        if not workflow:
            return

        # Create the generation step
        next_step_order = max((s.step_order for s in workflow.steps), default=0) + 1
        gen_step = create_workflow_step(
            db, workflow_id=workflow_id,
            step_order=next_step_order,
            step_type="agent_generation",
            provider_type="agent",
            input_data={
                "presentation_focus_preview": (presentation_focus or "")[:1000],
                "filename_hint": filename_hint,
                "research_preview": research_text[:500]
            }
        )

        update_workflow_status(db, workflow_id, "generating_ppt")
        update_step_status(db, gen_step.id, "in_progress")

        create_event(
            db, workflow_id=workflow_id, event_type="generation_started",
            actor_type="agent", step_id=gen_step.id,
            message="SlideSpeak PPT generation started"
        )

        session_id = workflow.openclaw_session_id
        if not session_id:
            session_id = f"workflow-{generate_session_id()}"
            update_workflow_status(db, workflow_id, "generating_ppt", openclaw_session_id=session_id)

        generation_spec = _reconcile_generation_spec_with_agent(
            presentation_focus=presentation_focus,
            research_text=research_text,
            openclaw_session_id=session_id
        )
        spec_summary = (
            f"Prompt reconciliation applied: {generation_spec.get('slide_count', 8)} slides, "
            f"tone={generation_spec.get('tone', 'professional')}, "
            f"verbosity={generation_spec.get('verbosity', 'text-heavy')}, "
            f"source={generation_spec.get('source', 'fallback')}"
        )
        create_event(
            db, workflow_id=workflow_id, event_type="generation_reconciled",
            actor_type="agent", step_id=gen_step.id,
            message=spec_summary
        )
        update_step_status(
            db,
            gen_step.id,
            "in_progress",
            output_data={"generation_spec": generation_spec}
        )

        ppt_result = _generate_ppt_via_slidespeak(
            presentation_focus=presentation_focus,
            research_text=research_text,
            generation_spec=generation_spec,
            filename_hint=filename_hint
        )

        # Guardrail: ignore late PPT completion if this run was cancelled/failed meanwhile.
        current_workflow = get_workflow_by_id(db, workflow_id)
        current_gen_step = get_step_by_id(db, gen_step.id) if gen_step else None
        if (not current_workflow or current_workflow.status != "generating_ppt"
                or not current_gen_step or current_gen_step.status == "failed"):
            print(f"[Workflow {workflow_id}] PPT result ignored because workflow state changed.")
            return

        update_step_status(
            db, gen_step.id, "completed",
            output_data=ppt_result
        )

        linked_request_id = None
        for step in workflow.steps:
            payload = step.input_data or {}
            if isinstance(payload, dict) and payload.get("request_id"):
                linked_request_id = payload.get("request_id")
                break
        if linked_request_id:
            linked_request = get_work_request_by_id(db, linked_request_id)
            if linked_request and linked_request.status != "completed":
                linked_request.status = "completed"

        update_workflow_status(db, workflow_id, "completed")
        create_event(
            db, workflow_id=workflow_id,
            event_type="generation_completed",
            actor_type="agent", step_id=gen_step.id,
            message=f"PowerPoint generated: {ppt_result['file_name']}"
        )

        # Notify via Slack
        try:
            from slack_service import notify_ppt_complete
            notify_ppt_complete(workflow_id, filename_hint or presentation_focus, ppt_result["file_name"])
        except Exception:
            pass

    except Exception as e:
        error_msg = str(e) or "Unknown PPT generation error"
        if isinstance(e, TimeoutError):
            error_msg = f"PPT generation timed out after {SLIDESPEAK_MAX_WAIT_SECONDS // 60} minutes"
        print(f"[Workflow {workflow_id}] EXCEPTION in PPT generation thread: {error_msg}")
        import traceback
        traceback.print_exc()
        try:
            if gen_step:
                update_step_status(db, gen_step.id, "failed", output_data={"error": error_msg})
            update_workflow_status(db, workflow_id, "failed")
            create_event(
                db, workflow_id=workflow_id, event_type="failed",
                actor_type="system", step_id=gen_step.id if gen_step else None,
                message=error_msg
            )
        except Exception:
            pass
    finally:
        db.close()
