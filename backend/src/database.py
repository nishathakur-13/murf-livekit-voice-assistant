"""
database.py — Persistent memory for KrishiMitra AI
SQLite-backed storage for caller profiles and farming facts.

Schema
------
users
  user_id            TEXT  PRIMARY KEY   -- room/participant identity from LiveKit
  name               TEXT               -- caller's name
  language_preference TEXT              -- e.g. "Hindi", "English", "Hinglish"
  facts              TEXT               -- JSON blob: crops, district, land_size, irrigation_type …
  last_interaction   TEXT               -- ISO-8601 UTC timestamp
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger("database")

# Keep the DB next to this file; easy to find, survives restarts
DB_PATH = os.path.join(os.path.dirname(__file__), "krishimitra_memory.db")


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------


def _get_connection() -> sqlite3.Connection:
    """Return a thread-safe SQLite connection with row_factory set."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------


def init_db() -> None:
    """Create the users table if it does not already exist."""
    conn = _get_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id             TEXT PRIMARY KEY,
                name                TEXT,
                language_preference TEXT,
                facts               TEXT DEFAULT '{}',
                last_interaction    TEXT
            )
            """
        )
        conn.commit()
        logger.info("Database initialised at %s", DB_PATH)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------


def get_user(user_id: str) -> dict | None:
    """
    Return the user record as a plain dict, or None if not found.

    Example return value:
    {
        "user_id": "room_abc123",
        "name": "Ramesh",
        "language_preference": "Hindi",
        "facts": {"crops": ["cotton", "wheat"], "district": "Wardha"},
        "last_interaction": "2025-08-09T15:30:00+00:00"
    }
    """
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row is None:
            return None
        record = dict(row)
        record["facts"] = json.loads(record.get("facts") or "{}")
        return record
    finally:
        conn.close()


def save_user(
    user_id: str,
    name: str | None = None,
    language_preference: str | None = None,
    facts: dict | None = None,
) -> dict:
    """
    Insert a new user or fully replace an existing one.
    Returns the saved record.
    """
    now = datetime.now(timezone.utc).isoformat()
    facts_json = json.dumps(facts or {})

    conn = _get_connection()
    try:
        # Check if user already exists so we can merge facts intelligently
        existing = get_user(user_id)
        if existing:
            merged_facts = {**existing.get("facts", {}), **(facts or {})}
            conn.execute(
                """
                INSERT INTO users (user_id, name, language_preference, facts, last_interaction)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    name               = COALESCE(excluded.name, users.name),
                    language_preference= COALESCE(excluded.language_preference, users.language_preference),
                    facts              = excluded.facts,
                    last_interaction   = excluded.last_interaction
                """,
                (
                    user_id,
                    name or existing.get("name"),
                    language_preference or existing.get("language_preference"),
                    json.dumps(merged_facts),
                    now,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO users (user_id, name, language_preference, facts, last_interaction)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, name, language_preference, facts_json, now),
            )
        conn.commit()
        logger.info("Saved user record for user_id=%s", user_id)
        return get_user(user_id)
    finally:
        conn.close()


def update_user_facts(user_id: str, new_facts: dict) -> dict | None:
    """
    Merge new_facts into the existing facts dict for a known user.
    Returns the updated record, or None if the user does not exist.
    """
    existing = get_user(user_id)
    if existing is None:
        logger.warning("update_user_facts: user_id=%s not found", user_id)
        return None

    merged = {**existing.get("facts", {}), **new_facts}
    now = datetime.now(timezone.utc).isoformat()

    conn = _get_connection()
    try:
        conn.execute(
            "UPDATE users SET facts = ?, last_interaction = ? WHERE user_id = ?",
            (json.dumps(merged), now, user_id),
        )
        conn.commit()
        logger.info("Updated facts for user_id=%s", user_id)
        return get_user(user_id)
    finally:
        conn.close()


def delete_user(user_id: str) -> bool:
    """
    Delete a user record completely.  Returns True if a row was deleted.
    """
    conn = _get_connection()
    try:
        cursor = conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        conn.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            logger.info("Deleted user record for user_id=%s", user_id)
        else:
            logger.warning("delete_user: user_id=%s not found", user_id)
        return deleted
    finally:
        conn.close()
