from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
import os
import subprocess
import time
from dotenv import load_dotenv
import requests
from openclaw_client import ask_openclaw
from openclaw_webhook_client import trigger_agent

# Load environment variables from .env file inside backend folder
env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=env_path)

# Initialize Flask app
app = Flask(__name__)

# PowerPoint output directory
PPT_OUTPUT_DIR = "/Users/anubhawmathur/development/ppt-output"

# Ensure output directory exists
os.makedirs(PPT_OUTPUT_DIR, exist_ok=True)

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
@app.route('/generate-ppt', methods=['OPTIONS'])
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


@app.route('/generate-ppt', methods=['POST'])
def generate_ppt():
    """
    Generate a PowerPoint presentation using OpenClaw webhooks.
    Uses the /hooks/agent endpoint to trigger OpenClaw with SlideSpeak skill.
    """
    try:
        data = request.json
        topic = data.get('topic')
        
        if not topic:
            return jsonify({'error': 'Topic is required'}), 400

        # Sanitize the topic for filename generation
        sanitized_topic = topic.strip()[:100]  # Limit topic length for filename

        # Craft a comprehensive prompt that instructs OpenClaw to:
        # 1. Research the topic using web_search
        # 2. Generate a PowerPoint using the slidespeak skill
        # 3. Save it with a meaningful filename to the output directory
        prompt = f"""You are tasked with creating a professional PowerPoint presentation. Follow these steps:

STEP 1 - RESEARCH:
Use web_search to research this topic thoroughly: "{sanitized_topic}"

Gather key facts, statistics, and insights that would make a compelling presentation.

STEP 2 - GENERATE POWERPOINT:
After researching, use the slidespeak skill to generate a PowerPoint presentation.

Run this command from the slidespeak skill directory (/Users/anubhawmathur/.openclaw/workspace/skills/slidespeak):
```bash
cd /Users/anubhawmathur/.openclaw/workspace/skills/slidespeak && node scripts/slidespeak.mjs generate --text "Based on my research: [INCLUDE YOUR RESEARCH FINDINGS HERE]. Create a professional presentation about: {sanitized_topic}" --length 8 --tone professional
```

STEP 3 - DOWNLOAD AND SAVE:
After generation completes, the slidespeak script will return a request_id. Use it to download:
```bash
cd /Users/anubhawmathur/.openclaw/workspace/skills/slidespeak && node scripts/slidespeak.mjs download <request_id>
```

This will return a download URL. Download the file using curl and save it with a meaningful filename based on the topic:
```bash
curl -L "<download_url>" -o "{PPT_OUTPUT_DIR}/<meaningful_filename>.pptx"
```

IMPORTANT REQUIREMENTS:
- The filename should be descriptive and based on the topic (use underscores for spaces, lowercase)
- Example: "sustainable_energy_future.pptx" or "ai_healthcare_revolution.pptx"
- Save the file ONLY to this directory: {PPT_OUTPUT_DIR}
- Report back the exact filename you used

When you're done, provide a brief summary of:
1. What you researched
2. The filename you saved the PowerPoint as
3. The full path to the saved file"""

        print(f"Triggering OpenClaw webhook for PowerPoint generation...")
        print(f"Topic: {sanitized_topic}")
        print(f"Output directory: {PPT_OUTPUT_DIR}")

        # Use the webhook API to trigger the agent
        result = trigger_agent(
            message=prompt,
            name="SlideSpeak-PPT",
            session_key=f"ppt-gen-{int(time.time())}",
            timeout_seconds=300,  # 5 minutes for research + generation
            thinking="medium"
        )

        if not result.get("success"):
            print(f"Webhook trigger failed: {result.get('error', 'Unknown error')}")
            return jsonify({
                'error': 'Failed to trigger PowerPoint generation',
                'details': result.get('error', ''),
                'status': 'error',
                'output_directory': PPT_OUTPUT_DIR
            }), 500

        # The webhook API returns 202 for async runs
        # The task is now running in the background
        # Include timestamp so frontend can poll for files created after this time
        start_timestamp = time.time()
        
        return jsonify({
            'message': 'PowerPoint generation started! OpenClaw is researching your topic and generating the presentation. This typically takes 1-2 minutes.',
            'output_directory': PPT_OUTPUT_DIR,
            'status': 'pending',
            'start_timestamp': start_timestamp,
            'note': 'Check the output directory for your generated PowerPoint file.'
        }), 202

    except Exception as e:
        print(f"Error generating PowerPoint: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'error': str(e),
            'status': 'error',
            'output_directory': PPT_OUTPUT_DIR
        }), 500


@app.route('/check-ppt-status', methods=['GET'])
def check_ppt_status():
    """
    Check if new PowerPoint files have been created in the output directory.
    Used by frontend to poll for completion.
    
    Query params:
        - since: Unix timestamp to check for files created after this time
    """
    try:
        since_timestamp = request.args.get('since', type=float, default=0)
        
        if not os.path.exists(PPT_OUTPUT_DIR):
            return jsonify({
                'status': 'pending',
                'files': [],
                'message': 'Output directory does not exist yet'
            }), 200
        
        # Get all .pptx files in the output directory
        all_files = []
        new_files = []
        
        for filename in os.listdir(PPT_OUTPUT_DIR):
            if filename.endswith('.pptx'):
                filepath = os.path.join(PPT_OUTPUT_DIR, filename)
                file_stat = os.stat(filepath)
                file_info = {
                    'name': filename,
                    'path': filepath,
                    'size_bytes': file_stat.st_size,
                    'created_at': file_stat.st_mtime,
                    'size_formatted': f"{file_stat.st_size / 1024:.1f} KB"
                }
                all_files.append(file_info)
                
                # Check if file was created after the start timestamp
                if file_stat.st_mtime > since_timestamp:
                    new_files.append(file_info)
        
        # Sort by creation time (newest first)
        all_files.sort(key=lambda x: x['created_at'], reverse=True)
        new_files.sort(key=lambda x: x['created_at'], reverse=True)
        
        if new_files:
            return jsonify({
                'status': 'completed',
                'files': new_files,
                'all_files': all_files,
                'message': f'Found {len(new_files)} new PowerPoint file(s)!',
                'output_directory': PPT_OUTPUT_DIR
            }), 200
        else:
            return jsonify({
                'status': 'pending',
                'files': [],
                'all_files': all_files,
                'message': 'No new files yet. Still generating...',
                'output_directory': PPT_OUTPUT_DIR
            }), 200
            
    except Exception as e:
        print(f"Error checking PPT status: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


# Add OPTIONS handler for the new endpoint
@app.route('/check-ppt-status', methods=['OPTIONS'])
@app.route('/open-output-dir', methods=['OPTIONS'])
def handle_check_ppt_options():
    response = make_response()
    origin = request.headers.get('Origin')
    if origin in ["http://localhost:5173", "http://localhost:5174"]:
        response.headers['Access-Control-Allow-Origin'] = origin
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response


@app.route('/open-output-dir', methods=['POST'])
def open_output_dir():
    """
    Open the PPT output directory in the system file explorer (Finder on macOS).
    """
    try:
        if not os.path.exists(PPT_OUTPUT_DIR):
            os.makedirs(PPT_OUTPUT_DIR, exist_ok=True)
        
        # Use 'open' command on macOS to open Finder at the directory
        result = subprocess.run(['open', PPT_OUTPUT_DIR], capture_output=True, text=True)
        
        if result.returncode == 0:
            return jsonify({
                'success': True,
                'message': f'Opened {PPT_OUTPUT_DIR} in Finder',
                'directory': PPT_OUTPUT_DIR
            }), 200
        else:
            return jsonify({
                'success': False,
                'error': f'Failed to open directory: {result.stderr}'
            }), 500
            
    except Exception as e:
        print(f"Error opening output directory: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

