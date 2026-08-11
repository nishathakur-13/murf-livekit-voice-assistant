"""
setup_outbound_trunk.py — One-time script to create a LiveKit SIP outbound trunk
pointing at your Twilio Elastic SIP Termination URI.

Run once, then copy the printed LIVEKIT_SIP_OUTBOUND_TRUNK_ID into .env.local.

Usage:
    uv run python src/setup_outbound_trunk.py

Environment variables required (in .env.local):
    LIVEKIT_URL
    LIVEKIT_API_KEY
    LIVEKIT_API_SECRET
    TWILIO_SIP_TERM_URI       e.g. mytrunk.pstn.twilio.com
    TWILIO_SIP_USERNAME
    TWILIO_SIP_PASSWORD
    TWILIO_PHONE_NUMBER       e.g. +12015551234  (your Twilio number, E.164)
"""

import asyncio
import os
import sys

from dotenv import load_dotenv
from livekit import api
from livekit.protocol.sip import CreateSIPOutboundTrunkRequest, SIPOutboundTrunkInfo

# Load .env.local from the backend/ directory
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env.local"), override=True)


async def main() -> None:
    required = [
        "LIVEKIT_URL",
        "LIVEKIT_API_KEY",
        "LIVEKIT_API_SECRET",
        "TWILIO_SIP_TERM_URI",
        "TWILIO_SIP_USERNAME",
        "TWILIO_SIP_PASSWORD",
        "TWILIO_PHONE_NUMBER",
    ]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        print(f"[ERROR] Missing environment variables: {', '.join(missing)}")
        print(
            "\nAdd them to backend/.env.local:\n"
            "  TWILIO_SIP_TERM_URI=mytrunk.pstn.twilio.com\n"
            "  TWILIO_SIP_USERNAME=your-credential-list-username\n"
            "  TWILIO_SIP_PASSWORD=your-credential-list-password\n"
            "  TWILIO_PHONE_NUMBER=+12015551234\n"
        )
        sys.exit(1)

    sip_term_uri = os.environ["TWILIO_SIP_TERM_URI"]
    sip_username = os.environ["TWILIO_SIP_USERNAME"]
    sip_password = os.environ["TWILIO_SIP_PASSWORD"]
    phone_number = os.environ["TWILIO_PHONE_NUMBER"]

    lkapi = api.LiveKitAPI()
    try:
        trunk = SIPOutboundTrunkInfo(
            name="KrishiMitra Outbound Trunk",
            address=sip_term_uri,
            numbers=[phone_number],
            auth_username=sip_username,
            auth_password=sip_password,
        )
        request = CreateSIPOutboundTrunkRequest(trunk=trunk)
        result = await lkapi.sip.create_sip_outbound_trunk(request)
        print("\n✅  Outbound trunk created successfully!")
        print(f"\n   Trunk ID : {result.sip_trunk_id}")
        print(f"   Name     : {result.name}")
        print(f"   Address  : {result.address}")
        print(f"   Numbers  : {result.numbers}")
        print(
            f"\nAdd this to backend/.env.local:\n"
            f"   LIVEKIT_SIP_OUTBOUND_TRUNK_ID={result.sip_trunk_id}\n"
        )
    except Exception as exc:
        print(f"[ERROR] Failed to create outbound trunk: {exc}")
        raise
    finally:
        await lkapi.aclose()


if __name__ == "__main__":
    asyncio.run(main())
