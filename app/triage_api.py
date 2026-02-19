import os
from fastapi import APIRouter
from app.inbox import recent_inbox
from app.mock_llm import triage_with_mock

router = APIRouter()

def _mode() -> str:
    return os.getenv("TRIAGE_MODE", "mock").lower()

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

    if _mode() == "llm":
        # Try to import llm only if in llm mode
        from app.llm import triage_with_llm
        slate = triage_with_llm(emails)
        return {"source_query": inbox["query"], "slate": slate, "mode": "llm"}

    slate = triage_with_mock(emails)
    return {"source_query": inbox["query"], "slate": slate, "mode": "mock"}
