import json
import os
from typing import Any, Dict, List

from google import genai
from google.genai import types

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = "models/gemini-2.0-flash-lite"


if not GEMINI_API_KEY:
    raise RuntimeError("Missing GEMINI_API_KEY env var")

client = genai.Client(api_key=GEMINI_API_KEY)

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

def triage_with_llm(emails: List[dict]) -> Dict[str, Any]:
    payload = {
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

    print("USING GEMINI MODEL:", MODEL)


    resp = client.models.generate_content(
        model=MODEL,  # e.g. models/gemini-2.0-flash
        contents=json.dumps(payload),
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.2,
            # This is the key: strongly nudges valid JSON
            response_mime_type="application/json",
        ),
    )

    text = (resp.text or "").strip()
    return json.loads(text)

