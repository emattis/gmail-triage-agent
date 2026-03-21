from __future__ import annotations

from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.db import get_conn

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

MINUTES_SAVED_PER_EMAIL = 2  # rough estimate: manual triage ~2 min, tool ~15 sec

CATEGORY_COLORS = {
    "REPLY":      "#34D399",
    "TASK":       "#FBBF24",
    "ARCHIVE":    "#94A3B8",
    "READ_LATER": "#60A5FA",
    "DELEGATE":   "#A78BFA",
}


def _week_start_iso() -> str:
    now = datetime.now(timezone.utc)
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def _fmt_time(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes / 60
    return f"{hours:.1f} hrs"


def build_stats() -> dict:
    week_start = _week_start_iso()

    with get_conn() as conn:

        # ── This week ─────────────────────────────────────────────────────────
        this_week = conn.execute(
            """
            SELECT COUNT(*) FROM triage_items ti
            JOIN batches b ON ti.batch_id = b.batch_id
            WHERE b.created_at >= ? AND b.mode != 'auto_archive'
            """,
            (week_start,),
        ).fetchone()[0]

        # ── All time (AI batches only) ─────────────────────────────────────
        all_time = conn.execute(
            """
            SELECT COUNT(*) FROM triage_items ti
            JOIN batches b ON ti.batch_id = b.batch_id
            WHERE b.mode != 'auto_archive'
            """
        ).fetchone()[0]

        auto_archived_total = conn.execute(
            """
            SELECT COUNT(*) FROM triage_items ti
            JOIN batches b ON ti.batch_id = b.batch_id
            WHERE b.mode = 'auto_archive' AND ti.applied = 1
            """
        ).fetchone()[0]

        # ── Category breakdown (all approved) ─────────────────────────────
        cat_rows = conn.execute(
            """
            SELECT category, COUNT(*) as n
            FROM triage_items
            WHERE approved = 1
            GROUP BY category
            ORDER BY n DESC
            """
        ).fetchall()
        categories = [{"category": r["category"], "count": r["n"]} for r in cat_rows]
        total_approved = sum(c["count"] for c in categories)

        for c in categories:
            c["pct"] = round(c["count"] / total_approved * 100) if total_approved else 0
            c["color"] = CATEGORY_COLORS.get(c["category"], "#CBD5E1")

        # ── Accuracy (requires original_category) ─────────────────────────
        acc_row = conn.execute(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN category = original_category THEN 1 ELSE 0 END) as agreed,
                SUM(CASE WHEN category != original_category THEN 1 ELSE 0 END) as overridden
            FROM triage_items
            WHERE approved = 1 AND original_category IS NOT NULL
            """
        ).fetchone()

        accuracy = None
        accuracy_total = acc_row["total"] if acc_row else 0
        if accuracy_total > 0:
            accuracy = round(acc_row["agreed"] / accuracy_total * 100)

        overrides = acc_row["overridden"] if acc_row else 0

        # ── Time saved ────────────────────────────────────────────────────
        total_applied = conn.execute(
            "SELECT COUNT(*) FROM triage_items WHERE applied = 1"
        ).fetchone()[0]

        minutes_saved = (total_applied + auto_archived_total) * MINUTES_SAVED_PER_EMAIL

        # ── Batch history ─────────────────────────────────────────────────
        batch_rows = conn.execute(
            """
            SELECT
                b.batch_id,
                b.created_at,
                b.mode,
                b.max_results,
                COUNT(ti.id) as total,
                SUM(ti.approved) as approved,
                SUM(ti.applied) as applied
            FROM batches b
            LEFT JOIN triage_items ti ON ti.batch_id = b.batch_id
            GROUP BY b.batch_id
            ORDER BY b.created_at DESC
            LIMIT 10
            """
        ).fetchall()

        batches = []
        for r in batch_rows:
            try:
                dt = datetime.fromisoformat(r["created_at"])
                label = dt.strftime("%b %d, %I:%M %p")
            except Exception:
                label = r["created_at"]
            batches.append({
                "created_at": label,
                "mode": r["mode"],
                "total": r["total"],
                "approved": r["approved"] or 0,
                "applied": r["applied"] or 0,
            })

    return {
        "this_week": this_week,
        "all_time": all_time,
        "auto_archived_total": auto_archived_total,
        "total_approved": total_approved,
        "categories": categories,
        "accuracy": accuracy,
        "accuracy_total": accuracy_total,
        "overrides": overrides,
        "minutes_saved": minutes_saved,
        "time_saved": _fmt_time(minutes_saved),
        "batches": batches,
    }


@router.get("/analytics", response_class=HTMLResponse)
def analytics_page(request: Request):
    stats = build_stats()
    return templates.TemplateResponse("analytics.html", {"request": request, **stats})
