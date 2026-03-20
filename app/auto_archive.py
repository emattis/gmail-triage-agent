from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

import html as _html
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.inbox import recent_inbox
from app.gmail_client import get_gmail_service
from app.gmail_actions import ensure_triage_labels, apply_triage_action
from app.db import get_conn, now_iso

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

RULES_PATH = Path(os.getenv("RULES_PATH", "data/auto_archive_rules.json"))

DEFAULT_RULES: dict[str, list[str]] = {
    "sender_domains": [
        "gap.com", "hm.com", "zara.com", "forever21.com", "oldnavy.com",
        "bananarepublic.com", "uniqlo.com", "macys.com", "nordstrom.com",
        "target.com", "kohls.com", "jcrew.com", "abercrombie.com",
        "ae.com", "urbanoutfitters.com", "anthropologie.com",
        "amazon.com", "ebay.com", "etsy.com", "wish.com",
        "shopify.com", "squarespace.com", "mailchimp.com",
    ],
    "sender_keywords": [
        "no-reply", "noreply", "do-not-reply", "donotreply",
        "newsletter", "notifications@", "updates@", "alerts@",
        "marketing@", "promotions@", "deals@", "offers@",
        "info@", "hello@", "team@",
    ],
    "subject_keywords": [
        "% off", "sale", "deal", "offer", "discount", "promo", "coupon",
        "free shipping", "limited time", "act now", "exclusive",
        "just for you", "shop now", "buy now", "don't miss",
        "weekly digest", "monthly digest", "newsletter",
        "unsubscribe", "order confirmation", "your receipt",
        "your order has shipped", "delivery update",
    ],
    "whitelist": [],
}


def load_rules() -> dict[str, list[str]]:
    if RULES_PATH.exists():
        try:
            return json.loads(RULES_PATH.read_text())
        except Exception:
            pass
    return {k: list(v) for k, v in DEFAULT_RULES.items()}


def save_rules(rules: dict[str, list[str]]) -> None:
    RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
    RULES_PATH.write_text(json.dumps(rules, indent=2))


def _matches(email: dict[str, Any], rules: dict[str, list[str]]) -> str | None:
    """Returns the matched rule string, or None if no match."""
    sender = (email.get("from") or "").lower()
    subject = (email.get("subject") or "").lower()

    # Whitelist takes priority
    for w in rules.get("whitelist", []):
        if w.lower() in sender:
            return None

    for domain in rules.get("sender_domains", []):
        if domain.lower() in sender:
            return f"Sender domain: {domain}"

    for kw in rules.get("sender_keywords", []):
        if kw.lower() in sender:
            return f"Sender keyword: {kw}"

    for kw in rules.get("subject_keywords", []):
        if kw.lower() in subject:
            return f"Subject keyword: {kw}"

    return None


# ── Rules editor ──────────────────────────────────────────────────────────────

@router.get("/auto-archive", response_class=HTMLResponse)
def auto_archive_page(request: Request):
    rules = load_rules()
    return templates.TemplateResponse(
        "auto_archive.html", {"request": request, "rules": rules}
    )


@router.post("/auto-archive/save-rules", response_class=RedirectResponse)
async def save_rules_endpoint(request: Request):
    form = await request.form()

    def _parse(raw: str) -> list[str]:
        return [line.strip() for line in raw.splitlines() if line.strip()]

    rules = {
        "sender_domains": _parse(form.get("sender_domains", "")),
        "sender_keywords": _parse(form.get("sender_keywords", "")),
        "subject_keywords": _parse(form.get("subject_keywords", "")),
        "whitelist": _parse(form.get("whitelist", "")),
    }
    save_rules(rules)
    return RedirectResponse("/auto-archive", status_code=303)


# ── Scan ─────────────────────────────────────────────────────────────────────

@router.get("/auto-archive/scan", response_class=HTMLResponse)
def scan_inbox(request: Request, max_results: int = 50):
    rules = load_rules()
    inbox = recent_inbox(max_results=max_results)

    matched = []
    for item in inbox["items"]:
        reason = _matches(item, rules)
        if reason:
            matched.append({
                "message_id": item["id"],
                "thread_id": item["threadId"],
                "sender": item.get("from") or "",
                "subject": item.get("subject") or "(No subject)",
                "date": item.get("date") or "",
                "snippet": item.get("snippet") or "",
                "match_reason": reason,
            })

    # Persist as a batch so we can apply later
    batch_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO batches (batch_id, created_at, mode, max_results) VALUES (?, ?, ?, ?)",
            (batch_id, now_iso(), "auto_archive", max_results),
        )
        for m in matched:
            conn.execute(
                """
                INSERT OR IGNORE INTO triage_items
                    (batch_id, message_id, thread_id, sender, subject, date, snippet,
                     category, confidence, reason, approved, applied)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'ARCHIVE', 1.0, ?, 0, 0)
                """,
                (
                    batch_id, m["message_id"], m["thread_id"],
                    m["sender"], m["subject"], m["date"], m["snippet"],
                    m["match_reason"],
                ),
            )

    return templates.TemplateResponse(
        "auto_archive_review.html",
        {"request": request, "batch_id": batch_id, "emails": matched},
    )


# ── Apply ────────────────────────────────────────────────────────────────────

@router.post("/auto-archive/apply", response_class=HTMLResponse)
async def apply_auto_archive(request: Request):
    form = await request.form()
    batch_id = form.get("batch_id", "")
    selected_ids = set(form.getlist("selected_ids"))

    if not selected_ids:
        return templates.TemplateResponse(
            "auto_archive_applied.html",
            {"request": request, "archived": 0, "skipped": 0, "errors": []},
        )

    service = get_gmail_service()
    label_ids_by_name = ensure_triage_labels(service)

    archived, skipped, errors = 0, 0, []

    with get_conn() as conn:
        rows = conn.execute(
            "SELECT message_id FROM triage_items WHERE batch_id=? AND applied=0",
            (batch_id,),
        ).fetchall()

        for row in rows:
            mid = row["message_id"]
            if mid not in selected_ids:
                skipped += 1
                continue
            try:
                apply_triage_action(
                    service=service,
                    message_id=mid,
                    category="ARCHIVE",
                    label_ids_by_name=label_ids_by_name,
                    archive=True,
                )
                conn.execute(
                    "UPDATE triage_items SET applied=1, approved=1, applied_at=? WHERE batch_id=? AND message_id=?",
                    (now_iso(), batch_id, mid),
                )
                archived += 1
            except Exception as e:
                errors.append({"message_id": mid, "error": str(e)})

    return templates.TemplateResponse(
        "auto_archive_applied.html",
        {"request": request, "archived": archived, "skipped": skipped, "errors": errors},
    )
