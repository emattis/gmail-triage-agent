import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

router = APIRouter()

def _token_path() -> Path:
    p = os.getenv("TOKEN_STORE_PATH", "data/token.json")
    return Path(p)

def _load_creds() -> Credentials:
    if not _token_path().exists():
        raise HTTPException(status_code=401, detail="Not connected yet. Go to /auth/google/start")
    data = json.loads(_token_path().read_text())
    return Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri"),
        client_id=data.get("client_id"),
        client_secret=data.get("client_secret"),
        scopes=data.get("scopes"),
    )

@router.get("/gmail/profile")
def gmail_profile():
    creds = _load_creds()
    service = build("gmail", "v1", credentials=creds)
    profile = service.users().getProfile(userId="me").execute()
    # returns your email + message/thread counts
    return profile
