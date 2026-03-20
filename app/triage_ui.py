import json
import html as _html
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.triage_api import run_triage
from app.gmail_client import get_gmail_service
from app.gmail_actions import ensure_triage_labels, apply_triage_action, send_reply, create_draft
from app.inbox import recent_inbox
from app.db import get_conn, require_latest_batch_id, now_iso

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# ── Main UI ───────────────────────────────────────────────────────────────────

@router.get("/triage/ui", response_class=HTMLResponse)
def triage_ui(request: Request, max_results: int = 20):
    data = run_triage(max_results=max_results)
    return templates.TemplateResponse(
        "slate.html",
        {
            "request": request,
            "slate": data["slate"],
            "mode": data.get("mode", "mock"),
            "batch_id": data.get("batch_id"),
        },
    )


# ── Approve ───────────────────────────────────────────────────────────────────

@router.post("/triage/approve", response_class=HTMLResponse)
async def triage_approve(request: Request):
    form = await request.form()
    ids = form.getlist("approve_ids")
    batch_id = form.get("batch_id")

    if not batch_id:
        return HTMLResponse(
            "<h3>Error: missing batch_id. Reload /triage/ui to generate a new batch.</h3>",
            status_code=400,
        )

    with get_conn() as conn:
        for mid in ids:
            edited = form.get(f"draft_{mid}")
            category = (form.get(f"cat_{mid}") or "ARCHIVE").upper()
            conn.execute(
                """
                UPDATE triage_items
                SET approved=1, edited_draft_body=?, category=?
                WHERE batch_id=? AND message_id=?
                """,
                (edited, category, batch_id, mid),
            )

    return templates.TemplateResponse(
        "approved.html",
        {
            "request": request,
            "count": len(ids),
            "batch_id": batch_id,
        },
    )


# ── Approvals view ────────────────────────────────────────────────────────────

@router.get("/triage/approvals", response_class=HTMLResponse)
def view_approvals(request: Request, batch_id: str | None = None):
    with get_conn() as conn:
        if not batch_id:
            batch_id = require_latest_batch_id(conn)
        rows = conn.execute(
            """
            SELECT message_id, approved, edited_draft_body, category, subject, sender
            FROM triage_items
            WHERE batch_id=? AND approved=1
            ORDER BY id DESC
            """,
            (batch_id,),
        ).fetchall()

    approvals = {
        r["message_id"]: {
            "approved": bool(r["approved"]),
            "edited_draft_body": r["edited_draft_body"],
            "category": r["category"],
            "subject": r["subject"] or "(No subject)",
            "sender": r["sender"] or "",
        }
        for r in rows
    }
    return templates.TemplateResponse(
        "approvals.html",
        {"request": request, "batch_id": batch_id, "approvals": approvals},
    )


# ── Apply to Gmail ────────────────────────────────────────────────────────────

@router.post("/triage/apply", response_class=HTMLResponse)
async def apply_approved_actions(request: Request):
    form = await request.form()
    batch_id = form.get("batch_id")

    service = get_gmail_service()
    label_ids_by_name = ensure_triage_labels(service)

    applied, skipped, errors = [], [], []

    with get_conn() as conn:
        if not batch_id:
            batch_id = require_latest_batch_id(conn)

        rows = conn.execute(
            """
            SELECT message_id, category, edited_draft_body
            FROM triage_items
            WHERE batch_id=? AND approved=1 AND applied=0
            """,
            (batch_id,),
        ).fetchall()

        for r in rows:
            msg_id = r["message_id"]
            category = (r["category"] or "ARCHIVE").upper()
            try:
                apply_triage_action(
                    service=service,
                    message_id=msg_id,
                    category=category,
                    label_ids_by_name=label_ids_by_name,
                    archive=True,
                )
                conn.execute(
                    "UPDATE triage_items SET applied=1, applied_at=? WHERE batch_id=? AND message_id=?",
                    (now_iso(), batch_id, msg_id),
                )
                label_name = {"ARCHIVE": "Triage/Done", "READ_LATER": "Triage/ReadLater"}.get(
                    category, "Triage/Now"
                )
                conn.execute(
                    """
                    INSERT INTO apply_log (batch_id, message_id, category, labels_added_json, removed_inbox, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        batch_id, msg_id, category,
                        json.dumps([label_name]),
                        1 if category in ("ARCHIVE", "READ_LATER") else 0,
                        now_iso(),
                    ),
                )
                applied.append({"message_id": msg_id, "category": category})
            except Exception as e:
                errors.append({"message_id": msg_id, "error": str(e)})

        if not rows:
            skipped.append({"batch_id": batch_id, "reason": "no_approved_unapplied_items"})

    return templates.TemplateResponse(
        "applied.html",
        {
            "request": request,
            "batch_id": batch_id,
            "applied": applied,
            "skipped": skipped,
            "errors": errors,
        },
    )


# ── Inbox Summary (HTMX fragment) ─────────────────────────────────────────────

@router.get("/triage/summary", response_class=HTMLResponse)
def get_summary(max_results: int = 20):
    try:
        inbox = recent_inbox(max_results=max_results)
        emails = [
            {
                "from": it.get("from") or "",
                "subject": it.get("subject") or "",
                "snippet": it.get("snippet") or "",
                "date": it.get("date") or "",
            }
            for it in inbox["items"]
        ]

        from app.llm import summarize_inbox
        summary = summarize_inbox(emails)

        headline = _html.escape(summary.get("headline", ""))
        actions_html = "".join(
            f'<li>{_html.escape(a)}</li>' for a in summary.get("key_actions", [])
        )
        fyi_items = summary.get("fyi", [])
        fyi_html = (
            f'<div><p class="summary-section-title">FYI</p>'
            f'<ul class="summary-list">{"".join(f"<li>{_html.escape(f)}</li>" for f in fyi_items)}</ul></div>'
            if fyi_items else ""
        )
        total = summary.get("total", len(emails))

        return HTMLResponse(f"""
        <div class="summary-panel">
          <button class="summary-close"
            onclick="document.getElementById('summary-target').innerHTML=''">×</button>
          <p class="summary-headline">{headline}</p>
          <div class="summary-cols">
            <div>
              <p class="summary-section-title">Needs Action</p>
              <ul class="summary-list">{actions_html}</ul>
            </div>
            {fyi_html}
          </div>
          <p class="summary-footer">{total} emails reviewed</p>
        </div>
        """)
    except Exception as e:
        return HTMLResponse(
            f'<div class="summary-panel summary-panel--error">Could not generate summary: {_html.escape(str(e))}</div>'
        )


# ── Send Now (HTMX fragment) ──────────────────────────────────────────────────

@router.post("/triage/send-now", response_class=HTMLResponse)
async def send_now(request: Request):
    form = await request.form()
    message_id = form.get("message_id", "")
    batch_id = form.get("batch_id", "")
    body = form.get(f"draft_{message_id}", "").strip()

    if not body:
        return HTMLResponse('<span class="status status--error">Draft body is empty</span>')

    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT sender, subject, thread_id FROM triage_items WHERE batch_id=? AND message_id=?",
                (batch_id, message_id),
            ).fetchone()

        if not row:
            return HTMLResponse('<span class="status status--error">Email not found in DB</span>')

        subject = row["subject"]
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        service = get_gmail_service()
        send_reply(service, to=row["sender"], subject=subject, body=body, thread_id=row["thread_id"])
        return HTMLResponse('<span class="status status--success">✓ Sent</span>')
    except Exception as e:
        return HTMLResponse(f'<span class="status status--error">Error: {_html.escape(str(e))}</span>')


# ── Save as Draft (HTMX fragment) ─────────────────────────────────────────────

@router.post("/triage/save-draft", response_class=HTMLResponse)
async def save_as_draft(request: Request):
    form = await request.form()
    message_id = form.get("message_id", "")
    batch_id = form.get("batch_id", "")
    body = form.get(f"draft_{message_id}", "").strip()

    if not body:
        return HTMLResponse('<span class="status status--error">Draft body is empty</span>')

    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT sender, subject, thread_id FROM triage_items WHERE batch_id=? AND message_id=?",
                (batch_id, message_id),
            ).fetchone()

        if not row:
            return HTMLResponse('<span class="status status--error">Email not found in DB</span>')

        subject = row["subject"]
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        service = get_gmail_service()
        create_draft(service, to=row["sender"], subject=subject, body=body, thread_id=row["thread_id"])
        return HTMLResponse('<span class="status status--success">✓ Saved to Drafts</span>')
    except Exception as e:
        return HTMLResponse(f'<span class="status status--error">Error: {_html.escape(str(e))}</span>')


# ── Schedule Send (HTMX fragment) ─────────────────────────────────────────────

@router.post("/triage/schedule-send", response_class=HTMLResponse)
async def schedule_send(request: Request):
    form = await request.form()
    message_id = form.get("message_id", "")
    batch_id = form.get("batch_id", "")
    send_at = form.get("send_at", "").strip()
    body = form.get(f"draft_{message_id}", "").strip()

    if not send_at:
        return HTMLResponse('<span class="status status--error">Please select a send time</span>')
    if not body:
        return HTMLResponse('<span class="status status--error">Draft body is empty</span>')

    try:
        dt = datetime.fromisoformat(send_at)
        send_at_iso = dt.isoformat()
    except ValueError:
        return HTMLResponse('<span class="status status--error">Invalid date/time format</span>')

    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT sender, subject, thread_id FROM triage_items WHERE batch_id=? AND message_id=?",
                (batch_id, message_id),
            ).fetchone()

            if not row:
                return HTMLResponse('<span class="status status--error">Email not found in DB</span>')

            subject = row["subject"]
            if not subject.lower().startswith("re:"):
                subject = f"Re: {subject}"

            conn.execute(
                """
                INSERT INTO scheduled_sends
                    (batch_id, message_id, to_addr, subject, body, thread_id, send_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (batch_id, message_id, row["sender"], subject, body, row["thread_id"],
                 send_at_iso, now_iso()),
            )

        formatted = dt.strftime("%b %d at %I:%M %p")
        return HTMLResponse(f'<span class="status status--success">✓ Scheduled for {_html.escape(formatted)}</span>')
    except Exception as e:
        return HTMLResponse(f'<span class="status status--error">Error: {_html.escape(str(e))}</span>')
