from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.triage_api import run_triage

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

APPROVALS = {}

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
        APPROVALS[mid] = {"approved": True, "edited_draft_body": edited}
    return HTMLResponse(
        f"<h3>Saved {len(ids)} approvals.</h3>"
        f"<p><a href='/triage/ui'>Back to slate</a></p>"
        f"<p><a href='/triage/approvals'>View approvals</a></p>"
    )

@router.get("/triage/approvals")
def view_approvals():
    return APPROVALS
