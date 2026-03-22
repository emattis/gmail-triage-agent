import base64
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

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

def _get_header(headers: List[Dict[str, str]], name: str) -> Optional[str]:
    name_l = name.lower()
    for h in headers:
        if h.get("name", "").lower() == name_l:
            return h.get("value")
    return None

def _decode_body(payload: Dict[str, Any]) -> str:
    # Try the payload body first
    body = payload.get("body", {}).get("data")
    if body:
        return base64.urlsafe_b64decode(body.encode("utf-8")).decode("utf-8", errors="replace")

    # Otherwise walk parts
    parts = payload.get("parts", [])
    stack = parts[:]
    while stack:
        part = stack.pop(0)
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data and mime in ("text/plain", "text/html"):
            return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="replace")
        stack.extend(part.get("parts", []))
    return ""

@router.get("/gmail/inbox/recent")
def recent_inbox(max_results: int = 20):
    """
    Read-only: returns basic info for recent INBOX emails.
    """
    creds = _load_creds()
    service = build("gmail", "v1", credentials=creds)

    # Tunable query: start simple and safe
    query = "in:inbox -in:spam -in:trash"

    res = service.users().messages().list(
        userId="me",
        q=query,
        maxResults=max_results,
    ).execute()

    messages = res.get("messages", [])
    out = []

    for m in messages:
        msg = service.users().messages().get(
            userId="me",
            id=m["id"],
            format="full",
        ).execute()

        payload = msg.get("payload", {})
        headers = payload.get("headers", [])
        out.append({
            "id": msg.get("id"),
            "threadId": msg.get("threadId"),
            "internalDate": msg.get("internalDate"),
            "from": _get_header(headers, "From"),
            "to": _get_header(headers, "To"),
            "subject": _get_header(headers, "Subject"),
            "date": _get_header(headers, "Date"),
            "snippet": msg.get("snippet"),
            "has_list_unsubscribe": _get_header(headers, "List-Unsubscribe") is not None,
            "body_preview": _decode_body(payload)[:1000],  # keep it short
        })

    return {"query": query, "count": len(out), "items": out}
