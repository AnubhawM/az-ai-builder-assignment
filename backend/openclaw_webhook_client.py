"""
OpenClaw Webhook Client
Handles communication with OpenClaw via HTTP Webhook API.
Uses the /hooks/agent endpoint for async agent runs.
"""

import requests
import json
import os
from typing import Optional

# Default OpenClaw gateway configuration
OPENCLAW_HOST = os.getenv("OPENCLAW_HOST", "http://127.0.0.1")
OPENCLAW_PORT = os.getenv("OPENCLAW_PORT", "18789")
OPENCLAW_TOKEN = os.getenv("OPENCLAW_TOKEN", "f768fadd060a1c0c4c502e6708c9d9623a5410854de2a87b")

def get_openclaw_url() -> str:
    """Get the base URL for OpenClaw webhook endpoints."""
    return f"{OPENCLAW_HOST}:{OPENCLAW_PORT}"


def trigger_agent(
    message: str,
    name: Optional[str] = None,
    session_key: Optional[str] = None,
    timeout_seconds: int = 300,
    model: Optional[str] = None,
    thinking: str = "medium"
) -> dict:
    """
    Trigger an OpenClaw agent run via the webhook API.
    
    Args:
        message: The prompt or message for the agent to process
        name: Human-readable name for the hook (e.g., "SlideSpeak")
        session_key: Optional session key for conversation continuity
        timeout_seconds: Maximum duration for the agent run
        model: Optional model override
        thinking: Thinking level (low, medium, high)
    
    Returns:
        dict with success status and response data
    """
    url = f"{get_openclaw_url()}/hooks/agent"
    
    headers = {
        "Authorization": f"Bearer {OPENCLAW_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "message": message,
        "wakeMode": "now",
        "deliver": False,  # Don't deliver to messaging channel
        "timeoutSeconds": timeout_seconds
    }
    
    if name:
        payload["name"] = name
    
    if session_key:
        payload["sessionKey"] = session_key
    
    if model:
        payload["model"] = model
    
    if thinking:
        payload["thinking"] = thinking
    
    try:
        print(f"Triggering OpenClaw agent via webhook: {url}")
        print(f"Payload: {json.dumps(payload, indent=2)}")
        
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        
        if response.status_code == 202:
            # Async run started successfully
            return {
                "success": True,
                "status": "accepted",
                "message": "Agent task started successfully",
                "data": response.json() if response.text else {}
            }
        elif response.status_code == 200:
            return {
                "success": True,
                "status": "completed",
                "data": response.json() if response.text else {}
            }
        elif response.status_code == 401:
            return {
                "success": False,
                "error": "Authentication failed. Check OPENCLAW_TOKEN.",
                "status_code": response.status_code
            }
        elif response.status_code == 400:
            return {
                "success": False,
                "error": f"Invalid payload: {response.text}",
                "status_code": response.status_code
            }
        else:
            return {
                "success": False,
                "error": f"Unexpected response: {response.status_code} - {response.text}",
                "status_code": response.status_code
            }
            
    except requests.exceptions.ConnectionError:
        return {
            "success": False,
            "error": f"Could not connect to OpenClaw at {url}. Is OpenClaw running?"
        }
    except requests.exceptions.Timeout:
        return {
            "success": False,
            "error": "Request timed out"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def wake_agent(text: str, mode: str = "now") -> dict:
    """
    Wake the OpenClaw agent with a system event.
    
    Args:
        text: Description of the event
        mode: "now" for immediate heartbeat, "next-heartbeat" to wait
    
    Returns:
        dict with success status
    """
    url = f"{get_openclaw_url()}/hooks/wake"
    
    headers = {
        "Authorization": f"Bearer {OPENCLAW_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "text": text,
        "mode": mode
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        
        if response.status_code == 200:
            return {"success": True, "message": "Agent woken successfully"}
        else:
            return {
                "success": False,
                "error": f"Failed to wake agent: {response.status_code} - {response.text}"
            }
            
    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    # Test the webhook client
    print("Testing OpenClaw Webhook Client...")
    result = trigger_agent(
        message="Say hello!",
        name="Test",
        timeout_seconds=30
    )
    print(f"Result: {json.dumps(result, indent=2)}")
