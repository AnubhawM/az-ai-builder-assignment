"""
Slack Service — Outbound notifications for the AIXplore Capability Exchange.

Sends interactive messages to Slack when:
- Research is complete and ready for review
- PPT generation is finished
- A workflow needs attention

Inbound Slack interactions (button clicks) are handled in workflow_routes.py.
"""

import os
import json
from dotenv import load_dotenv

load_dotenv()

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID", "")


def is_configured() -> bool:
    """Check if Slack integration is properly configured."""
    return bool(
        SLACK_BOT_TOKEN
        and SLACK_BOT_TOKEN != "xoxb-your-bot-token-here"
        and SLACK_CHANNEL_ID
        and SLACK_CHANNEL_ID != "C0XXXXXXX"
    )


def _get_slack_client():
    """Get an authenticated Slack WebClient."""
    if not is_configured():
        return None
    try:
        from slack_sdk import WebClient
        return WebClient(token=SLACK_BOT_TOKEN)
    except ImportError:
        print("[Slack] slack_sdk not installed. Run: pip install slack-sdk")
        return None


def notify_research_complete(
    workflow_id: int,
    topic: str,
    summary: str,
    is_refinement: bool = False,
    iteration: int = 0
) -> bool:
    """
    Send a Slack notification when research is ready for review.
    Includes Approve/Refine interactive buttons.
    """
    client = _get_slack_client()
    if not client:
        print(f"[Slack] Not configured — skipping notification for workflow {workflow_id}")
        return False

    # Truncate summary for Slack (max ~3000 chars for a block)
    display_summary = summary[:800] + ("..." if len(summary) > 800 else "")

    header_text = (
        f"🔄 Refinement Round {iteration} Complete"
        if is_refinement
        else "🔬 Research Complete — Ready for Review"
    )

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": header_text}
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Topic:* {topic}\n*Workflow ID:* {workflow_id}"
            }
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Executive Summary:*\n{display_summary}"
            }
        },
        {"type": "divider"},
        {
            "type": "actions",
            "block_id": f"review_actions_{workflow_id}",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✅ Approve"},
                    "style": "primary",
                    "action_id": "approve_research",
                    "value": json.dumps({"workflow_id": workflow_id})
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "🔄 Request Refinement"},
                    "action_id": "refine_research",
                    "value": json.dumps({"workflow_id": workflow_id})
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "🌐 Open in Web App"},
                    "url": f"http://localhost:5173/workflows/{workflow_id}",
                    "action_id": "open_web_app"
                }
            ]
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "💡 _For detailed review with slide outline and full research data, use the web app._"
                }
            ]
        }
    ]

    try:
        response = client.chat_postMessage(
            channel=SLACK_CHANNEL_ID,
            text=f"Research ready for review: {topic}",  # Fallback text
            blocks=blocks
        )
        print(f"[Slack] Notification sent for workflow {workflow_id}: {response['ts']}")
        return True
    except Exception as e:
        print(f"[Slack] Failed to send notification: {e}")
        return False


def notify_ppt_complete(workflow_id: int, topic: str, filename: str) -> bool:
    """Send a Slack notification when PPT generation is finished."""
    client = _get_slack_client()
    if not client:
        return False

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "📊 PowerPoint Generated!"}
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Topic:* {topic}\n"
                    f"*File:* `{filename}`\n"
                    f"*Workflow ID:* {workflow_id}"
                )
            }
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "🌐 View in Web App"},
                    "url": f"http://localhost:5173/workflows/{workflow_id}",
                    "action_id": "view_completed"
                }
            ]
        }
    ]

    try:
        response = client.chat_postMessage(
            channel=SLACK_CHANNEL_ID,
            text=f"PowerPoint generated: {filename}",
            blocks=blocks
        )
        print(f"[Slack] PPT completion notification sent: {response['ts']}")
        return True
    except Exception as e:
        print(f"[Slack] Failed to send PPT notification: {e}")
        return False


def update_slack_message(channel: str, message_ts: str, new_text: str) -> bool:
    """Update an existing Slack message (e.g., after approval via Slack button)."""
    client = _get_slack_client()
    if not client:
        return False

    try:
        client.chat_update(
            channel=channel,
            ts=message_ts,
            text=new_text,
            blocks=[
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": new_text}
                }
            ]
        )
        return True
    except Exception as e:
        print(f"[Slack] Failed to update message: {e}")
        return False
