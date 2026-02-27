import os
import json
import uuid
from fastapi import APIRouter

from app.inbox import recent_inbox
from app.mock_llm import triage_with_mock
from app.db import get_conn, now_iso 
router = APIRouter()


def _mode() -> str:
    return os.getenv("TRIAGE_MODE", "mock").lower()


def _normalize_slate(slate):
    """
    Ensure the slate is always a dict of the form:
      {"items": [ ... ]}
    so templates can always do: slate["items"].
    """
    if isinstance(slate, dict) and "items" in slate and isinstance(slate["items"], list):
        return {"items": slate["items"]}
    if isinstance(slate, list):
        return {"items": slate}
    return {"items": []}


@router.get("/triage/run")
def run_triage(max_results: int = 20):
    inbox = recent_inbox(max_results=max_results)

    emails = [{
        "message_id": it["id"],
        "thread_id": it["threadId"],
        "from": it.get("from") or "",
        "subject": it.get("subject") or "",
        "date": it.get("date") or "",
        "snippet": it.get("snippet") or "",
        "has_list_unsubscribe": it.get("has_list_unsubscribe", False),
        "body_preview": it.get("body_preview") or "",
    } for it in inbox["items"]]

    mode = "llm" if _mode() == "llm" else "mock"
    if mode == "llm":
        from app.llm import triage_with_llm
        raw_slate = triage_with_llm(emails)
    else:
        raw_slate = triage_with_mock(emails)

    slate = _normalize_slate(raw_slate)

    # ---- persist batch + items ----
    batch_id = str(uuid.uuid4())
    created_at = now_iso()

    with get_conn() as conn:
        conn.execute(
            "INSERT INTO batches (batch_id, created_at, mode, max_results) VALUES (?, ?, ?, ?)",
            (batch_id, created_at, mode, max_results)
        )

        for item in slate["items"]:
            msg_id = item.get("message_id") or item.get("id")
            if not msg_id:
                continue

            suggested_labels = item.get("suggested_labels")
            suggested_labels_json = json.dumps(suggested_labels) if suggested_labels is not None else None

            conn.execute(
                """
                INSERT OR IGNORE INTO triage_items (
                    batch_id, message_id, thread_id, sender, subject, date, snippet,
                    category, confidence, reason, suggested_labels_json, draft_reply,
                    approved, edited_draft_body, applied, applied_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, 0, NULL)
                """,
                (
                    batch_id,
                    msg_id,
                    item.get("thread_id"),
                    item.get("from") or item.get("sender") or "",
                    item.get("subject") or "",
                    item.get("date") or "",
                    item.get("snippet") or "",
                    (item.get("category") or "").upper(),
                    float(item.get("confidence")) if item.get("confidence") is not None else None,
                    item.get("reason"),
                    suggested_labels_json,
                    item.get("draft_reply"),
                )
            )

    return {"source_query": inbox.get("query"), "slate": slate, "mode": mode, "batch_id": batch_id}