"""
outbound_call.py — Trigger KrishiMitra outbound farming tip call via Linphone SIP.

Uses LiveKit's inline trunk configuration to call a Linphone SIP address directly.
No Twilio or stored trunk required — works with a free sip.linphone.org account.

SETUP (one time):
  1. Download Linphone app on your phone: https://linphone.org/en/
  2. Create a free account at: https://subscribe.linphone.org/
     You'll get a SIP address like: yourname@sip.linphone.org
  3. Log into the Linphone app on your phone with those credentials.
  4. Add these 3 lines to backend/.env.local:
       LINPHONE_USERNAME=yourname          (just the username, no @sip.linphone.org)
       LINPHONE_PASSWORD=yourpassword
       LINPHONE_SIP_ADDRESS=yourname@sip.linphone.org

USAGE:
  # Call your Linphone address (default topic)
  uv run python src/outbound_call.py

  # Call with a specific farming topic
  uv run python src/outbound_call.py --topic "kharif soil preparation"

  # Call a different SIP address
  uv run python src/outbound_call.py --to someone@sip.linphone.org

  # Dry run — see what would happen without placing a call
  uv run python src/outbound_call.py --dry-run
"""

import argparse
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime

from dotenv import load_dotenv
from livekit import api

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env.local"), override=True)


def _check_env() -> None:
    required = [
        "LIVEKIT_URL",
        "LIVEKIT_API_KEY",
        "LIVEKIT_API_SECRET",
        "LINPHONE_USERNAME",
        "LINPHONE_PASSWORD",
        "LINPHONE_SIP_ADDRESS",
    ]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        print(f"[ERROR] Missing environment variables: {', '.join(missing)}")
        print(
            "\nAdd these to backend/.env.local:\n"
            "  LINPHONE_USERNAME=yourname\n"
            "  LINPHONE_PASSWORD=yourpassword\n"
            "  LINPHONE_SIP_ADDRESS=yourname@sip.linphone.org\n"
            "\nGet a free Linphone account at: https://subscribe.linphone.org/\n"
        )
        sys.exit(1)


async def dispatch_outbound_call(
    sip_address: str | None = None,
    topic: str = "aaj ka farming tip",
    dry_run: bool = False,
) -> None:
    """
    Dispatch the KrishiMitra agent to call a Linphone SIP address.

    Uses inline trunk config — LiveKit connects directly to sip.linphone.org
    using your Linphone credentials. No stored trunk or Twilio required.
    """
    linphone_username = os.environ.get("LINPHONE_USERNAME", "")
    linphone_password = os.environ.get("LINPHONE_PASSWORD", "")
    linphone_sip_address = sip_address or os.environ.get("LINPHONE_SIP_ADDRESS", "")

    # Normalise — strip sip: prefix if user passed it
    linphone_sip_address = linphone_sip_address.removeprefix("sip:")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    short_id = uuid.uuid4().hex[:6]
    room_name = f"krishimitra-outbound-{timestamp}-{short_id}"

    # We pass the full config in metadata so agent.py can do the inline dial
    metadata = json.dumps(
        {
            # agent.py reads this and dials via inline trunk
            "linphone_sip_address": linphone_sip_address,
            "linphone_username": linphone_username,
            "linphone_password": linphone_password,
            "call_type": "outbound_daily_tip",
            "topic": topic,
        }
    )

    print("\n📞 KrishiMitra Outbound Call — via Linphone")
    print(f"   Calling    : sip:{linphone_sip_address}")
    print(f"   Topic      : {topic}")
    print(f"   Room       : {room_name}")
    print("   Trunk      : inline (sip.linphone.org)")
    print("   Agent      : my-agent")

    if dry_run:
        print("\n[DRY RUN] No call placed. Metadata that would be sent:")
        # Mask password in dry-run output
        display = json.loads(metadata)
        display["linphone_password"] = "***"
        print(f"   {json.dumps(display, indent=2)}")
        print("\nRun without --dry-run to place the real call.\n")
        return

    _check_env()

    if not linphone_sip_address:
        print("[ERROR] No SIP address to call. Set LINPHONE_SIP_ADDRESS in .env.local")
        sys.exit(1)

    print(f"\n⏳ Dispatching agent to room '{room_name}'...")

    async with api.LiveKitAPI() as lkapi:
        try:
            dispatch = await lkapi.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(
                    agent_name="my-agent",
                    room=room_name,
                    metadata=metadata,
                )
            )
            print(f"\n✅  Dispatch created: {dispatch.id}")
            print(
                "\n   What happens next:\n"
                f"   1. Agent connects to room '{room_name}'\n"
                f"   2. Agent dials sip:{linphone_sip_address} via sip.linphone.org\n"
                "   3. Your Linphone app rings — pick up!\n"
                "   4. Agent delivers the farming tip and listens\n"
                "\n   👀 Watch agent terminal for: 'Outbound call answered'\n"
            )
        except Exception as exc:
            print(f"[ERROR] Failed to dispatch agent: {exc}")
            raise


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Trigger a KrishiMitra outbound farming tip call via Linphone",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Setup:
  1. Install Linphone app on your phone: https://linphone.org/en/
  2. Create free account: https://subscribe.linphone.org/
  3. Add to backend/.env.local:
       LINPHONE_USERNAME=yourname
       LINPHONE_PASSWORD=yourpassword
       LINPHONE_SIP_ADDRESS=yourname@sip.linphone.org

Examples:
  uv run python src/outbound_call.py
  uv run python src/outbound_call.py --topic "wheat irrigation tips"
  uv run python src/outbound_call.py --to someone@sip.linphone.org
  uv run python src/outbound_call.py --dry-run
        """,
    )
    parser.add_argument(
        "--to",
        metavar="SIP_ADDRESS",
        default=None,
        help=(
            "SIP address to call, e.g. yourname@sip.linphone.org "
            "(default: LINPHONE_SIP_ADDRESS from .env.local)"
        ),
    )
    parser.add_argument(
        "--topic",
        default="aaj ka farming tip",
        metavar="TOPIC",
        help="Farming topic for today's tip (default: 'aaj ka farming tip')",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without placing a real call",
    )

    args = parser.parse_args()

    asyncio.run(
        dispatch_outbound_call(
            sip_address=args.to,
            topic=args.topic,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
