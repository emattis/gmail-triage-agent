from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.triage_api import run_triage
from app.gmail_client import get_gmail_service
from app.gmail_actions import ensure_triage_labels, apply_triage_action
from app.triage_store import APPROVALS

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/triage/ui", response_class=HTMLResponse)
def triage_ui(request: Request, max_results: int = 20):
    data = run_triage(max_results=max_results)
    return templates.TemplateResponse(
        "slate.html",
        {"request": request, "slate": data["slate"], "mode": data.get("mode", "llm")},
    )

@router.post("/triage/approve", response_class=HTMLResponse)
async def triage_approve(request: Request):
    form = await request.form()
    ids = form.getlist("approve_ids")
    for mid in ids:
        edited = form.get(f"draft_{mid}")
        category = form.get(f"cat_{mid}")
        APPROVALS[mid] = {"approved": True, "edited_draft_body": edited, "category": category}
    return HTMLResponse(
        f"<h3>Saved {len(ids)} approvals.</h3>"
        f"<p><a href='/triage/ui'>Back to slate</a></p>"
        f"<p><a href='/triage/approvals'>View approvals</a></p>"
    )

@router.get("/triage/approvals")
def view_approvals():
    return APPROVALS

@router.post("/triage/apply")
async def apply_approved_actions():
    service = get_gmail_service()     # your existing helper
    approvals = APPROVALS

    label_ids_by_name = ensure_triage_labels(service)

    applied, skipped, errors = [], [], []

    for msg_id, info in approvals.items():
        if not info.get("approved"):
            skipped.append({"message_id": msg_id, "reason": "not_approved"})
            continue

        category = (info.get("category") or "READ_LATER").upper()

        try:
            # apply label + archive behavior (archives only for ARCHIVE/READ_LATER)
            apply_triage_action(
                service=service,
                message_id=msg_id,
                category=category,
                label_ids_by_name=label_ids_by_name,
                archive=True,
            )
            applied.append({"message_id": msg_id, "category": category})
        except Exception as e:
            errors.append({"message_id": msg_id, "error": str(e)})

    return {"applied": applied, "skipped": skipped, "errors": errors}
