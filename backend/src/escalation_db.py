"""
escalation_db.py — JSON-based escalation store for KrishiMitra AI.

Stores escalation requests in backend/src/escalations.json.
Thread-safe via a threading lock.
"""

import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime

logger = logging.getLogger("escalation_db")

# Path to the escalations JSON file (same folder as this script)
_DB_PATH = os.path.join(os.path.dirname(__file__), "escalations.json")
_lock = threading.Lock()


def _strip_sensitive(text: str) -> str:
    """Remove patterns that look like OTPs, PINs, or account numbers (4–16 consecutive digits)."""
    return re.sub(r"\b\d{4,16}\b", "[REDACTED]", text).strip()


def _load() -> dict:
    """Load the escalations JSON file. Returns {"escalations": []} if missing/empty."""
    if not os.path.exists(_DB_PATH):
        return {"escalations": []}
    try:
        with open(_DB_PATH, encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict) or "escalations" not in data:
                return {"escalations": []}
            return data
    except (json.JSONDecodeError, OSError):
        return {"escalations": []}


def _save(data: dict) -> None:
    """Write the escalations dict back to disk."""
    with open(_DB_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def create_escalation(
    user_id: str,
    caller_name: str | None,
    situation_type: str,
    summary: str,
    urgency: str,
    language: str,
    follow_up_method: str,
    what_agent_tried: str,
) -> str:
    """
    Create a new escalation record and persist it.

    Returns the reference_id (e.g. "ESC-7F3A2B").
    """
    reference_id = "ESC-" + uuid.uuid4().hex[:6].upper()
    record = {
        "reference_id": reference_id,
        "user_id": user_id,
        "caller_name": caller_name if caller_name and caller_name.strip() else None,
        "situation_type": situation_type,
        "summary": _strip_sensitive(summary),
        "urgency": urgency,           # low / medium / high / emergency
        "language": language,
        "follow_up_method": follow_up_method,
        "what_agent_tried": _strip_sensitive(what_agent_tried),
        "status": "open",             # open / in_progress / resolved
        "created_at": datetime.utcnow().isoformat() + "Z",
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }
    with _lock:
        data = _load()
        # Dedup: if an open escalation with same user_id + situation_type exists,
        # return its ID instead of creating a duplicate.
        for existing in data["escalations"]:
            if (
                existing["user_id"] == user_id
                and existing["situation_type"] == situation_type
                and existing["status"] == "open"
            ):
                logger.info(
                    "Duplicate escalation detected for user=%s type=%s — returning existing %s",
                    user_id,
                    situation_type,
                    existing["reference_id"],
                )
                return existing["reference_id"]

        data["escalations"].append(record)
        _save(data)

    logger.info("Created escalation %s for user=%s", reference_id, user_id)
    return reference_id


def get_all_escalations() -> list[dict]:
    """Return all escalations, newest first."""
    with _lock:
        data = _load()
    escalations = data.get("escalations", [])
    return sorted(escalations, key=lambda e: e.get("created_at", ""), reverse=True)


def get_escalation(reference_id: str) -> dict | None:
    """Return a single escalation by reference_id, or None."""
    with _lock:
        data = _load()
    for esc in data.get("escalations", []):
        if esc["reference_id"] == reference_id:
            return esc
    return None


def update_status(reference_id: str, status: str) -> bool:
    """Update the status of an escalation. Returns True if found."""
    with _lock:
        data = _load()
        for esc in data["escalations"]:
            if esc["reference_id"] == reference_id:
                esc["status"] = status
                esc["updated_at"] = datetime.utcnow().isoformat() + "Z"
                _save(data)
                logger.info("Escalation %s status → %s", reference_id, status)
                return True
    return False
