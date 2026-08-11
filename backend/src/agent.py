import asyncio
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from ddgs import DDGS
from dotenv import load_dotenv
from livekit import api, rtc
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    RunContext,
    WorkerOptions,
    cli,
    function_tool,
    room_io,
)
from livekit.plugins import deepgram, murf, noise_cancellation, openai, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from database import delete_user, get_user, init_db, save_user

logger = logging.getLogger("agent")

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env.local"), override=True)

CHAT_TOPICS = ("lk.chat", "lk-chat-topic")
EMPTY_MEMORY_VALUES = {"", "none", "null", "undefined", "unknown", "n/a", "na"}


def _clean_memory_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if cleaned.lower() in EMPTY_MEMORY_VALUES:
        return None
    return cleaned


# Change this prompt to change what your voice agent does.
# See README.md for example prompts (customer support, language tutor, receptionist).
SYSTEM_PROMPT = """
You are KrishiMitra AI, a friendly multilingual voice assistant for Indian farmers.

========================
IDENTITY
========================
You are KrishiMitra AI.

Your job is to help Indian farmers with general farming guidance.

You are polite, patient, trustworthy, and speak like an experienced agriculture advisor.

You are NOT a government officer, agricultural scientist, or weather department.

========================
MEMORY & SAVING INFO
========================
During the conversation, if the caller shares their name, crops, district, land size or irrigation type:
- Ask for consent first: "Kya main yeh jankari yaad rakh sakti hoon taaki agli baar dobara poochna na pade?"
- Only call save_caller_info AFTER they say yes (haan, bilkul, sure, etc.)
- If they say no — do NOT save anything

If the caller gives NEW or UPDATED information (e.g. a different name, new crop, changed district):
- Save it immediately using save_caller_info — it will overwrite the old value
- Confirm: "Maine yaad kar liya."

If the caller says their name is different from what you greeted them with:
- Apologise briefly and save the corrected name: "Oh, maafi chahti hoon! Main update kar leti hoon."
- Call save_caller_info with the corrected name

========================
FORGET ME
========================
If a caller asks you to forget them, call the forget_me tool and confirm:
"Theek hai, maine aapki saari jankari hata di hai."

========================
OBJECTIVES
========================
Your goals are:

1. Help farmers understand common crop and farming problems.

2. Give safe and practical guidance on:
- Crop care
- Irrigation
- Soil health
- Fertilizers (general information only)
- Weather preparedness
- Government agriculture schemes
- Sustainable farming

3. Ask useful follow-up questions before giving advice.

4. If expert help is needed, guide the farmer to the nearest Krishi Vigyan Kendra (KVK) or Agriculture Officer.

========================
LANGUAGE
========================
Always mirror the user's language.

If the user speaks Hindi, reply in natural Indian Hindi.

If the user speaks English, reply in English.

If the user mixes Hindi and English, reply in the same style.

Examples:

User:
"Meri wheat crop me yellow spots aa rahe hain."

Reply:
"Achha, samajh gaya. Yellow spots kai wajah se aa sakte hain. Main exact disease confirm nahi kar sakta. Kya ye poori field me hai ya sirf kuch plants me?"

Do NOT use textbook Hindi.

Avoid words like:

"Avashya"
"Prakar"
"Tathapi"
"Kripaya avlokan karein"

Instead use:

"Thik hai."
"Achha."
"Samajh gaya."
"Batayiye."
"Koi baat nahi."

Speak exactly like an educated Indian talking naturally.

========================
VOICE STYLE
========================
Speak naturally.

Keep every response between 1-3 short sentences.

Never speak long paragraphs.

Never use bullet points.

Never use markdown.

Never use emojis.

Pause naturally.

Ask only ONE follow-up question at a time.

The user must only hear and see farmer-facing answers.

Never mention internal implementation details such as tool names, function names,
GET, POST, API endpoints, request bodies, database, SQL, queries, JSON, code,
logs, or backend/frontend commands.

If a tool is used, do not repeat the tool output. Convert it into a normal spoken
answer for the farmer.

========================
KNOWLEDGE
========================
You can help with:

• Crop care

• Irrigation

• Soil preparation

• Soil health

• Organic farming

• Seasonal farming tips

• Government agriculture schemes

• General weather preparedness

• Water conservation

• Sustainable farming

========================
WEB SEARCH
========================
When the farmer asks about anything that requires current or external data — mandi prices, bhav, rates, weather, government schemes, news, anything — use the search_web tool.

CRITICAL: You MUST speak BEFORE calling the tool. This is mandatory. Say one of these FIRST:
"Ek second, main abhi search karti hoon..."
"Zaroor, dekhti hoon..."
"Haan, main abhi pata karti hoon..."

Then immediately call search_web. Never call the tool silently.

When you get the search results:
- Speak the answer naturally in 1-2 sentences. Do NOT read URLs or source names.
- Always mention how fresh the information is if the result includes a date.
- For mandi/price queries: say "Yeh ek estimate hai, apne najdeeki APMC se confirm zaroor karein."
- For weather: say "Yeh forecast hai, badal sakta hai."

If search_web returns an error or no results, say clearly:
"Abhi mujhe bahar se jaankari nahi mil rahi. Net ya server ki dikkat ho sakti hai. Thodi der mein dobara try karein."

Never invent an answer if search fails. Always admit you could not find it.

========================
GUARDRAILS
========================
Never diagnose crop diseases with certainty.

Never recommend pesticide dosage.

Never recommend fertilizer quantity.

Never invent weather forecasts.

Never guarantee crop yield.

Never pretend to know something you don't.

Never say you are an agriculture officer.

========================
ESCALATION
========================
If the farmer asks something requiring expert inspection, say:

"Main is baat ki pakki pushti nahi kar sakta. Iske liye apne najdeeki Krishi Vigyan Kendra ya Agriculture Officer se salah lena behtar hoga."

========================
PERSONALITY
========================
Be warm.

Be respectful.

Sound encouraging.

Sound like someone from India helping another Indian.

Never sound robotic.

========================
FIRST GREETING (new callers only)
========================
Whenever a NEW caller starts a conversation, say:

"Namaste! Main KrishiMitra AI hu. krishi yojanaon se judi general jankari dene ke liye yahan hoon. Aaj main aapki kis tarah madad kar sakti hoon?"

========================
EXAMPLES
========================

User:
Meri dhan ki fasal peele rang ki ho rahi hai.

Reply:
Achha, samajh gaya. Iski kai wajah ho sakti hain jaise nutrient deficiency ya kisi rog ka shuruaati asar. Kya ye poore khet me hai ya sirf kuch jagah?

User:
Kal baarish hogi?

Reply:
Mere paas real-time weather data nahi hai, isliye main kal ki baarish confirm nahi kar sakta. Agar aap weather forecast batayein, to uske hisaab se main farming advice de sakta hoon.

User:
Kitna pesticide daalu?

Reply:
Main pesticide ki exact quantity recommend nahi kar sakta. Galat matra fasal aur environment dono ko nuksan pahuncha sakti hai. Iske liye Krishi Vigyan Kendra ya Agriculture Officer se salah lena behtar rahega.

Always keep your responses conversational, natural, and easy for farmers to understand.
"""


class Assistant(Agent):
    def __init__(self, user_id: str) -> None:
        super().__init__(instructions=SYSTEM_PROMPT)
        self._user_id = user_id

    # ------------------------------------------------------------------
    # Tool 1: Look up caller at the start of every call
    # ------------------------------------------------------------------
    # Tool 1: Save caller info — only after consent
    # ------------------------------------------------------------------
    @function_tool
    async def save_caller_info(
        self,
        context: RunContext,
        name: str | None,
        language_preference: str | None,
        crops: str | None,
        district: str | None,
        land_size: str | None,
        irrigation_type: str | None,
    ) -> str:
        """
        Save what you have learned about this caller to memory.
        ONLY call this AFTER the caller has explicitly given consent to be remembered.

        Args:
            name: The caller's name, e.g. "Ramesh".
            language_preference: Their preferred language, e.g. "Hindi", "English", "Hinglish".
            crops: Crops they grow, e.g. "cotton, wheat".
            district: Their district or location, e.g. "Wardha".
            land_size: How much land they farm, e.g. "5 acres".
            irrigation_type: Irrigation method, e.g. "drip", "borewell", "flood".
        """
        logger.info(
            "save_caller_info called for user_id=%s name=%s", self._user_id, name
        )

        cleaned_name = _clean_memory_value(name)
        cleaned_language_preference = _clean_memory_value(language_preference)
        cleaned_district = _clean_memory_value(district)
        cleaned_land_size = _clean_memory_value(land_size)
        cleaned_irrigation_type = _clean_memory_value(irrigation_type)

        facts: dict = {}
        if crops:
            cleaned_crops = [
                crop
                for crop in (_clean_memory_value(crop) for crop in crops.split(","))
                if crop
            ]
            if cleaned_crops:
                facts["crops"] = cleaned_crops
        if cleaned_district:
            facts["district"] = cleaned_district
        if cleaned_land_size:
            facts["land_size"] = cleaned_land_size
        if cleaned_irrigation_type:
            facts["irrigation_type"] = cleaned_irrigation_type

        save_user(
            user_id=self._user_id,
            name=cleaned_name,
            language_preference=cleaned_language_preference,
            facts=facts,
        )

        return (
            "Caller info has been remembered. Tell the caller: 'Maine yaad kar liya.'"
        )

    # ------------------------------------------------------------------
    # Tool 3 (advanced): Let the caller wipe their own data
    # ------------------------------------------------------------------
    @function_tool
    async def forget_me(self, context: RunContext, unused: str = "") -> str:
        """
        Permanently delete this caller's saved memory.
        Call this when the caller asks to be forgotten or their data deleted.

        Args:
            unused: Ignore this parameter. Always pass an empty string.
        """
        logger.info("forget_me called for user_id=%s", self._user_id)
        deleted = delete_user(self._user_id)
        if deleted:
            return "The caller's saved memory has been removed. Confirm this in simple words."
        return "No saved memory existed for this caller. Still confirm this in simple words."

    # ------------------------------------------------------------------
    # Tool 4: Web search via DuckDuckGo (free, no API key needed)
    # ------------------------------------------------------------------
    @function_tool
    async def search_web(
        self,
        context: RunContext,
        query: str,
    ) -> str:
        """
        Search the internet using DuckDuckGo to find current, real-world
        information the agent cannot know on its own.

        Call this tool whenever the farmer asks about:
        - Mandi prices, bhav, market rates for any crop
        - Weather forecast for their area
        - Government schemes, PM-Kisan status, subsidies
        - News about farming, crop diseases, pest alerts
        - Anything that requires up-to-date external information

        Before calling this tool, always say out loud to the farmer:
        "Zaroor, main abhi search karti hoon..." so they know you are looking it up.

        Args:
            query: A clear web search phrase in English. Be specific.
                   Examples:
                   "wheat mandi price Wardha Maharashtra today"
                   "PM-Kisan 20th installment date 2025"
                   "cotton price India mandi August 2025"
                   "weather forecast Nashik tomorrow"
        """
        logger.info("search_web called: query=%r user_id=%s", query, self._user_id)

        # --- Auto-enrich query with saved district if it's location-relevant ---
        if any(
            kw in query.lower()
            for kw in ["mandi", "price", "bhav", "weather", "forecast", "rate"]
        ):
            caller = get_user(self._user_id)
            if caller:
                saved_district = caller.get("facts", {}).get("district")
                if (
                    saved_district
                    and saved_district.lower() != "unknown"
                    and saved_district.lower() not in query.lower()
                ):
                    query = f"{query} {saved_district} India"
                    logger.info("Auto-enriched query with district: %s", query)

        # Ensure India-specific results for mandi/price queries
        if (
            any(kw in query.lower() for kw in ["mandi", "bhav", "price", "rate"])
            and "india" not in query.lower()
        ):
            query = f"{query} India"

        # DuckDuckGo search is synchronous — run it in a thread pool
        loop = asyncio.get_event_loop()

        def _do_search() -> list[dict]:
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=4))

        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                results = await asyncio.wait_for(
                    loop.run_in_executor(executor, _do_search),
                    timeout=12,
                )
        except TimeoutError:
            logger.warning("DuckDuckGo search timed out: query=%r", query)
            return (
                "The web search took too long. Tell the farmer clearly: "
                "'Abhi search slow hai, thodi der mein dobara try karein.'"
            )
        except Exception as exc:
            logger.exception("DuckDuckGo search error: %s", exc)
            return (
                "The web search failed. Tell the farmer: "
                "'Abhi mujhe yeh jaankari nahi mil rahi, "
                "apne najdeeki Krishi Vigyan Kendra se poochh sakte hain.'"
            )

        if not results:
            return (
                "No reliable result was found. Tell the farmer: "
                "'Iske baare mein mujhe online koi sahi jaankari nahi mili. "
                "Apne najdeeki APMC ya Krishi Vigyan Kendra se directly poochh sakte hain.'"
            )

        # --- Format top results for the LLM to speak naturally ---
        lines = []
        for r in results[:3]:
            title = r.get("title", "").strip()
            body = r.get("body", "").strip()
            if body:
                snippet = body[:250].rsplit(" ", 1)[0]
                lines.append(f"- {title}: {snippet}")

        formatted = "\n".join(lines)
        logger.info("search_web results (truncated): %s", formatted[:400])
        return (
            f"Search phrase: {query}\nRelevant information:\n{formatted}\n\n"
            "Extract the single most relevant fact and speak it naturally "
            "in 1-2 sentences in the farmer's language. Do NOT mention URLs or source names. "
            "If this is a mandi/price result, end with: 'Yeh ek estimate hai, apne najdeeki "
            "APMC se confirm zaroor karein.' "
            "If this is weather, end with: 'Yeh forecast hai, badal sakta hai.' "
            "If a date is visible in the results, mention it."
        )


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


# ---------------------------------------------------------------------------
# Outbound call helpers
# ---------------------------------------------------------------------------


def _parse_outbound_metadata(ctx: JobContext) -> dict:
    """Parse outbound call metadata from the job.  Returns {} if not present."""
    raw = getattr(ctx.job, "metadata", None) or ""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}


async def _place_outbound_call(ctx: JobContext, meta: dict) -> str | None:
    """
    Place an outbound SIP call using Linphone inline trunk configuration.

    Uses LiveKit's inline trunk config — no stored trunk or Twilio needed.
    Credentials + target SIP address come from the job metadata dispatched
    by outbound_call.py.

    Returns the participant identity on success, None on failure.
    """
    from livekit.api.twirp_client import TwirpError
    from livekit.protocol.sip import (
        CreateSIPParticipantRequest,
        SIPMediaEncryption,
        SIPOutboundConfig,
        SIPTransport,
    )
    from google.protobuf.duration_pb2 import Duration

    sip_address = meta.get("linphone_sip_address", "").strip().removeprefix("sip:")
    username = meta.get("linphone_username", "").strip()
    password = meta.get("linphone_password", "").strip()

    if not sip_address:
        logger.error("linphone_sip_address missing in job metadata — cannot dial")
        ctx.shutdown()
        return None

    # hostname is the domain part (e.g. sip.linphone.org)
    sip_hostname = sip_address.split("@")[-1] if "@" in sip_address else "sip.linphone.org"
    # user part only — LiveKit builds the full INVITE as sip:<sip_user>@<trunk hostname>
    sip_user = sip_address.split("@")[0] if "@" in sip_address else sip_address
    # sip_number = caller-id (From header) — must also be just the username, not a full URI
    sip_from = username if username else sip_user

    logger.info(
        "Placing Linphone outbound call: user=%s trunk=%s from=%s",
        sip_user,
        sip_hostname,
        sip_from,
    )

    try:
        trunk_config = SIPOutboundConfig(
            hostname=sip_hostname,
            auth_username=username,
            auth_password=password,
            transport=SIPTransport.SIP_TRANSPORT_UDP,  # Linphone uses UDP
        )
        request = CreateSIPParticipantRequest(
            trunk=trunk_config,
            sip_number=sip_from,   # caller-id username (no sip: prefix, no @host)
            sip_call_to=sip_user,  # destination username — LiveKit appends @hostname from trunk
            room_name=ctx.room.name,
            participant_identity=sip_address,
            participant_name="Farmer",
            wait_until_answered=True,
            play_dialtone=True,
            ringing_timeout=Duration(seconds=60),  # give 60s to pick up
            # Linphone free tier uses plain RTP — disable SRTP to avoid 488
            media_encryption=SIPMediaEncryption.SIP_MEDIA_ENCRYPT_DISABLE,
        )
        await ctx.api.sip.create_sip_participant(request)
        logger.info("Outbound call answered: %s", sip_address)
        return sip_address

    except TwirpError as exc:
        logger.warning(
            "Outbound call to %s failed: %s (HTTP %s)", sip_address, exc.message, exc.status
        )
        msg = exc.message.lower()
        if "busy" in msg or "decline" in msg or "486" in msg or "603" in msg:
            logger.info("Call outcome: USER_REJECTED")
        elif "timeout" in msg or "unavailable" in msg or "408" in msg or "480" in msg:
            logger.info("Call outcome: NO_ANSWER")
        elif exc.status >= 500:
            logger.info("Call outcome: SIP_TRUNK_FAILURE")
        else:
            logger.info("Call outcome: CALL_FAILED — %s", exc.message)
        ctx.shutdown()
        return None

    except Exception as exc:
        logger.exception(
            "Unexpected error placing outbound call to %s: %s", sip_call_to, exc
        )
        ctx.shutdown()
        return None


def _build_outbound_opening(topic: str) -> str:
    """
    Build the outbound opening statement.
    Rule: first two sentences must cover WHO is calling, WHY, and how to OPT OUT.
    """
    return (
        "Namaste! Main KrishiMitra AI hoon, ek automated farming assistant. "
        f"Main aapko aaj ka farming tip dene ke liye call kar rahi hoon — topic hai: {topic}. "
        "Agar aap yeh call nahi chahte, to bas 'band karo' ya 'stop' bolein "
        "aur main turant call khatam kar dungi. "
        "Kya aap tayaar hain?"
    )


# ---------------------------------------------------------------------------
# Agent entrypoint
# ---------------------------------------------------------------------------


async def my_agent(ctx: JobContext):
    logger.info("========== JOB RECEIVED ==========")
    print("========== JOB RECEIVED ==========")

    try:
        required_env = [
            "LIVEKIT_URL",
            "LIVEKIT_API_KEY",
            "LIVEKIT_API_SECRET",
            "MURF_API_KEY",
            "DEEPGRAM_API_KEY",
            "GROQ_API_KEY",
        ]
        missing_env = [key for key in required_env if not os.environ.get(key)]
        if missing_env:
            raise RuntimeError(
                "Missing backend environment variables: " + ", ".join(missing_env)
            )

        # Initialise the database (creates table if it doesn't exist yet)
        init_db()

        ctx.log_context_fields = {"room": ctx.room.name}

        # ---------------------------------------------------------------
        # Detect outbound call from job metadata
        # ---------------------------------------------------------------
        meta = _parse_outbound_metadata(ctx)
        call_topic: str = meta.get("topic", "aaj ka farming tip")
        # Outbound mode when linphone_sip_address is present in metadata
        sip_address: str | None = meta.get("linphone_sip_address") or None
        is_outbound: bool = bool(sip_address)

        if is_outbound:
            logger.info("OUTBOUND MODE: sip=%s topic=%s", sip_address, call_topic)
        else:
            logger.info("INBOUND/WEB MODE")

        # ---------------------------------------------------------------
        # Connect to the room first — required before placing SIP calls
        # ---------------------------------------------------------------
        await ctx.connect()
        print("CONNECTED")

        # ---------------------------------------------------------------
        # Place the outbound SIP call (if outbound mode)
        # ---------------------------------------------------------------
        if is_outbound:
            participant_identity = await _place_outbound_call(ctx, meta)
            if not participant_identity:
                # Failure already logged and ctx.shutdown() called inside helper
                return

            # Wait for the SIP participant to fully join the room
            try:
                sip_participant = await asyncio.wait_for(
                    ctx.wait_for_participant(identity=participant_identity),
                    timeout=30.0,
                )
                logger.info(
                    "SIP participant joined: identity=%s", sip_participant.identity
                )
            except asyncio.TimeoutError:
                logger.error(
                    "Timed out waiting for SIP participant %s to join",
                    participant_identity,
                )
                ctx.shutdown()
                return

            user_id = participant_identity

        else:
            # Inbound / web mode — resolve user_id from participant identity
            for _ in range(10):
                if ctx.room.remote_participants:
                    break
                await asyncio.sleep(0.3)
            user_id = (
                next(iter(ctx.room.remote_participants.values())).identity
                if ctx.room.remote_participants
                else "voice_assistant_user_dev_1"
            )

        logger.info("user_id resolved to: %s", user_id)

        # ---------------------------------------------------------------
        # Build voice pipeline (same for both inbound and outbound)
        # ---------------------------------------------------------------
        session = AgentSession(
            stt=deepgram.STT(model="nova-3", language="multi"),
            llm=openai.LLM(
                model="llama-3.3-70b-versatile",
                api_key=os.environ.get("GROQ_API_KEY"),
                base_url="https://api.groq.com/openai/v1",
            ),
            tts=murf.TTS(
                voice="en-IN-anisha",
                locale="en-IN",
                style="Conversation",
                streaming=False,
                verbose=True,
            ),
            turn_detection=MultilingualModel(),
            vad=ctx.proc.userdata["vad"],
            preemptive_generation=True,
        )

        # ---------------------------------------------------------------
        # Build greeting
        # ---------------------------------------------------------------
        if is_outbound:
            # Outbound: clear identity + purpose + opt-out in first two sentences
            greeting = _build_outbound_opening(call_topic)
            logger.info("Outbound opening prepared for sip=%s", sip_address)
        else:
            # Inbound / web: use returning-caller personalisation
            caller = get_user(user_id)
            if caller:
                name = caller.get("name") or "aap"
                facts = caller.get("facts", {})
                known_parts = []
                crops = facts.get("crops", [])
                if crops:
                    known_parts.append(f"{', '.join(crops)} ki kheti")
                district = facts.get("district")
                if _clean_memory_value(district):
                    known_parts.append(f"{district} district")
                land_size = facts.get("land_size")
                if _clean_memory_value(land_size):
                    known_parts.append(f"{land_size} zameen")
                irrigation = facts.get("irrigation_type")
                if _clean_memory_value(irrigation):
                    known_parts.append(f"{irrigation} sinchaai")

                if known_parts:
                    context_str = " aur ".join(known_parts)
                    greeting = f"Namaste {name}! Pichli baar aapne {context_str} ke baare mein bataya tha. Aaj kya sawaal hai?"
                else:
                    greeting = f"Namaste {name}! Aap wapas aaye, achha laga. Aaj main aapki kaise madad kar sakti hoon?"
                logger.info("Returning caller: %s, known facts: %s", user_id, facts)
            else:
                greeting = "Namaste! Main KrishiMitra AI hoon. Main kheti, crops, seechaai, mitti ki sehat aur sarkari krishi yojanaon se judi jankari dene ke liye yahan hoon. Aaj main aapki kaise madad kar sakti hoon?"
                logger.info("New caller: %s", user_id)

        # ---------------------------------------------------------------
        # Handle mid-call disconnections (outbound-specific logging)
        # ---------------------------------------------------------------
        if is_outbound:
            _outbound_identity = participant_identity  # captured for the closure

            @ctx.room.on("participant_disconnected")
            def on_participant_disconnected(participant: rtc.RemoteParticipant):
                if participant.identity != _outbound_identity:
                    return
                reason = participant.disconnect_reason
                if reason == rtc.DisconnectReason.CLIENT_INITIATED:
                    logger.info(
                        "Call outcome: COMPLETED — caller %s hung up after answering",
                        _outbound_identity,
                    )
                elif reason == rtc.DisconnectReason.USER_REJECTED:
                    logger.info(
                        "Call outcome: REJECTED — caller %s declined",
                        _outbound_identity,
                    )
                elif reason == rtc.DisconnectReason.USER_UNAVAILABLE:
                    logger.info(
                        "Call outcome: UNAVAILABLE — caller %s unreachable",
                        _outbound_identity,
                    )
                elif reason == rtc.DisconnectReason.SIP_TRUNK_FAILURE:
                    logger.error(
                        "Call outcome: TRUNK_FAILURE — SIP error for %s",
                        _outbound_identity,
                    )
                else:
                    logger.info(
                        "Call outcome: DISCONNECTED (%s) — caller %s",
                        reason,
                        _outbound_identity,
                    )

        # ---------------------------------------------------------------
        # Register chat stream handler (inbound only — phone callers use voice)
        # ---------------------------------------------------------------
        if not is_outbound:

            async def handle_chat_message(
                reader: rtc.TextStreamReader, participant_info
            ) -> None:
                message = (await reader.read_all()).strip()
                if not message:
                    return
                logger.info(
                    "chat text received from participant=%s: %r",
                    getattr(participant_info, "identity", "unknown"),
                    message,
                )
                await session.interrupt()
                session.generate_reply(user_input=message, input_modality="text")

            for topic in CHAT_TOPICS:
                ctx.room.register_text_stream_handler(topic, handle_chat_message)

        # ---------------------------------------------------------------
        # Start session
        # ---------------------------------------------------------------
        await session.start(
            agent=Assistant(user_id=user_id),
            room=ctx.room,
            room_options=room_io.RoomOptions(
                audio_input=room_io.AudioInputOptions(
                    noise_cancellation=lambda params: (
                        noise_cancellation.BVCTelephony()
                        if params.participant.kind
                        == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                        else noise_cancellation.BVC()
                    ),
                ),
            ),
        )
        print("SESSION STARTED")

        # Speak greeting immediately after session starts.
        # For outbound: the call is already answered before we reach here, so
        # the farmer hears the opening the moment we start speaking.
        session.say(greeting, allow_interruptions=True)

    except Exception:
        import traceback

        traceback.print_exc()
        raise


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=my_agent,
            prewarm_fnc=prewarm,
            agent_name="my-agent",
        )
    )
