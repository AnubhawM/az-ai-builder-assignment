from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
from openai import OpenAI
import os
from dotenv import load_dotenv
from auth import requires_auth, AuthError
from database.config import SessionLocal
from crud import create_user, get_user_by_auth0_id
import requests  # Add this import

# Load environment variables from .env file
load_dotenv()

client = OpenAI()

# Initialize Flask app
app = Flask(__name__)

# Configure CORS for specific frontend URL
CORS(app, 
    # origins="",
    origins="http://localhost:5173",
    allow_headers=["Content-Type", "Authorization"],
    methods=["GET", "POST", "OPTIONS"])

# Add CORS headers to all responses
@app.after_request
def add_cors_headers(response):
    # response.headers['Access-Control-Allow-Origin'] = ""
    response.headers['Access-Control-Allow-Origin'] = "http://localhost:5173"
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    return response

@app.route('/')
def health_check():
    return "OK", 200

# Handle preflight OPTIONS requests explicitly
@app.route('/generate', methods=['OPTIONS'])
def handle_options():
    response = make_response()
    # response.headers['Access-Control-Allow-Origin'] = ""
    response.headers['Access-Control-Allow-Origin'] = "http://localhost:5173"
    response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    return response

# Add registration endpoint
@app.route('/register', methods=['POST'])
@requires_auth
def register_user(payload):
    db = SessionLocal()
    try:
        # Get the Authorization header
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({'error': 'Authorization header is required'}), 401

        # Call the /userinfo endpoint to get user information
        userinfo_response = requests.get(
            f"https://{os.getenv('AUTH0_DOMAIN')}/userinfo",
            headers={'Authorization': auth_header}
        )
        
        if userinfo_response.status_code != 200:
            return jsonify({'error': 'Failed to get user info from Auth0'}), 500
            
        user_info = userinfo_response.json()

        # Check if user already exists
        existing_user = get_user_by_auth0_id(db, payload['sub'])
        if existing_user:
            return jsonify({'message': 'User already registered'}), 200

        # Create new user with email from user_info
        user_data = {
            'auth0_id': payload['sub'],
            'email': user_info.get('email'),
            'name': user_info.get('name', '')
        }
        
        if not user_data['email']:
            return jsonify({'error': 'Email not found in user info'}), 400
            
        new_user = create_user(db, user_data)
        
        return jsonify({
            'message': 'User registered successfully',
            'user': {
                'id': new_user.id,
                'auth0_id': new_user.auth0_id,
                'email': new_user.email,
                'name': new_user.name
            }
        }), 201

    except Exception as e:
        print(f"Error registering user: {e}")
        return jsonify({'error': 'Failed to register user'}), 500
    finally:
        db.close()

# Main route to generate a response from OpenAI API
@app.route('/generate', methods=['POST'])
@requires_auth  # Add auth decorator
def generate(payload):  # Add payload parameter
    try:
        # Parse incoming JSON data
        data = request.json

        if not data or not data.get('prompt'):
            return jsonify({'error': 'Prompt is required'}), 400

        # Call OpenAI API
        model = "gpt-4o-mini"
        response = client.chat.completions.create(
            model=model,  # Use a valid model for chat completions
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": data['prompt']}
            ],
            max_tokens=500,
            temperature=0.7,
        )

        # Extract and return the generated response
        response = response.choices[0].message.content.strip()

        return jsonify({'response': response}), 200

    except Exception as e:
        print(f"Error generating response: {e}")
        return jsonify({'error': 'Failed to generate response'}), 500

# Add Auth0 error handler
@app.errorhandler(AuthError)
def handle_auth_error(ex):
    response = jsonify(ex.error)
    response.status_code = ex.status_code
    return response

if __name__ == '__main__':
    # Run Flask app on localhost (Codespaces will handle port forwarding)
    # app.run(host='127.0.0.1', port=5000, debug=True)
    app.run(host='0.0.0.0', port=5000, debug=True)
