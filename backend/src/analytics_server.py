"""
analytics_server.py — Lightweight HTTP server exposing call analytics data.

Runs on port 8001 so it doesn't conflict with Next.js (3000) or any other service.
Start it with:
    uv run python src/analytics_server.py

Endpoints:
  GET  /analytics/summary    — aggregate stats (total, success, failed, etc.)
  GET  /analytics/calls      — recent call history (last 50 calls)
  POST /analytics/seed       — insert a test record (dev only)
"""

import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

# Allow imports from this directory when run directly
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv

load_dotenv(
    os.path.join(os.path.dirname(__file__), "..", ".env.local"),
    override=True,
)

from analytics_db import (
    get_analytics_summary,
    get_recent_calls,
    init_analytics,
    record_call_end,
    record_call_start,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("analytics_server")

PORT = int(os.environ.get("ANALYTICS_PORT", "8001"))

# ---------------------------------------------------------------------------
# CORS helper — allow Next.js dev (localhost:3000) to call this API
# ---------------------------------------------------------------------------

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


def _send_json(handler: BaseHTTPRequestHandler, data: object, status: int = 200) -> None:
    body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    for k, v in CORS_HEADERS.items():
        handler.send_header(k, v)
    handler.end_headers()
    handler.wfile.write(body)


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------


class AnalyticsHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: N802
        logger.info("HTTP %s", fmt % args)

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        for k, v in CORS_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]

        if path == "/analytics/summary":
            try:
                data = get_analytics_summary()
                _send_json(self, data)
            except Exception as exc:
                logger.exception("Error in /analytics/summary: %s", exc)
                _send_json(self, {"error": str(exc)}, status=500)

        elif path == "/analytics/calls":
            try:
                calls = get_recent_calls(limit=50)
                _send_json(self, {"calls": calls, "count": len(calls)})
            except Exception as exc:
                logger.exception("Error in /analytics/calls: %s", exc)
                _send_json(self, {"error": str(exc)}, status=500)

        elif path in ("/", "/health"):
            _send_json(self, {"status": "ok", "service": "krishimitra-analytics"})

        else:
            _send_json(self, {"error": "Not found"}, status=404)

    def do_POST(self):  # noqa: N802
        path = self.path.split("?")[0]

        if path == "/analytics/seed":
            # Dev-only endpoint — insert a fake call record so you can verify
            # the dashboard immediately without running the full agent.
            import uuid
            from datetime import datetime, timezone

            session_id = "seed-" + uuid.uuid4().hex[:8]
            user_id = "seed_user_dev"
            record_call_start(session_id, user_id, channel="web")
            record_call_end(
                session_id,
                outcome="success",
                language="Hinglish",
                notes="Seeded via /analytics/seed",
            )
            _send_json(self, {"seeded": True, "session_id": session_id})

        else:
            _send_json(self, {"error": "Not found"}, status=404)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_analytics()
    logger.info("KrishiMitra Analytics Server starting on port %d …", PORT)
    httpd = HTTPServer(("0.0.0.0", PORT), AnalyticsHandler)
    logger.info("Analytics API ready at http://localhost:%d/analytics/summary", PORT)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down analytics server.")
        httpd.server_close()
