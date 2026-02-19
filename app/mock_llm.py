from typing import Any, Dict, List

def triage_with_mock(emails: List[dict]) -> Dict[str, Any]:
    items = []
    for e in emails:
        subj = (e.get("subject") or "").lower()
        frm = (e.get("from") or "").lower()
        has_unsub = bool(e.get("has_list_unsubscribe"))

        if has_unsub or "unsubscribe" in subj or "newsletter" in subj:
            cat = "READ_LATER"
            reason = "Newsletter/marketing signal."
        elif any(x in frm for x in ["no-reply", "noreply", "do-not-reply", "notifications@"]):
            cat = "ARCHIVE"
            reason = "Automated notification sender."
        elif any(x in subj for x in ["intro", "introduction", "meeting", "quick chat", "availability"]):
            cat = "REPLY"
            reason = "Likely expects a response (intro/scheduling keywords)."
        else:
            cat = "ARCHIVE"
            reason = "Default: no clear action requested."

        items.append({
            "message_id": e["message_id"],
            "thread_id": e["thread_id"],
            "from": e.get("from", ""),
            "subject": e.get("subject", ""),
            "date": e.get("date", ""),
            "category": cat,
            "confidence": 0.6,
            "reason": reason,
            "suggested_labels": [f"Triage/{'ReadLater' if cat=='READ_LATER' else 'Now' if cat in ('REPLY','TASK','DELEGATE') else 'Done'}"],
            "draft_reply": None,
            "task_suggestion": None,
            "questions_for_user": []
        })

    return {"batch_summary": f"Mock triage (no model): processed {len(items)} emails.", "items": items}
