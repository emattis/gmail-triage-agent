from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.oauth import router as oauth_router
from app.gmail import router as gmail_router
from app.inbox import router as inbox_router
from app.triage_api import router as triage_router

from google import genai

import os



app = FastAPI(title="Gmail Triage Agent (Local)")

app.include_router(oauth_router)
app.include_router(gmail_router)
app.include_router(inbox_router)
app.include_router(triage_router)


@app.get("/gemini/models")
def list_models():
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    return [m.name for m in client.models.list()]

@app.get("/", response_class=HTMLResponse)
def home():
    return """
    <h2>Gmail Triage Agent (Local)</h2>
    <p><a href="/auth/google/start">Connect Gmail</a></p>
    <p><a href="/gmail/profile">Test: Gmail Profile</a> (after connecting)</p>
    """
