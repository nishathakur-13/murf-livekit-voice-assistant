import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from ddgs import DDGS
from dotenv import load_dotenv
from livekit import rtc
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

        # Logging setup
        # Add any other context you want in all log entries here
        ctx.log_context_fields = {
            "room": ctx.room.name,
        }

        # Join the room and connect to the user FIRST
        await ctx.connect()
        print("CONNECTED")

        # Resolve stable user_id from participant identity.
        # remote_participants may already be populated after connect().
        # If not, wait briefly for the participant to join.
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

        # Set up a voice AI pipeline using Murf Falcon, Gemini, Deepgram, and the LiveKit turn detector
        session = AgentSession(
            # Speech-to-text (STT) is your agent's ears, turning the user's speech into text that the LLM can understand
            # See all available models at https://docs.livekit.io/agents/models/stt/
            # "multi" enables automatic language detection so Hindi/Hinglish is picked up correctly
            stt=deepgram.STT(model="nova-3", language="multi"),
            # A Large Language Model (LLM) is your agent's brain, processing user input and generating a response
            # See all available models at https://docs.livekit.io/agents/models/llm/
            llm=openai.LLM(
                model="llama-3.3-70b-versatile",
                api_key=os.environ.get("GROQ_API_KEY"),
                base_url="https://api.groq.com/openai/v1",
            ),
            # Text-to-speech (TTS) is your agent's voice, turning the LLM's text into speech that the user can hear
            # See all available models as well as voice selections at https://docs.livekit.io/agents/models/tts/
            # Anisha is an Indian English/Hindi-friendly voice from Murf's voice library
            tts=murf.TTS(
                voice="en-IN-anisha",
                locale="en-IN",
                style="Conversation",
                streaming=False,
                verbose=True,
            ),
            # VAD and turn detection are used to determine when the user is speaking and when the agent should respond
            # See more at https://docs.livekit.io/agents/build/turns
            turn_detection=MultilingualModel(),
            vad=ctx.proc.userdata["vad"],
            # allow the LLM to generate a response while waiting for the end of turn
            # See more at https://docs.livekit.io/agents/build/audio/#preemptive-generation
            preemptive_generation=True,
        )

        # To use a realtime model instead of a voice pipeline, use the following session setup instead.
        # (Note: This is for the OpenAI Realtime API. For other providers, see https://docs.livekit.io/agents/models/realtime/))
        # 1. Install livekit-agents[openai]
        # 2. Set OPENAI_API_KEY in .env.local
        # 3. Add `from livekit.plugins import openai` to the top of this file
        # 4. Use the following session setup instead of the version above
        # session = AgentSession(
        #     llm=openai.realtime.RealtimeModel(voice="marin")
        # )

        # # Add a virtual avatar to the session, if desired
        # # For other providers, see https://docs.livekit.io/agents/models/avatar/
        # avatar = hedra.AvatarSession(
        #   avatar_id="...",  # See https://docs.livekit.io/agents/models/avatar/plugins/hedra
        # )
        # # Start the avatar and wait for it to join
        # await avatar.start(session, room=ctx.room)

        # Look up caller in DB BEFORE starting session.
        # Greeting is injected by code — not left to LLM tool calling.
        caller = get_user(user_id)
        if caller:
            name = caller.get("name") or "aap"
            facts = caller.get("facts", {})

            # Build a natural summary of what we know about them
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

        # Start the session
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

        # Speak greeting immediately — no silence, no waiting for LLM
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
