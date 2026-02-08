from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
from openai import OpenAI
import os
import subprocess
import time
from dotenv import load_dotenv
import requests

# Load environment variables from .env file inside backend folder
env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=env_path)

client = OpenAI()

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

# Main route to generate a response from OpenAI API
@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.json
        if not data or not data.get('prompt'):
            return jsonify({'error': 'Prompt is required'}), 400

        # Call OpenAI API
        model = "gpt-4o-mini"
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": data['prompt']}
            ],
            max_tokens=500,
            temperature=0.7,
        )

        response_text = response.choices[0].message.content.strip()
        return jsonify({'response': response_text}), 200

    except Exception as e:
        print(f"Error generating response: {e}")
        return jsonify({'error': 'Failed to generate response'}), 500

@app.route('/research', methods=['POST'])
def research():
    try:
        from openclaw_client import ask_openclaw
        
        data = request.json
        topic = data.get('topic')
        if not topic:
            return jsonify({'error': 'Topic is required'}), 400

        # Get the gateway token from config (you can also put this in .env)
        gateway_token = os.getenv('OPENCLAW_GATEWAY_TOKEN', '45f4aa260648382416916c336bec303480c6399348f0247c')
        
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
        
        # Use WebSocket to communicate with OpenClaw Gateway
        print(f"Sending request to OpenClaw Gateway via WebSocket...")
        result = ask_openclaw(
            message=prompt,
            session_id="research_session",
            gateway_url="ws://localhost:18789",
            token=gateway_token
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
