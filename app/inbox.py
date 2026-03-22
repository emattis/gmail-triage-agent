import base64
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

router = APIRouter()

MAX_WORKERS = 15  # concurrent Gmail API fetches


def _token_path() -> Path:
    return Path(os.getenv("TOKEN_STORE_PATH", "data/token.json"))


def _load_creds() -> Credentials:
    if not _token_path().exists():
        raise HTTPException(status_code=401, detail="Not connected. Go to /auth/google/start")
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
    body = payload.get("body", {}).get("data")
    if body:
        return base64.urlsafe_b64decode(body.encode()).decode("utf-8", errors="replace")
    stack = list(payload.get("parts", []))
    while stack:
        part = stack.pop(0)
        data = part.get("body", {}).get("data")
        if data and part.get("mimeType", "") in ("text/plain", "text/html"):
            return base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors="replace")
        stack.extend(part.get("parts", []))
    return ""


def _fetch_one(service, msg_id: str) -> Dict[str, Any]:
    return service.users().messages().get(
        userId="me",
        id=msg_id,
        format="full",
    ).execute()


def _parse_message(msg: Dict[str, Any]) -> Dict[str, Any]:
    payload = msg.get("payload", {})
    headers = payload.get("headers", [])
    return {
        "id": msg.get("id"),
        "threadId": msg.get("threadId"),
        "internalDate": msg.get("internalDate"),
        "from": _get_header(headers, "From"),
        "to": _get_header(headers, "To"),
        "subject": _get_header(headers, "Subject"),
        "date": _get_header(headers, "Date"),
        "snippet": msg.get("snippet"),
        "has_list_unsubscribe": _get_header(headers, "List-Unsubscribe") is not None,
        "body_preview": _decode_body(payload)[:1000],
    }


@router.get("/gmail/inbox/recent")
def recent_inbox(max_results: int = 20):
    creds = _load_creds()
    service = build("gmail", "v1", credentials=creds)

    query = "in:inbox -in:spam -in:trash"
    res = service.users().messages().list(
        userId="me", q=query, maxResults=max_results
    ).execute()

    messages = res.get("messages", [])
    if not messages:
        return {"query": query, "count": 0, "items": []}

    # Fetch all messages concurrently
    workers = min(len(messages), MAX_WORKERS)
    fetched: Dict[str, Any] = {}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_id = {
            pool.submit(_fetch_one, service, m["id"]): m["id"]
            for m in messages
        }
        for future in as_completed(future_to_id):
            msg_id = future_to_id[future]
            try:
                fetched[msg_id] = future.result()
            except (HttpError, Exception):
                pass  # skip failed fetches silently

    # Preserve original order from the list response
    out = [
        _parse_message(fetched[m["id"]])
        for m in messages
        if m["id"] in fetched
    ]

    return {"query": query, "count": len(out), "items": out}
