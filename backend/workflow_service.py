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
from database import SessionLocal
from database.models import Workflow, WorkflowStep
from crud import (
    get_workflow_by_id, update_workflow_status,
    create_workflow_step, get_active_step,
    update_step_status, increment_step_iteration,
    create_event, create_workflow_message,
    get_user_by_email, get_work_request_by_id
)
from openclaw_client import ask_openclaw, generate_session_id
from openclaw_webhook_client import trigger_agent

# PPT output directory (shared with existing PPT generation logic)
PPT_OUTPUT_DIR = "/Users/anubhawmathur/development/ppt-output"


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
- [Key point 1]
- [Key point 2]
- [Key point 3]

Slide 2: [Title]
- [Key point 1]
- [Key point 2]
- [Key point 3]

(Continue for all {num_slides} slides)

=== RAW RESEARCH ===
Include your complete research findings with all data points, statistics, sources, and detailed information gathered from your web search.

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

Make sure to incorporate the reviewer's feedback while preserving the valuable parts of your original research."""


def start_research(workflow_id: int, topic: str, openclaw_session_id: str, request_description: str = ""):
    """
    Launch a background thread to run OpenClaw research.
    Updates the database with results when complete.
    """
    thread = threading.Thread(
        target=_run_research_thread,
        args=(workflow_id, topic, openclaw_session_id, request_description),
        daemon=True
    )
    thread.start()
    return thread


def _run_research_thread(workflow_id: int, topic: str, openclaw_session_id: str, request_description: str = ""):
    """Background thread: executes OpenClaw research and updates DB."""
    db = SessionLocal()
    try:
        # Update workflow status to researching
        update_workflow_status(db, workflow_id, "researching")

        # Get the active research step
        step = get_active_step(db, workflow_id)
        if not step:
            print(f"[Workflow {workflow_id}] ERROR: No active step found")
            return
        update_step_status(db, step.id, "in_progress")

        # Log the research start event
        create_event(
            db, workflow_id=workflow_id, event_type="research_started",
            actor_type="agent", step_id=step.id,
            message=f"OpenClaw agent started researching: {topic}"
        )

        # Build prompt and call OpenClaw (synchronous — blocks this thread)
        prompt = _build_research_prompt(topic, request_description=request_description)
        print(f"[Workflow {workflow_id}] Starting OpenClaw research...")

        result = ask_openclaw(
            message=prompt,
            session_id=openclaw_session_id,
            timeout=300  # 5 minutes
        )

        if result.get("success"):
            output = result.get("output", "")
            parsed = parse_research_output(output)

            # Mark research step as complete
            update_step_status(db, step.id, "completed", output_data=parsed)

            # Get workflow owner for review assignment
            workflow = get_workflow_by_id(db, workflow_id)

            # Create the human review step (assigned to the workflow owner)
            review_step = create_workflow_step(
                db, workflow_id=workflow_id, step_order=2,
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

        # Find the research step (step_order=1) to update its output
        workflow = get_workflow_by_id(db, workflow_id)
        research_step = None
        for step in workflow.steps:
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

        if result.get("success"):
            output = result.get("output", "")
            parsed = parse_research_output(output)

            # Update research step with refined output
            update_step_status(db, research_step.id, "completed", output_data=parsed)

            # Update the review step back to awaiting_input
            review_step = None
            for step in workflow.steps:
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
    recent_chat_context: str
) -> str:
    return f"""You are OpenClaw, collaborating inside the AIXplore Capability Exchange.

WORKFLOW TITLE: {workflow_title}
WORKFLOW TYPE: {workflow_type}

RECENT CHAT CONTEXT:
{recent_chat_context}

LATEST HUMAN MESSAGE:
{latest_user_message}

INSTRUCTIONS:
1. Reply as a practical collaborator in 1-4 short paragraphs.
2. If asked for revisions, return actionable edits and checks.
3. If the request is about presentation quality, include concrete guidance for SlideSpeak/PPT updates.
4. If information is missing, ask concise clarifying questions.
5. Do not mention internal tooling or hidden reasoning.
"""


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
        prompt = _build_agent_chat_prompt(
            workflow_title=workflow.title,
            workflow_type=workflow.workflow_type,
            latest_user_message=latest_user_message,
            recent_chat_context=recent_chat_context
        )

        result = ask_openclaw(
            message=prompt,
            session_id=session_id,
            timeout=180
        )

        openclaw_user = get_user_by_email(db, "agent@openclaw.ai")
        if result.get("success"):
            reply = (result.get("output") or "").strip()
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

def start_ppt_generation(workflow_id: int, research_text: str, topic: str):
    """
    Launch a background thread to generate a PPT via SlideSpeak
    and poll for the output file.
    """
    thread = threading.Thread(
        target=_run_ppt_generation_thread,
        args=(workflow_id, research_text, topic),
        daemon=True
    )
    thread.start()
    return thread


def _run_ppt_generation_thread(workflow_id: int, research_text: str, topic: str):
    """Background thread: triggers SlideSpeak + polls for PPT file."""
    db = SessionLocal()
    try:
        workflow = get_workflow_by_id(db, workflow_id)

        # Create the generation step
        next_step_order = max((s.step_order for s in workflow.steps), default=0) + 1
        gen_step = create_workflow_step(
            db, workflow_id=workflow_id,
            step_order=next_step_order,
            step_type="agent_generation",
            provider_type="agent",
            input_data={"topic": topic, "research_preview": research_text[:500]}
        )

        update_workflow_status(db, workflow_id, "generating_ppt")
        update_step_status(db, gen_step.id, "in_progress")

        create_event(
            db, workflow_id=workflow_id, event_type="generation_started",
            actor_type="agent", step_id=gen_step.id,
            message="SlideSpeak PPT generation started"
        )

        # Build the SlideSpeak prompt (reusing the pattern from the existing generate-ppt endpoint)
        sanitized_topic = topic.strip()[:100]
        prompt = f"""You are tasked with creating a professional PowerPoint presentation. Follow these steps:

STEP 1 - USE RESEARCH:
You have already researched this topic. Here is a summary of your findings:

{research_text[:2000]}

STEP 2 - GENERATE POWERPOINT:
Use the slidespeak skill to generate a PowerPoint presentation.

Run this command from the slidespeak skill directory (/Users/anubhawmathur/.openclaw/workspace/skills/slidespeak):
```bash
cd /Users/anubhawmathur/.openclaw/workspace/skills/slidespeak && node scripts/slidespeak.mjs generate --text "Based on research: {research_text[:500]}. Create a professional presentation about: {sanitized_topic}" --length 8 --tone professional
```

STEP 3 - DOWNLOAD AND SAVE:
After generation completes, the slidespeak script will return a request_id. Use it to download:
```bash
cd /Users/anubhawmathur/.openclaw/workspace/skills/slidespeak && node scripts/slidespeak.mjs download <request_id>
```

Download the file using curl and save it:
```bash
curl -L "<download_url>" -o "{PPT_OUTPUT_DIR}/{sanitized_topic.replace(' ', '_').lower()}.pptx"
```

Save the file ONLY to: {PPT_OUTPUT_DIR}
Use a descriptive filename based on the topic."""

        # Record the timestamp before triggering generation
        start_timestamp = time.time()

        # Trigger via webhook (fire-and-forget)
        result = trigger_agent(
            message=prompt,
            name="SlideSpeak-PPT",
            session_key=workflow.openclaw_session_id,
            timeout_seconds=300,
            thinking="medium"
        )

        if not result.get("success"):
            error_msg = result.get("error", "Failed to trigger generation")
            update_step_status(db, gen_step.id, "failed",
                               output_data={"error": error_msg})
            update_workflow_status(db, workflow_id, "failed")
            create_event(
                db, workflow_id=workflow_id, event_type="failed",
                actor_type="agent", step_id=gen_step.id,
                message=f"PPT generation trigger failed: {error_msg}"
            )
            return

        # Poll for the PPT file (check every 5 seconds for up to 5 minutes)
        print(f"[Workflow {workflow_id}] Polling for PPT file...")
        max_attempts = 60
        poll_interval = 5

        for attempt in range(max_attempts):
            time.sleep(poll_interval)

            # Check for new .pptx files created after our start timestamp
            if os.path.exists(PPT_OUTPUT_DIR):
                for filename in os.listdir(PPT_OUTPUT_DIR):
                    if filename.endswith('.pptx'):
                        filepath = os.path.join(PPT_OUTPUT_DIR, filename)
                        file_mtime = os.stat(filepath).st_mtime
                        file_size = os.stat(filepath).st_size

                        if file_mtime > start_timestamp and file_size > 0:
                            # Found the generated file!
                            print(f"[Workflow {workflow_id}] PPT found: {filename}")

                            update_step_status(
                                db, gen_step.id, "completed",
                                output_data={
                                    "file_name": filename,
                                    "file_path": filepath,
                                    "file_size": file_size,
                                    "file_size_formatted": f"{file_size / 1024:.1f} KB",
                                }
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
                                message=f"PowerPoint generated: {filename}"
                            )

                            # Notify via Slack
                            try:
                                from slack_service import notify_ppt_complete
                                notify_ppt_complete(workflow_id, topic, filename)
                            except Exception:
                                pass

                            return

            if attempt % 6 == 0 and attempt > 0:
                print(f"[Workflow {workflow_id}] Still polling... ({attempt * poll_interval}s)")

        # Timeout — no file found
        update_step_status(
            db, gen_step.id, "failed",
            output_data={"error": "Timed out waiting for PPT file"}
        )
        update_workflow_status(db, workflow_id, "failed")
        create_event(
            db, workflow_id=workflow_id, event_type="failed",
            actor_type="system", step_id=gen_step.id,
            message="PPT generation timed out after 5 minutes"
        )

    except Exception as e:
        print(f"[Workflow {workflow_id}] EXCEPTION in PPT generation thread: {e}")
        import traceback
        traceback.print_exc()
        try:
            update_workflow_status(db, workflow_id, "failed")
        except Exception:
            pass
    finally:
        db.close()
