"""
analytics_db.py — Call analytics for KrishiMitra AI.

Tracks every call: when it started, when it ended, duration, outcome, and
failure type when applicable.

Success condition (Farm & Field track):
  A call is SUCCESSFUL if the farmer received the information they asked for
  (crop advice, mandi price, weather, or scheme details) OR was escalated to
  a human expert.
  A call FAILS if the farmer hung up before receiving a helpful response,
  the agent encountered a technical error, or the connection was never
  established.

Schema
------
call_analytics
  id              INTEGER  PRIMARY KEY AUTOINCREMENT
  session_id      TEXT     UNIQUE  -- LiveKit room name (unique per call)
  user_id         TEXT             -- participant identity
  channel         TEXT             -- "web" or "sip"
  started_at      TEXT             -- ISO-8601 UTC
  ended_at        TEXT             -- ISO-8601 UTC (NULL while in progress)
  duration_sec    REAL             -- seconds, NULL until ended
  outcome         TEXT             -- "success" | "failed" | "in_progress"
  failure_type    TEXT             -- "user_hangup" | "no_response" | "api_error"
                                   --   | "incomplete_task" | NULL for success
  language        TEXT             -- detected language, e.g. "Hindi"
  escalated       INTEGER          -- 1 if farmer was escalated, else 0
  notes           TEXT             -- free-form notes, e.g. topic served
"""

import logging
import os
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger("analytics_db")

DB_PATH = os.path.join(os.path.dirname(__file__), "krishimitra_memory.db")


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Schema bootstrap — called once on startup
# ---------------------------------------------------------------------------

def init_analytics() -> None:
    """Create call_analytics table if it does not exist."""
    conn = _get_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS call_analytics (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id   TEXT    UNIQUE NOT NULL,
                user_id      TEXT    NOT NULL,
                channel      TEXT    NOT NULL DEFAULT 'web',
                started_at   TEXT    NOT NULL,
                ended_at     TEXT,
                duration_sec REAL,
                outcome      TEXT    NOT NULL DEFAULT 'in_progress',
                failure_type TEXT,
                language     TEXT,
                escalated    INTEGER NOT NULL DEFAULT 0,
                notes        TEXT
            )
            """
        )
        conn.commit()
        logger.info("call_analytics table ready in %s", DB_PATH)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

def record_call_start(
    session_id: str,
    user_id: str,
    channel: str = "web",
) -> None:
    """Insert a new in-progress call record."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_connection()
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO call_analytics
                (session_id, user_id, channel, started_at, outcome)
            VALUES (?, ?, ?, ?, 'in_progress')
            """,
            (session_id, user_id, channel, now),
        )
        conn.commit()
        logger.info("Call started: session=%s user=%s channel=%s", session_id, user_id, channel)
    finally:
        conn.close()


def record_call_end(
    session_id: str,
    outcome: str,                 # "success" | "failed"
    failure_type: str | None = None,
    language: str | None = None,
    escalated: bool = False,
    notes: str | None = None,
) -> None:
    """
    Close an existing call record with its outcome.

    outcome must be "success" or "failed".
    failure_type is only relevant when outcome == "failed":
      - "user_hangup"      caller disconnected before getting help
      - "incomplete_task"  agent was helping but call cut off mid-task
      - "api_error"        tool/LLM/TTS failure prevented the agent from responding
      - "no_response"      agent never responded (STT/connection issue)
    """
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_connection()
    try:
        # Look up start time to compute duration
        row = conn.execute(
            "SELECT started_at FROM call_analytics WHERE session_id = ?",
            (session_id,),
        ).fetchone()

        duration = None
        if row:
            try:
                start = datetime.fromisoformat(row["started_at"])
                end   = datetime.fromisoformat(now)
                duration = (end - start).total_seconds()
            except Exception:
                pass

        conn.execute(
            """
            UPDATE call_analytics
            SET ended_at     = ?,
                duration_sec = ?,
                outcome      = ?,
                failure_type = ?,
                language     = COALESCE(?, language),
                escalated    = ?,
                notes        = COALESCE(?, notes)
            WHERE session_id = ?
            """,
            (
                now,
                duration,
                outcome,
                failure_type,
                language,
                1 if escalated else 0,
                notes,
                session_id,
            ),
        )
        conn.commit()
        logger.info(
            "Call ended: session=%s outcome=%s failure=%s duration=%.1fs",
            session_id, outcome, failure_type, duration or 0,
        )
    finally:
        conn.close()


def mark_call_escalated(session_id: str) -> None:
    """Mark that this call resulted in a human escalation (counts as success)."""
    conn = _get_connection()
    try:
        conn.execute(
            "UPDATE call_analytics SET escalated = 1 WHERE session_id = ?",
            (session_id,),
        )
        conn.commit()
        logger.info("Call marked as escalated: session=%s", session_id)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Read helpers — used by the analytics HTTP endpoint
# ---------------------------------------------------------------------------

def get_analytics_summary() -> dict:
    """
    Return aggregate counts for the dashboard.

    {
      "total_calls": int,
      "successful_calls": int,
      "failed_calls": int,
      "in_progress_calls": int,
      "success_rate": float,          # 0-100 percent
      "escalated_calls": int,
      "failure_breakdown": {
        "user_hangup": int,
        "incomplete_task": int,
        "api_error": int,
        "no_response": int,
        "other": int
      }
    }
    """
    conn = _get_connection()
    try:
        row = conn.execute(
            """
            SELECT
              COUNT(*)                                          AS total,
              SUM(CASE WHEN outcome = 'success'     THEN 1 ELSE 0 END) AS successful,
              SUM(CASE WHEN outcome = 'failed'      THEN 1 ELSE 0 END) AS failed,
              SUM(CASE WHEN outcome = 'in_progress' THEN 1 ELSE 0 END) AS in_progress,
              SUM(CASE WHEN escalated = 1           THEN 1 ELSE 0 END) AS escalated,
              SUM(CASE WHEN failure_type = 'user_hangup'      THEN 1 ELSE 0 END) AS ft_hangup,
              SUM(CASE WHEN failure_type = 'incomplete_task'  THEN 1 ELSE 0 END) AS ft_incomplete,
              SUM(CASE WHEN failure_type = 'api_error'        THEN 1 ELSE 0 END) AS ft_api_error,
              SUM(CASE WHEN failure_type = 'no_response'      THEN 1 ELSE 0 END) AS ft_no_response,
              SUM(CASE WHEN failure_type NOT IN (
                        'user_hangup','incomplete_task','api_error','no_response')
                        AND failure_type IS NOT NULL THEN 1 ELSE 0 END) AS ft_other
            FROM call_analytics
            """
        ).fetchone()

        total       = row["total"]       or 0
        successful  = row["successful"]  or 0
        failed      = row["failed"]      or 0
        in_progress = row["in_progress"] or 0
        escalated   = row["escalated"]   or 0

        # Success rate calculated only over completed calls
        completed = successful + failed
        success_rate = round((successful / completed) * 100, 1) if completed else 0.0

        return {
            "total_calls":      total,
            "successful_calls": successful,
            "failed_calls":     failed,
            "in_progress_calls": in_progress,
            "success_rate":     success_rate,
            "escalated_calls":  escalated,
            "failure_breakdown": {
                "user_hangup":     row["ft_hangup"]     or 0,
                "incomplete_task": row["ft_incomplete"]  or 0,
                "api_error":       row["ft_api_error"]   or 0,
                "no_response":     row["ft_no_response"] or 0,
                "other":           row["ft_other"]       or 0,
            },
        }
    finally:
        conn.close()


def get_recent_calls(limit: int = 20) -> list[dict]:
    """
    Return the most recent calls for the call history table.
    Sensitive fields (user_id) are excluded.
    """
    conn = _get_connection()
    try:
        rows = conn.execute(
            """
            SELECT
              session_id,
              channel,
              started_at,
              ended_at,
              duration_sec,
              outcome,
              failure_type,
              language,
              escalated,
              notes
            FROM call_analytics
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
