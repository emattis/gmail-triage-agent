from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.oauth import router as oauth_router
from app.gmail import router as gmail_router
from app.inbox import router as inbox_router
from app.triage_api import router as triage_router
from app.triage_ui import router as triage_ui_router
from app.db import init_db
from app.scheduler import start_scheduler, shutdown_scheduler


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


@app.get("/", response_class=HTMLResponse)
def home():
    return """
    <!doctype html><html><head><meta charset="utf-8">
    <style>
      body { font-family: system-ui, sans-serif; display: flex; flex-direction: column;
             align-items: center; justify-content: center; min-height: 100vh;
             background: #F8FAFC; margin: 0; color: #0F172A; }
      h1 { font-size: 22px; font-weight: 600; margin-bottom: 8px; }
      p { color: #64748B; font-size: 14px; margin-bottom: 24px; }
      .links { display: flex; gap: 12px; }
      a { padding: 9px 18px; border-radius: 8px; font-size: 14px; font-weight: 500;
          text-decoration: none; border: 1px solid #E2E8F0; background: #fff; color: #0F172A; }
      a.primary { background: #0F172A; color: #fff; border-color: #0F172A; }
    </style></head>
    <body>
      <h1>Gmail Triage Agent</h1>
      <p>AI-powered inbox management</p>
      <div class="links">
        <a href="/auth/google/start">Connect Gmail</a>
        <a href="/triage/ui" class="primary">Open Triage ↗</a>
      </div>
    </body></html>
    """
