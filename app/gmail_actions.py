from __future__ import annotations

from typing import Dict, List
from googleapiclient.discovery import Resource

TRIAGE_LABELS = {
    "ARCHIVE": "Triage/Done",
    "READ_LATER": "Triage/ReadLater",
    "REPLY": "Triage/Now",
    "TASK": "Triage/Now",
    "RESPOND": "Triage/Now",
    "DELEGATE": "Triage/Now",
}

def _list_labels(service: Resource) -> Dict[str, str]:
    resp = service.users().labels().list(userId="me").execute()
    out: Dict[str, str] = {}
    for lab in resp.get("labels", []):
        out[lab["name"]] = lab["id"]
    return out

def get_or_create_label(service: Resource, name: str) -> str:
    labels = _list_labels(service)
    if name in labels:
        return labels[name]
    body = {
        "name": name,
        "labelListVisibility": "labelShow",
        "messageListVisibility": "show",
        "type": "user",
    }
    created = service.users().labels().create(userId="me", body=body).execute()
    return created["id"]

def ensure_triage_labels(service: Resource) -> Dict[str, str]:
    label_ids: Dict[str, str] = {}
    for name in set(TRIAGE_LABELS.values()):
        label_ids[name] = get_or_create_label(service, name)
    return label_ids

def apply_triage_action(
    service: Resource,
    message_id: str,
    category: str,
    label_ids_by_name: Dict[str, str],
    archive: bool = True,
) -> dict:
    category = (category or "").upper()
    label_name = TRIAGE_LABELS.get(category, "Triage/Now")
    add_label_id = label_ids_by_name[label_name]

    add_label_ids: List[str] = [add_label_id]
    remove_label_ids: List[str] = []

    # Archive only for ARCHIVE/READ_LATER
    if archive and category in ("ARCHIVE", "READ_LATER"):
        remove_label_ids.append("INBOX")  # system label id is literally "INBOX"

    body = {"addLabelIds": add_label_ids, "removeLabelIds": remove_label_ids}
    return service.users().messages().modify(userId="me", id=message_id, body=body).execute()

