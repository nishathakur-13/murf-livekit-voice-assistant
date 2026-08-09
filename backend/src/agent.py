import logging
import os
from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    RunContext,
    cli,
    function_tool,
    inference,
    tokenize,
    room_io,
)
from livekit.plugins import murf, silero, google, deepgram, noise_cancellation, openai
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from database import delete_user, get_user, init_db, save_user

logger = logging.getLogger("agent")

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env.local"))

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

Keep every response between 1–3 short sentences.

Never speak long paragraphs.

Never use bullet points.

Never use markdown.

Never use emojis.

Pause naturally.

Ask only ONE follow-up question at a time.

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
GUARDRAILS
========================
Never diagnose crop diseases with certainty.

Never recommend pesticide dosage.

Never recommend fertilizer quantity.

Never claim live mandi prices.

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
        Save what you have learned about this caller to the database.
        ONLY call this AFTER the caller has explicitly given consent to be remembered.

        Args:
            name: The caller's name, e.g. "Ramesh".
            language_preference: Their preferred language, e.g. "Hindi", "English", "Hinglish".
            crops: Crops they grow, e.g. "cotton, wheat".
            district: Their district or location, e.g. "Wardha".
            land_size: How much land they farm, e.g. "5 acres".
            irrigation_type: Irrigation method, e.g. "drip", "borewell", "flood".
        """
        logger.info("save_caller_info called for user_id=%s name=%s", self._user_id, name)

        facts: dict = {}
        if crops:
            facts["crops"] = [c.strip() for c in crops.split(",")]
        if district:
            facts["district"] = district
        if land_size:
            facts["land_size"] = land_size
        if irrigation_type:
            facts["irrigation_type"] = irrigation_type

        save_user(
            user_id=self._user_id,
            name=name,
            language_preference=language_preference,
            facts=facts,
        )

        return f"SAVED: Caller info stored successfully for {name or self._user_id}."

    # ------------------------------------------------------------------
    # Tool 3 (advanced): Let the caller wipe their own data
    # ------------------------------------------------------------------
    @function_tool
    async def forget_me(self, context: RunContext, unused: str = "") -> str:
        """
        Permanently delete this caller's record from KrishiMitra's memory.
        Call this when the caller asks to be forgotten or their data deleted.

        Args:
            unused: Ignore this parameter. Always pass an empty string.
        """
        logger.info("forget_me called for user_id=%s", self._user_id)
        deleted = delete_user(self._user_id)
        if deleted:
            return "DELETED: The caller's record has been wiped. Confirm to them that you no longer remember them."
        return "NOT_FOUND: No record existed for this caller anyway."


server = AgentServer()


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session(agent_name="my-agent")
async def my_agent(ctx: JobContext):
    logger.info("========== JOB RECEIVED ==========")
    print("========== JOB RECEIVED ==========")

    try:
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
        import asyncio
        for _ in range(10):
            if ctx.room.remote_participants:
                break
            await asyncio.sleep(0.3)
        user_id = next(iter(ctx.room.remote_participants.values())).identity if ctx.room.remote_participants else "voice_assistant_user_dev_1"
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
                api_key=os.getenv("GROQ_API_KEY"),
                base_url="https://api.groq.com/openai/v1",
            ),
            # Text-to-speech (TTS) is your agent's voice, turning the LLM's text into speech that the user can hear
            # See all available models as well as voice selections at https://docs.livekit.io/agents/models/tts/
            # Nikhil is a male Indian English/Hindi voice from Murf's voice library
            tts=murf.TTS(
                    voice="en-IN-anisha",
                    locale="en-IN",
                    style="Conversational",
                    tokenizer=tokenize.basic.SentenceTokenizer(min_sentence_len=2),
                    text_pacing=True
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
            if district and district != "unknown":
                known_parts.append(f"{district} district")
            land_size = facts.get("land_size")
            if land_size and land_size != "unknown":
                known_parts.append(f"{land_size} zameen")
            irrigation = facts.get("irrigation_type")
            if irrigation and irrigation != "unknown":
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
        await session.say(greeting, allow_interruptions=True)

    except Exception:
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    cli.run_app(server)
