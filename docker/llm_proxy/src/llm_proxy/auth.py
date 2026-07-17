import base64
import json

from fastapi import HTTPException, Request


def decode_credentials(authorization: str) -> dict:
    prefix = "Bearer "
    if not authorization.lower().startswith(prefix.lower()):
        raise HTTPException(status_code=401, detail="Invalid credentials format")

    token = authorization[len(prefix):]
    try:
        decoded = base64.b64decode(token)
        return json.loads(decoded)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid credentials format")


def extract_authorization(request: Request) -> str:
    auth = request.headers.get("Authorization")
    if not auth:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    return auth
