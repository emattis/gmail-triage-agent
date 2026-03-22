from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.oauth import router as oauth_router
from app.gmail import router as gmail_router
from app.inbox import router as inbox_router
from app.triage_api import router as triage_router
from app.triage_ui import router as triage_ui_router
from app.auto_archive import router as auto_archive_router
from app.analytics import router as analytics_router
from app.db import init_db
from app.scheduler import start_scheduler, shutdown_scheduler

templates = Jinja2Templates(directory="app/templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    start_scheduler()
    yield
    shutdown_scheduler()


app = FastAPI(title="Gmail Triage Agent", lifespan=lifespan)

app.include_router(oauth_router)
app.include_router(gmail_router)
app.include_router(inbox_router)
app.include_router(triage_router)
app.include_router(triage_ui_router)
app.include_router(auto_archive_router)
app.include_router(analytics_router)


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    token_path = Path("data/token.json")
    connected = token_path.exists() and token_path.stat().st_size > 0
    return templates.TemplateResponse(
        "landing.html", {"request": request, "connected": connected}
    )
