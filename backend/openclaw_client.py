"""
OpenClaw WebSocket Client
Handles communication with the OpenClaw Gateway via WebSocket protocol.
"""

import json
import uuid
import websocket
import threading
import time

class OpenClawClient:
    def __init__(self, gateway_url="ws://localhost:18789", token=None):
        self.gateway_url = gateway_url
        self.token = token
        self.ws = None
        self.connected = False
        self.responses = {}
        self.agent_output = {}
        self.lock = threading.Lock()
        
    def _generate_id(self):
        return str(uuid.uuid4())[:8]
    
    def connect(self):
        """Establish connection to OpenClaw Gateway"""
        self.ws = websocket.create_connection(self.gateway_url)
        
        # Send connect handshake
        connect_req = {
            "type": "req",
            "id": self._generate_id(),
            "method": "connect",
            "params": {
                "minProtocol": 1,
                "maxProtocol": 1,
                "client": {
                    "id": "python-backend",
                    "displayName": "Research Bot Backend",
                    "version": "1.0.0",
                    "platform": "python",
                    "mode": "headless"
                },
                "caps": ["agent"],
                "auth": {"token": self.token} if self.token else None
            }
        }
        
        self.ws.send(json.dumps(connect_req))
        response = json.loads(self.ws.recv())
        
        if response.get("ok"):
            self.connected = True
            return True
        else:
            raise Exception(f"Failed to connect: {response.get('error')}")
    
    def send_agent_request(self, message, session_id="research_session", timeout=120):
        """
        Send a message to the OpenClaw agent and wait for the response.
        Returns the full agent output.
        """
        if not self.connected:
            self.connect()
        
        req_id = self._generate_id()
        
        # Send the agent request
        agent_req = {
            "type": "req",
            "id": req_id,
            "method": "agent",
            "params": {
                "message": message,
                "sessionId": session_id
            }
        }
        
        self.ws.send(json.dumps(agent_req))
        
        # Collect responses and events
        output_parts = []
        run_id = None
        start_time = time.time()
        
        while True:
            if time.time() - start_time > timeout:
                raise TimeoutError("Agent request timed out")
            
            try:
                self.ws.settimeout(5.0)
                raw = self.ws.recv()
                frame = json.loads(raw)
            except websocket.WebSocketTimeoutException:
                continue
            except Exception as e:
                print(f"WebSocket error: {e}")
                break
            
            # Handle different frame types
            if frame.get("type") == "res" and frame.get("id") == req_id:
                payload = frame.get("payload", {})
                if payload.get("status") == "accepted":
                    run_id = payload.get("runId")
                    print(f"Agent request accepted, runId: {run_id}")
                elif payload.get("status") in ["ok", "error"]:
                    # Final response
                    return {
                        "success": payload.get("status") == "ok",
                        "output": "\n".join(output_parts),
                        "summary": payload.get("summary", ""),
                        "run_id": run_id
                    }
            
            elif frame.get("type") == "event" and frame.get("event") == "agent":
                # Streamed agent output
                payload = frame.get("payload", {})
                if "text" in payload:
                    output_parts.append(payload["text"])
                    print(f"Agent: {payload['text'][:100]}...")
                elif "content" in payload:
                    output_parts.append(str(payload["content"]))
            
            elif frame.get("type") == "event" and frame.get("event") == "tick":
                # Keepalive, ignore
                pass
        
        return {
            "success": False,
            "output": "\n".join(output_parts),
            "error": "Connection closed unexpectedly"
        }
    
    def close(self):
        """Close the WebSocket connection"""
        if self.ws:
            self.ws.close()
            self.connected = False


# Convenience function for one-shot requests
def ask_openclaw(message, session_id="research_session", gateway_url="ws://localhost:18789", token=None):
    """
    Send a message to OpenClaw and get the response.
    This is a convenience wrapper for simple use cases.
    """
    client = OpenClawClient(gateway_url=gateway_url, token=token)
    try:
        result = client.send_agent_request(message, session_id=session_id)
        return result
    finally:
        client.close()


if __name__ == "__main__":
    # Test the client
    result = ask_openclaw(
        "What is 2 + 2?",
        token="45f4aa260648382416916c336bec303480c6399348f0247c"
    )
    print(f"Result: {result}")
