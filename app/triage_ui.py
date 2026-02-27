import json
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.triage_api import run_triage
from app.gmail_client import get_gmail_service
from app.gmail_actions import ensure_triage_labels, apply_triage_action

from app.db import get_conn, require_latest_batch_id, now_iso  # <-- add

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/triage/ui", response_class=HTMLResponse)
def triage_ui(request: Request, max_results: int = 20):
    data = run_triage(max_results=max_results)
    # Pass batch_id into template so you can include it as a hidden field later
    return templates.TemplateResponse(
        "slate.html",
        {
            "request": request,
            "slate": data["slate"],
            "mode": data.get("mode", "llm"),
            "batch_id": data.get("batch_id"),
        },
    )


@router.post("/triage/approve", response_class=HTMLResponse)
async def triage_approve(request: Request):
    form = await request.form()
    ids = form.getlist("approve_ids")

    # Optional: if you add <input type="hidden" name="batch_id" value="{{ batch_id }}">
    batch_id = form.get("batch_id")

    with get_conn() as conn:
        if not batch_id:
            return HTMLResponse(
                "<h3>Error: missing batch_id. Reload /triage/ui to generate a new batch.</h3>",
                status_code=400,
            )

        updated = 0
        for mid in ids:
            edited = form.get(f"draft_{mid}")
            category = (form.get(f"cat_{mid}") or "READ_LATER").upper()

            conn.execute(
                """
                UPDATE triage_items
                SET approved=1, edited_draft_body=?, category=?
                WHERE batch_id=? AND message_id=?
                """,
                (edited, category, batch_id, mid),
            )
            updated += 1

    return HTMLResponse(
        f"<h3>Saved {updated} approvals (batch {batch_id}).</h3>"
        f"<p><a href='/triage/ui'>Back to slate</a></p>"
        f"<p><a href='/triage/approvals'>View approvals</a></p>"
    )


@router.get("/triage/approvals")
def view_approvals(batch_id: str | None = None):
    with get_conn() as conn:
        if not batch_id:
            batch_id = require_latest_batch_id(conn)

        rows = conn.execute(
            """
            SELECT message_id, approved, edited_draft_body, category
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
        }
        for r in rows
    }
    return {"batch_id": batch_id, "approvals": approvals}


@router.post("/triage/apply")
async def apply_approved_actions(batch_id: str | None = None):
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
            category = (r["category"] or "READ_LATER").upper()

            try:
                # Apply label + archive behavior (archives only for ARCHIVE/READ_LATER)
                apply_triage_action(
                    service=service,
                    message_id=msg_id,
                    category=category,
                    label_ids_by_name=label_ids_by_name,
                    archive=True,
                )

                # Mark applied
                conn.execute(
                    "UPDATE triage_items SET applied=1, applied_at=? WHERE batch_id=? AND message_id=?",
                    (now_iso(), batch_id, msg_id),
                )

                # Log for undo (minimal)
                label_name = {
                    "ARCHIVE": "Triage/Done",
                    "READ_LATER": "Triage/ReadLater",
                }.get(category, "Triage/Now")
                conn.execute(
                    """
                    INSERT INTO apply_log (batch_id, message_id, category, labels_added_json, removed_inbox, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        batch_id,
                        msg_id,
                        category,
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

    return {"batch_id": batch_id, "applied": applied, "skipped": skipped, "errors": errors}