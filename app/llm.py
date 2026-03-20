import json
import os
from typing import Any, Dict, List

SYSTEM_PROMPT = """You are an email triage assistant.
Return ONLY valid JSON. No markdown. No commentary.

Categories:
- ARCHIVE: FYI/notifications/no action required
- READ_LATER: newsletters/long reads
- REPLY: sender expects a response
- TASK: should become a to-do (not immediate reply)
- DELEGATE: someone else should handle it

Rules:
- Minimize questions.
- Draft replies should be concise and professional.
- If ARCHIVE or READ_LATER: draft_reply and task_suggestion MUST be null.
- confidence is 0..1.
"""

SUMMARY_SYSTEM_PROMPT = """You are an executive assistant summarizing an inbox.
Return ONLY valid JSON with this exact shape:
{"headline": "string", "key_actions": ["string"], "fyi": ["string"], "total": number}

- headline: one punchy sentence describing the inbox state
- key_actions: up to 5 emails that need action, each formatted as "Sender Name: Subject — why it matters"
- fyi: up to 3 informational items worth noting
- total: total number of emails summarized
"""


def _build_triage_payload(emails: List[dict]) -> dict:
    return {
        "preferences": {
            "tone": "concise, warm, professional",
            "never_auto_archive_if_from_contains": ["@eliseai.com"],
        },
        "required_output_json_shape": {
            "batch_summary": "string",
            "items": [
                {
                    "message_id": "string",
                    "thread_id": "string",
                    "from": "string",
                    "subject": "string",
                    "date": "string",
                    "category": "ARCHIVE|REPLY|TASK|READ_LATER|DELEGATE",
                    "confidence": "number 0..1",
                    "reason": "string",
                    "suggested_labels": ["string"],
                    "draft_reply": "null OR {to, cc[], subject, body}",
                    "task_suggestion": "null OR {title, notes, due}",
                    "questions_for_user": ["string"],
                }
            ],
        },
        "emails": emails,
    }


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
    return text.strip()


# ── Gemini ────────────────────────────────────────────────────────────────────

def triage_with_gemini(emails: List[dict]) -> Dict[str, Any]:
    from google import genai
    from google.genai import types

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY env var")

    client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model="models/gemini-2.0-flash-lite",
        contents=json.dumps(_build_triage_payload(emails)),
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.2,
            response_mime_type="application/json",
        ),
    )
    return json.loads((resp.text or "").strip())


def summarize_with_gemini(emails: List[dict]) -> Dict[str, Any]:
    from google import genai
    from google.genai import types

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY env var")

    client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model="models/gemini-2.0-flash-lite",
        contents=json.dumps({"emails": emails}),
        config=types.GenerateContentConfig(
            system_instruction=SUMMARY_SYSTEM_PROMPT,
            temperature=0.3,
            response_mime_type="application/json",
        ),
    )
    return json.loads((resp.text or "").strip())


# ── Claude ────────────────────────────────────────────────────────────────────

def triage_with_claude(emails: List[dict]) -> Dict[str, Any]:
    import anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("Missing ANTHROPIC_API_KEY env var")

    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps(_build_triage_payload(emails))}],
    )
    return json.loads(_strip_code_fences(msg.content[0].text))


def summarize_with_claude(emails: List[dict]) -> Dict[str, Any]:
    import anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("Missing ANTHROPIC_API_KEY env var")

    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=SUMMARY_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps({"emails": emails})}],
    )
    return json.loads(_strip_code_fences(msg.content[0].text))


# ── Dispatchers ───────────────────────────────────────────────────────────────

def triage_with_llm(emails: List[dict]) -> Dict[str, Any]:
    mode = os.getenv("TRIAGE_MODE", "mock").lower()
    if mode == "claude":
        return triage_with_claude(emails)
    return triage_with_gemini(emails)


def summarize_inbox(emails: List[dict]) -> Dict[str, Any]:
    mode = os.getenv("TRIAGE_MODE", "mock").lower()
    if mode == "mock":
        return {
            "headline": f"You have {len(emails)} emails in your inbox.",
            "key_actions": [
                f"{e.get('from', '?')}: {e.get('subject', '(no subject)')}"
                for e in emails[:5]
            ],
            "fyi": [],
            "total": len(emails),
        }
    if mode == "claude":
        return summarize_with_claude(emails)
    return summarize_with_gemini(emails)
