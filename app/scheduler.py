from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _run_weekly_triage() -> None:
    try:
        from app.triage_api import run_triage
        result = run_triage(max_results=50)
        logger.info("Weekly triage complete — batch_id=%s", result.get("batch_id"))
    except Exception as e:
        logger.error("Weekly triage failed: %s", e)


def _process_scheduled_sends() -> None:
    try:
        from app.db import get_conn, now_iso
        from app.gmail_client import get_gmail_service
        from app.gmail_actions import send_reply

        now = now_iso()
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM scheduled_sends WHERE sent=0 AND error IS NULL AND send_at <= ?",
                (now,),
            ).fetchall()

            if not rows:
                return

            try:
                service = get_gmail_service()
            except Exception as e:
                logger.warning("Scheduled sends: could not get Gmail service — %s", e)
                return

            for row in rows:
                try:
                    send_reply(
                        service,
                        to=row["to_addr"],
                        subject=row["subject"],
                        body=row["body"],
                        thread_id=row["thread_id"],
                    )
                    conn.execute(
                        "UPDATE scheduled_sends SET sent=1, sent_at=? WHERE id=?",
                        (now_iso(), row["id"]),
                    )
                    logger.info("Scheduled send delivered — id=%s", row["id"])
                except Exception as e:
                    conn.execute(
                        "UPDATE scheduled_sends SET error=? WHERE id=?",
                        (str(e), row["id"]),
                    )
                    logger.error("Scheduled send failed — id=%s: %s", row["id"], e)
    except Exception as e:
        logger.error("_process_scheduled_sends error: %s", e)


def start_scheduler() -> None:
    global _scheduler
    _scheduler = BackgroundScheduler(timezone="UTC")

    # Weekly triage: every Saturday at 08:00 UTC
    _scheduler.add_job(
        _run_weekly_triage,
        "cron",
        day_of_week="sat",
        hour=8,
        minute=0,
        id="weekly_triage",
    )

    # Deliver scheduled sends every minute
    _scheduler.add_job(
        _process_scheduled_sends,
        "interval",
        minutes=1,
        id="scheduled_sends",
    )

    _scheduler.start()
    logger.info("Scheduler started — weekly triage: Saturday 08:00 UTC")


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
