from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from app.db import get_conn

MIN_OCCURRENCES = 3   # minimum emails needed to detect a pattern
MIN_CONFIDENCE = 0.80  # 80% of decisions must be the same action


def _extract_domain(sender: str) -> str | None:
    match = re.search(r"@([\w.-]+)", sender.lower())
    return match.group(1) if match else None


def analyze_patterns() -> dict[str, Any]:
    """
    Scan approved triage decisions and surface:
    - suggested_archive_rules: domains you consistently archive (→ add to auto-archive)
    - insights: senders you consistently reply to or task (informational)
    """
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT sender, subject, category
            FROM triage_items
            WHERE approved = 1 AND sender != ''
            ORDER BY id DESC
            LIMIT 500
            """
        ).fetchall()

    total = len(rows)
    if total < 10:
        return {
            "suggestions": [],
            "insights": [],
            "total_analyzed": total,
            "insufficient_data": True,
        }

    # Bucket decisions by domain
    domain_cats: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        domain = _extract_domain(row["sender"] or "")
        if domain:
            domain_cats[domain].append((row["category"] or "").upper())

    suggestions: list[dict] = []
    insights: list[dict] = []

    for domain, cats in domain_cats.items():
        n = len(cats)
        if n < MIN_OCCURRENCES:
            continue

        archive_rate = cats.count("ARCHIVE") / n
        reply_rate = cats.count("REPLY") / n
        task_rate = cats.count("TASK") / n

        if archive_rate >= MIN_CONFIDENCE:
            suggestions.append({
                "rule_type": "sender_domains",
                "value": domain,
                "label": f"@{domain}",
                "evidence": f"{cats.count('ARCHIVE')} of {n} emails archived",
                "count": n,
                "confidence": round(archive_rate * 100),
            })
        elif reply_rate >= MIN_CONFIDENCE:
            insights.append({
                "action": "REPLY",
                "value": domain,
                "evidence": f"You reply to {cats.count('REPLY')} of {n} emails from @{domain}",
            })
        elif task_rate >= MIN_CONFIDENCE:
            insights.append({
                "action": "TASK",
                "value": domain,
                "evidence": f"{cats.count('TASK')} of {n} emails from @{domain} become tasks",
            })

    # Most confident first, then most seen
    suggestions.sort(key=lambda x: (-x["confidence"], -x["count"]))
    insights.sort(key=lambda x: -x.get("count", 0))

    return {
        "suggestions": suggestions,
        "insights": insights[:5],
        "total_analyzed": total,
        "insufficient_data": False,
    }
