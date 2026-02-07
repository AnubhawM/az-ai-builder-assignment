from functools import wraps
from flask import request, jsonify
from jose import jwt
import json
import requests
import os
from dotenv import load_dotenv

load_dotenv()

AUTH0_DOMAIN = os.getenv('AUTH0_DOMAIN')
AUTH0_AUDIENCE = os.getenv('AUTH0_AUDIENCE')
ALGORITHMS = ['RS256']

class AuthError(Exception):
    def __init__(self, error, status_code):
        self.error = error
        self.status_code = status_code

def get_token_auth_header():
    auth = request.headers.get('Authorization', None)
    if not auth:
        raise AuthError({"code": "authorization_header_missing",
                        "description": "Authorization header is expected."}, 401)

    parts = auth.split()
    if parts[0].lower() != 'bearer':
        raise AuthError({"code": "invalid_header",
                        "description": "Authorization header must start with Bearer."}, 401)
    elif len(parts) == 1:
        raise AuthError({"code": "invalid_header",
                        "description": "Token not found."}, 401)
    elif len(parts) > 2:
        raise AuthError({"code": "invalid_header",
                        "description": "Authorization header must be Bearer token."}, 401)

    token = parts[1]
    return token

def verify_jwt(token):
    jsonurl = requests.get(f'https://{AUTH0_DOMAIN}/.well-known/jwks.json')
    jwks = jsonurl.json()
    unverified_header = jwt.get_unverified_header(token)
    
    rsa_key = {}
    for key in jwks['keys']:
        if key['kid'] == unverified_header['kid']:
            rsa_key = {
                'kty': key['kty'],
                'kid': key['kid'],
                'use': key['use'],
                'n': key['n'],
                'e': key['e']
            }
    
    if rsa_key:
        try:
            payload = jwt.decode(
                token,
                rsa_key,
                algorithms=ALGORITHMS,
                audience=AUTH0_AUDIENCE,
                issuer=f'https://{AUTH0_DOMAIN}/'
            )
            return payload
            
        except jwt.ExpiredSignatureError:
            raise AuthError({"code": "token_expired",
                           "description": "Token is expired."}, 401)
        except jwt.JWTClaimsError:
            raise AuthError({"code": "invalid_claims",
                           "description": "Incorrect claims."}, 401)
        except Exception:
            raise AuthError({"code": "invalid_header",
                           "description": "Unable to parse authentication token."}, 401)

    raise AuthError({"code": "invalid_header",
                    "description": "Unable to find appropriate key."}, 401)

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = get_token_auth_header()
        payload = verify_jwt(token)
        return f(payload, *args, **kwargs)
    return decorated
