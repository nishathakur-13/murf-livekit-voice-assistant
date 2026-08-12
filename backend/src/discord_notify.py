"""
discord_notify.py — Send escalation notifications to a Discord channel via webhook.

Uses only the stdlib (urllib.request) so no extra dependencies are needed.
"""

import json
import logging
import os
import urllib.error
import urllib.request
from urllib.parse import urlparse

logger = logging.getLogger("discord_notify")

# DISCORD_WEBHOOK_URL must be set in backend/.env.local
# Read lazily so load_dotenv() in agent.py runs first.
def _get_webhook_url() -> str:
    return os.environ.get("DISCORD_WEBHOOK_URL", "")

_URGENCY_COLORS = {
    "low": 3066993,       # green
    "medium": 16776960,   # yellow
    "high": 15158332,     # orange-red
    "emergency": 15548997, # red
}

_URGENCY_EMOJI = {
    "low": "🟢",
    "medium": "🟡",
    "high": "🔴",
    "emergency": "🚨",
}


def send_escalation(record: dict) -> bool:
    """
    POST an escalation record to Discord as a rich embed.
    Returns True on success, False on failure (non-blocking).
    """
    webhook_url = _get_webhook_url()
    if not webhook_url:
        logger.warning(
            "DISCORD_WEBHOOK_URL is not set — skipping Discord notification"
        )
        return False

    # Validate it looks like a Discord webhook URL
    try:
        parsed = urlparse(webhook_url)
        if "discord" not in parsed.netloc:
            logger.warning(
                "DISCORD_WEBHOOK_URL does not look like a Discord URL — skipping"
            )
            return False
    except Exception:
        return False

    urgency = record.get("urgency", "medium").lower()
    color = _URGENCY_COLORS.get(urgency, _URGENCY_COLORS["medium"])
    emoji = _URGENCY_EMOJI.get(urgency, "🟡")

    embed = {
        "title": f"{emoji} KrishiMitra Escalation Request",
        "color": color,
        "fields": [
            {
                "name": "📋 Reference ID",
                "value": f"`{record.get('reference_id', 'N/A')}`",
                "inline": True,
            },
            {
                "name": "⚠️ Urgency",
                "value": urgency.upper(),
                "inline": True,
            },
            {
                "name": "🌾 Situation",
                "value": record.get("situation_type", "Unknown"),
                "inline": False,
            },
            {
                "name": "👤 Caller",
                "value": record.get("caller_name", "Unknown"),
                "inline": True,
            },
            {
                "name": "🗣️ Language",
                "value": record.get("language", "Unknown"),
                "inline": True,
            },
            {
                "name": "📞 Follow-up Method",
                "value": record.get("follow_up_method", "N/A"),
                "inline": True,
            },
            {
                "name": "📝 Summary",
                "value": record.get("summary", "No summary provided.")[:500],
                "inline": False,
            },
            {
                "name": "🔍 What Agent Tried",
                "value": record.get("what_agent_tried", "N/A")[:300],
                "inline": False,
            },
        ],
        "footer": {
            "text": f"Created at {record.get('created_at', 'N/A')} UTC | KrishiMitra AI"
        },
    }

    payload = json.dumps({"embeds": [embed]}).encode("utf-8")

    try:
        req = urllib.request.Request(
            webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status in (200, 204):
                logger.info(
                    "Discord notification sent for %s", record.get("reference_id")
                )
                return True
            else:
                logger.warning(
                    "Discord webhook returned status %s", resp.status
                )
                return False
    except urllib.error.HTTPError as exc:
        logger.error("Discord webhook HTTP error: %s %s", exc.code, exc.reason)
        return False
    except Exception as exc:
        logger.error("Discord webhook error: %s", exc)
        return False
