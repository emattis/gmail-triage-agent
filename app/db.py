# app/db.py
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional, Tuple

DB_PATH = os.getenv("DB_PATH", "data/app.db")

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def db_path() -> str:
    # Default to data/app.db (your .gitignore already ignores data/)
    return os.getenv("DB_PATH", "data/app.db")


def init_db() -> None:
    path = db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS batches (
                batch_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                mode TEXT,
                max_results INTEGER
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS triage_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                thread_id TEXT,
                sender TEXT,
                subject TEXT,
                date TEXT,
                snippet TEXT,
                category TEXT,
                confidence REAL,
                reason TEXT,
                suggested_labels_json TEXT,
                draft_reply TEXT,
                approved INTEGER DEFAULT 0,
                edited_draft_body TEXT,
                applied INTEGER DEFAULT 0,
                applied_at TEXT,
                UNIQUE(batch_id, message_id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_items_batch ON triage_items(batch_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_items_mid ON triage_items(message_id)")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS apply_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                category TEXT,
                labels_added_json TEXT,
                removed_inbox INTEGER,
                created_at TEXT NOT NULL
            )
            """
        )


@contextmanager
def get_conn():
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_latest_batch_id(conn: sqlite3.Connection) -> Optional[str]:
    row = conn.execute(
        "SELECT batch_id FROM batches ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    return row["batch_id"] if row else None


def require_latest_batch_id(conn: sqlite3.Connection) -> str:
    bid = get_latest_batch_id(conn)
    if not bid:
        raise RuntimeError("No batches found. Run /triage/run first.")
    return bid