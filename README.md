# Gmail Triage Agent

A personal Gmail triage assistant that uses AI to categorize your inbox, draft replies, auto-archive noise, and surface patterns in your email habits.

## Features

- **AI Triage** — Categorizes emails as `ARCHIVE`, `READ_LATER`, `REPLY`, `TASK`, or `DELEGATE` with confidence scores and reasoning
- **Draft Replies** — AI-suggested reply drafts with Send Now, Schedule Send, and Save as Gmail Draft options
- **Category Override** — Change any AI recommendation before approving
- **Auto-Archive** — Rule-based archiving for newsletters, notifications, and other noise with a review page before applying
- **Pattern Recognition** — After 10+ approvals, surfaces suggested auto-archive rules based on your behavior ("you always archive X domain")
- **Analytics** — Triaged email counts, category breakdown, accuracy rate, and estimated time saved
- **Weekly Scheduler** — Automatically runs triage every Saturday at 8AM UTC
- **Inbox Summary** — One-click AI summary of your inbox with key actions and FYI items

## Tech Stack

- **Backend** — FastAPI + Jinja2 templates
- **Frontend** — HTMX (no JS framework)
- **Database** — SQLite (WAL mode)
- **AI** — Gemini 2.0 Flash Lite (default), Claude Haiku, or mock mode (switchable via `TRIAGE_MODE`)
- **Scheduler** — APScheduler
- **Auth** — Google OAuth2

## Setup

### 1. Prerequisites

- Python 3.10+
- A Google Cloud project with the Gmail API enabled
- OAuth 2.0 credentials (Desktop app type)

### 2. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure environment

Create a `.env` file in the project root:

```env
# Google OAuth
GOOGLE_OAUTH_CLIENT_SECRETS=data/client_secret.json
OAUTH_REDIRECT_URI=http://127.0.0.1:8000/auth/google/callback
TOKEN_STORE_PATH=data/token.json

# AI mode: mock | gemini | claude
TRIAGE_MODE=gemini

# API keys (only needed for the respective mode)
GEMINI_API_KEY=your_gemini_api_key
ANTHROPIC_API_KEY=your_anthropic_api_key
```

### 4. Add Google credentials

Download your OAuth client secrets JSON from Google Cloud Console and save it to `data/client_secret.json`.

### 5. Run

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) and sign in with Google.

## Pages

| Route | Description |
|---|---|
| `/` | Landing page / sign-in |
| `/triage/ui` | Main triage view |
| `/triage/approvals` | View approved items |
| `/auto-archive` | Auto-archive rules editor |
| `/analytics` | Stats dashboard |

## AI Modes

Set `TRIAGE_MODE` in your `.env`:

| Value | Model | Notes |
|---|---|---|
| `mock` | None | Instant, no API key needed — good for development |
| `gemini` | Gemini 2.0 Flash Lite | Default production mode |
| `claude` | Claude Haiku (`claude-haiku-4-5-20251001`) | Cheapest Claude option |

## Project Structure

```
app/
├── main.py              # FastAPI app + lifespan (scheduler, db init)
├── oauth.py             # Google OAuth2 flow
├── inbox.py             # Gmail inbox fetching (concurrent)
├── triage_api.py        # Core triage logic + DB persistence
├── triage_ui.py         # UI routes (approve, apply, send, draft)
├── llm.py               # LLM dispatcher (gemini / claude / mock)
├── mock_llm.py          # Mock triage for development
├── gmail_actions.py     # Apply labels, send replies, create drafts
├── gmail_client.py      # Authenticated Gmail service
├── auto_archive.py      # Auto-archive rules + scan + apply
├── pattern_analyzer.py  # Detect patterns in approval history
├── analytics.py         # Stats aggregation
├── scheduler.py         # APScheduler jobs
├── db.py                # SQLite schema + migrations
└── templates/           # Jinja2 HTML templates
```

## Database

SQLite at `data/triage.db` with tables:

- `batches` — each triage run
- `triage_items` — per-email results with approval/apply state
- `apply_log` — record of Gmail actions taken
- `scheduled_sends` — queued scheduled replies
