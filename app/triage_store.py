# app/triage_store.py

from typing import Any, Dict

# single in-memory source of truth for Step 7
APPROVALS: Dict[str, Dict[str, Any]] = {}