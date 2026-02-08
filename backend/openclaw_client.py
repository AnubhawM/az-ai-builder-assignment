"""
OpenClaw CLI Client
Handles communication with OpenClaw via subprocess CLI calls.
This is simpler and more robust than the WebSocket approach.
"""

import subprocess
import json
import uuid


def ask_openclaw(message: str, session_id: str = None, timeout: int = 300, use_json: bool = True) -> dict:
    """
    Send a message to OpenClaw agent via CLI and get the response.
    
    Args:
        message: The message/prompt to send to the agent
        session_id: Optional session ID for conversation continuity
        timeout: Command timeout in seconds (default 300 = 5 minutes)
        use_json: Whether to request JSON output (default True)
    
    Returns:
        dict with 'success', 'output', and optionally 'error' keys
    """
    # Build the command
    cmd = ["openclaw", "agent", "--message", message]
    
    if session_id:
        cmd.extend(["--session-id", session_id])
    
    if use_json:
        cmd.append("--json")
    
    cmd.extend(["--timeout", str(timeout)])
    
    try:
        print(f"Running OpenClaw command: {' '.join(cmd[:4])}...")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 30  # Give subprocess a bit more time than the agent timeout
        )
        
        # Check for errors
        if result.returncode != 0:
            print(f"OpenClaw CLI error (exit code {result.returncode})")
            print(f"Stderr: {result.stderr}")
            return {
                "success": False,
                "output": result.stdout,
                "error": result.stderr or f"Exit code {result.returncode}"
            }
        
        # Parse JSON output if requested
        if use_json:
            try:
                # The output might have deprecation warnings before the JSON
                # Find the JSON part (starts with { or [)
                stdout = result.stdout.strip()
                json_start = stdout.find('{')
                if json_start == -1:
                    json_start = stdout.find('[')
                
                if json_start != -1:
                    json_str = stdout[json_start:]
                    parsed = json.loads(json_str)
                    
                    # Handle OpenClaw's actual response format
                    # The response has: result.payloads[].text
                    output_text = ""
                    if "result" in parsed and "payloads" in parsed["result"]:
                        payloads = parsed["result"]["payloads"]
                        # Get the last (most complete) payload text
                        for payload in payloads:
                            if payload.get("text"):
                                output_text = payload["text"]  # Keep overwriting to get the last one
                    elif "reply" in parsed:
                        output_text = parsed["reply"]
                    elif "output" in parsed:
                        output_text = parsed["output"]
                    else:
                        output_text = str(parsed)
                    
                    return {
                        "success": parsed.get("status") == "ok" if "status" in parsed else True,
                        "output": output_text,
                        "raw": parsed
                    }
                else:
                    # No JSON found, return as plain text
                    return {
                        "success": True,
                        "output": stdout
                    }
            except json.JSONDecodeError as e:
                print(f"Failed to parse JSON: {e}")
                return {
                    "success": True,
                    "output": result.stdout.strip()
                }
        else:
            return {
                "success": True,
                "output": result.stdout.strip()
            }
            
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "output": "",
            "error": f"Command timed out after {timeout} seconds"
        }
    except FileNotFoundError:
        return {
            "success": False,
            "output": "",
            "error": "OpenClaw CLI not found. Make sure 'openclaw' is installed and in your PATH."
        }
    except Exception as e:
        return {
            "success": False,
            "output": "",
            "error": str(e)
        }


def generate_session_id() -> str:
    """Generate a unique session ID for conversation continuity."""
    return str(uuid.uuid4())[:8]


if __name__ == "__main__":
    # Test the client
    print("Testing OpenClaw CLI client...")
    result = ask_openclaw("What is 2 + 2?")
    print(f"Result: {result}")
