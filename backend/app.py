from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
import os
import subprocess
import time
from dotenv import load_dotenv
import requests
from openclaw_client import ask_openclaw

# Load environment variables from .env file inside backend folder
env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=env_path)

# Initialize Flask app
app = Flask(__name__)

# Configure CORS
CORS(app, 
    origins=["http://localhost:5173", "http://localhost:5174"],
    allow_headers=["Content-Type"],
    methods=["GET", "POST", "OPTIONS"])

# Add CORS headers to all responses
@app.after_request
def add_cors_headers(response):
    origin = request.headers.get('Origin')
    if origin in ["http://localhost:5173", "http://localhost:5174"]:
        response.headers['Access-Control-Allow-Origin'] = origin
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

@app.route('/')
def health_check():
    return "OK", 200

# Handle preflight OPTIONS requests explicitly
@app.route('/generate', methods=['OPTIONS'])
@app.route('/research', methods=['OPTIONS'])
def handle_options():
    response = make_response()
    origin = request.headers.get('Origin')
    if origin in ["http://localhost:5173", "http://localhost:5174"]:
        response.headers['Access-Control-Allow-Origin'] = origin
    response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

# Main route to generate a research proposal as a Google Doc
@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.json
        if not data or not data.get('prompt'):
            return jsonify({'error': 'Research topic is required'}), 400

        topic = data['prompt'].strip()
        
        # Craft a prompt that instructs OpenClaw to:
        # 1. Research the topic
        # 2. Create a structured project proposal
        # 3. Save it as a Google Doc using the gog skill
        # Simple prompt: research and return proposal as text
        prompt = f"""Research this topic using web_search: "{topic}"

Based on your research findings, write a comprehensive project proposal with these sections:

1. **Executive Summary** (2-3 paragraphs)
2. **Problem Statement** - What problem does this address?
3. **Background & Key Findings** - Include facts from your research
4. **Proposed Solution** - Detailed approach
5. **Methodology** - How to execute
6. **Timeline & Milestones** - Key phases
7. **Expected Outcomes** - What success looks like
8. **Risks & Mitigation** - Challenges and solutions
9. **Conclusion** - Summary and next steps

Execute the web search NOW, then write the full proposal. Return the complete proposal text."""

        # Call OpenClaw via CLI
        result = ask_openclaw(
            message=prompt,
            session_id="proposal_session",
            timeout=180  # 3 minutes for research
        )

        if not result.get("success"):
            print(f"OpenClaw error: {result.get('error', 'Unknown error')}")
            return jsonify({'error': 'Failed to generate proposal', 'details': result.get('output', '')}), 500

        output = result.get('output', '').strip()
        
        return jsonify({
            'response': output,
            'type': 'text',
            'message': 'Research proposal generated!'
        }), 200

    except Exception as e:
        print(f"Error generating proposal: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Failed to generate proposal'}), 500

@app.route('/research', methods=['POST'])
def research():
    try:
        data = request.json
        topic = data.get('topic')
        if not topic:
            return jsonify({'error': 'Topic is required'}), 400

        # Construct the prompt
        prompt = (
            f"Research the following topic: '{topic}'. "
            f"Then, create a PowerPoint presentation with 5 slides summarizing your findings. "
            f"Write a Python script that uses the python-pptx library. "
            f"The script should create slides with titles and bullet points. "
            f"Save the file as 'research_output.pptx'. "
            f"Execute the script to generate the file. "
            f"Return a confirmation when done."
        )
        
        # Use CLI to communicate with OpenClaw
        print(f"Sending request to OpenClaw via CLI...")
        result = ask_openclaw(
            message=prompt,
            session_id="research_session"
        )
        
        if not result.get("success"):
            print(f"OpenClaw error: {result.get('error', 'Unknown error')}")
            return jsonify({
                'error': 'OpenClaw failed to process research',
                'details': result.get('output', '')
            }), 500

        # OpenClaw saves files to its workspace directory
        openclaw_workspace = os.path.expanduser('~/.openclaw/workspace')
        output_path = os.path.join(openclaw_workspace, 'research_output.pptx')
        
        time.sleep(2)

        if os.path.exists(output_path):
            return jsonify({
                'message': 'Research completed and PowerPoint generated!',
                'file_name': 'research_output.pptx',
                'preview_text': result.get('summary', result.get('output', '')[:500])
            }), 200
        else:
            return jsonify({
                'error': 'Research finished but no PowerPoint file was found.',
                'log': result.get('output', ''),
                'summary': result.get('summary', '')
            }), 500

    except Exception as e:
        print(f"Error in research: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
