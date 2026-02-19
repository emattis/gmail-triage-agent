import json
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials

router = APIRouter()

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
]

def _env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing env var: {name}")
    return val

def _token_store_path() -> Path:
    return Path(_env("TOKEN_STORE_PATH"))

def _client_secrets_path() -> str:
    return _env("GOOGLE_OAUTH_CLIENT_SECRETS")

def _redirect_uri() -> str:
    return _env("OAUTH_REDIRECT_URI")

def _make_flow(state: Optional[str] = None) -> Flow:
    return Flow.from_client_secrets_file(
        _client_secrets_path(),
        scopes=SCOPES,
        redirect_uri=_redirect_uri(),
        state=state,
    )

@router.get("/auth/google/start")
def google_start():
    flow = _make_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",  # ensures refresh_token is returned on first connection
    )
    # Store state locally (simple local dev approach)
    Path("data").mkdir(parents=True, exist_ok=True)
    Path("data/oauth_state.txt").write_text(state)
    return RedirectResponse(auth_url)

@router.get("/auth/google/callback", response_class=HTMLResponse)
def google_callback(request: Request):
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code/state from Google callback")

    expected_state = Path("data/oauth_state.txt").read_text().strip()
    if state != expected_state:
        raise HTTPException(status_code=400, detail="OAuth state mismatch")

    flow = _make_flow(state=state)
    flow.fetch_token(code=code)

    creds: Credentials = flow.credentials
    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }

    _token_store_path().parent.mkdir(parents=True, exist_ok=True)
    _token_store_path().write_text(json.dumps(token_data, indent=2))

    return """
    <h3>✅ Connected Gmail</h3>
    <p>Token saved locally.</p>
    <p><a href="/gmail/profile">Test Gmail Profile</a></p>
    <p><a href="/">Back home</a></p>
    """
