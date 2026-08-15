import asyncio
import json
import logging
import os
import re as _re
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
from livekit.plugins import deepgram, google, murf, noise_cancellation, openai, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from database import delete_user, get_user, init_db, save_user
from escalation_db import create_escalation as db_create_escalation, get_escalation
from discord_notify import send_escalation as discord_send_escalation
from analytics_db import (
    init_analytics,
    record_call_start,
    record_call_end,
    mark_call_escalated,
)

logger = logging.getLogger("agent")

# Tool names that should never appear in spoken TTS output
_TOOL_NAME_PATTERN = _re.compile(
    r"^(transfer_to_crop_specialist|search_web|create_escalation|save_caller_info|forget_me)\b",
)
_SPEAKER_PREFIX_PATTERN = _re.compile(r"^\s*(Anisha|Arjun)\s*[-:]\s*", _re.I)


async def _filter_tool_leakage(text):
    """
    Async generator that strips leaked tool-call artifacts from the LLM text stream
    before it reaches TTS.

    Filters out chunks/lines that look like:
      - A tool name (e.g. "transfer_to_crop_specialist")
      - Raw JSON (starts with { or [)
      - Inline JSON fragments embedded in a line
    """
    buffer = ""
    async for chunk in text:
        buffer += chunk
        # Process complete lines; hold back the last partial line
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            cleaned = _clean_tts_line(line)
            if cleaned:
                yield cleaned + "\n"
    # Flush the remaining buffer
    if buffer:
        cleaned = _clean_tts_line(buffer)
        if cleaned:
            yield cleaned


def _clean_tts_line(line: str) -> str:
    """
    Return the line with tool-call artifacts removed, or empty string if the
    whole line should be suppressed.
    """
    stripped = line.strip()
    if not stripped:
        return line  # preserve blank lines/whitespace

    tool_check = _SPEAKER_PREFIX_PATTERN.sub("", stripped).strip()

    # Suppress lines that are pure JSON objects or arrays
    if tool_check.startswith(("{", "[")):
        return ""

    # Suppress lines that start with a known tool name
    if _TOOL_NAME_PATTERN.match(tool_check):
        return ""

    # Strip inline JSON fragments (e.g. '{"symptom_summary": "..."}') from the end of a line
    cleaned = _re.sub(r'\s*\{[^}]*\}\s*$', "", line).rstrip()
    return cleaned


load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env.local"), override=True)

CHAT_TOPICS = ("lk.chat", "lk-chat-topic")
EMPTY_MEMORY_VALUES = {"", "none", "null", "undefined", "unknown", "n/a", "na"}

SYMPTOM_KEYWORDS = [
    # yellowing / color changes
    "peele",
    "peel",
    "yellow",
    "pila",
    "pile",
    "पीले",
    "पीला",
    "पीली",
    "पीलेपन",
    # spots / marks
    "dhabbe",
    "dhabb",
    "daag",
    "spot",
    "spots",
    "धब्बे",
    "दाग",
    # mold / powder
    "safed",
    "kaala",
    "black",
    "white",
    "powder",
    "mold",
    "mildew",
    "सफेद",
    "काला",
    "पाउडर",
    "फफूंदी",
    # wilting / dying
    "mur",
    "sukh",
    "wilt",
    "dying",
    "mar",
    "मुरझ",
    "सूख",
    "मर",
    # insects / holes
    "kide",
    "kida",
    "insect",
    "pest",
    "hole",
    "holes",
    "कीड़े",
    "कीड़ा",
    "कीड़ा",
    "कीट",
    "छेद",
    # rot
    "gal",
    "rot",
    "गल",
    "सड़",
    # leaf / stem / fruit symptoms
    "patte",
    "patta",
    "leaf",
    "leaves",
    "stem",
    "fruit",
    "पत्ते",
    "पत्ता",
    "पत्ती",
    "तना",
    "फल",
    # blight / disease
    "blight",
    "rust",
    "lesion",
    "रोग",
]


def _has_crop_symptoms(text: str) -> bool:
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in SYMPTOM_KEYWORDS)


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

## IDENTITY
Help farmers with crop care, irrigation, soil health, fertilizers (general only), weather preparedness, and government schemes. You are NOT a government officer or scientist.

## LANGUAGE & STYLE
- Mirror the user's language (Hindi/English/Hinglish).
- Speak naturally like an educated Indian. Use: "Achha.", "Samajh gaya.", "Batayiye.", "Theek hai."
- Avoid textbook Hindi words like "Avashya", "Prakar", "Tathapi".
- Keep every response to 1-3 short sentences. No bullet points, no markdown, no emojis.
- Ask only ONE follow-up question at a time.
- Never mention tool names, APIs, database, or backend details.

## MEMORY
If caller shares name, crops, district, land size, or irrigation type:
- Ask consent first: "Kya main yeh yaad rakh sakti hoon?"
- Only call save_caller_info AFTER explicit yes.
- NEVER invent or assume a caller's name. Only use name if they told you themselves in this conversation.
- If they say forget me → call forget_me tool.

## WEB SEARCH — STRICT RULES

You have a search_web tool. USE IT VERY RARELY. Default answer is always from your own knowledge.

ONLY call search_web when the user explicitly asks for ONE of these 4 things:
1. "aaj ka bhav" / mandi price for a specific crop right now
2. Weather forecast for a specific city/village today or tomorrow
3. PM-Kisan installment date or a specific government scheme benefit amount
4. An active pest or disease outbreak alert in a specific region

NEVER call search_web for:
- How to grow a crop, crop care, sowing time, harvesting — answer from your knowledge
- Irrigation methods, drip vs flood, borewell — answer from your knowledge
- Soil health, fertilizer types, NPK — answer from your knowledge
- General farming tips of any kind — answer from your knowledge
- Any question where you already know the answer — answer from your knowledge

If the user asks "gehu ki kheti kaise karen" → answer directly, DO NOT search.
If the user asks "kaunsi khad daalen" → answer directly, DO NOT search.
If the user asks "aaj gehu ka bhav kya hai Wardha mein" → then you may search.

When you do search, call search_web silently — do NOT say anything before calling the tool. After the tool returns, speak the result in 1-2 sentences only. Never read URLs.

## GUARDRAILS
Never diagnose diseases with certainty. Never give pesticide/fertilizer doses. Never invent forecasts.

## ESCALATION
Escalate ONLY for a serious crop emergency happening RIGHT NOW, or a farmer in genuine distress (flood, total crop failure, financial crisis, suicidal thoughts). Normal questions like mandi price or weather do NOT need escalation.

When you detect an emergency, first empathize briefly and ask permission — say something like "Yeh sunke dukh hua. Kya main aapki baat ek krishi expert tak pahuncha sakti hoon?" Then wait silently for their reply.

If they say no or hesitate, say "Theek hai, koi baat nahi" and continue helping normally. Do NOT call create_escalation.

If they say yes, ask for their name — "Aapka naam kya hai?" — and wait for the answer. Then ask how to reach them — "Phone call ya WhatsApp?" — and wait again. Only after you have their reply should you call create_escalation.

For caller_name, use only the personal name the farmer said out loud. Never use a city, village, district, or anything from the situation summary. If they skipped giving their name, pass null.

After the tool returns a reference_id, tell them: "Theek hai, aapki jankari register ho chuki hai. Aapka reference number hai [reference_id]. Expert 24 ghante mein sampark karenge."

## CROP DISEASE / PEST SPECIALIST HANDOFF
You have access to a Fasal Visheshagya (Crop Disease Specialist) named Arjun.
Call transfer_to_crop_specialist ONLY when the farmer describes VISIBLE SYMPTOMS on a crop — for example:
- Yellowing, browning, or spotted leaves
- White powder or black mold on leaves/stems
- Insects, larvae, or holes on the plant
- Wilting, rotting, or dying plants
- Unusual growth patterns that suggest infection or pest attack

DO NOT transfer for:
- General crop care questions (sowing time, irrigation, harvesting) — answer yourself
- Fertilizer and soil questions — answer yourself
- Mandi price, weather, government schemes — answer yourself (or use search_web)
- Any question you can answer from your own knowledge

When you detect visible crop symptoms, call transfer_to_crop_specialist IMMEDIATELY and SILENTLY.
Do NOT ask the farmer for permission. Do NOT say "Kya main Arjun se jodun?" or anything similar.
The tool itself will announce the handoff. Just call the tool.

CRITICAL — TOOL CALL RULES (follow exactly, no exceptions):
- When calling ANY tool, output ZERO text before or alongside the tool call.
- Do NOT say "Ek second", "Wait", "Please hold", "transfer_to_crop_specialist", or ANY words.
- Do NOT narrate, describe, or repeat the tool name or its arguments.
- Do NOT output the JSON arguments of a tool call as speech.
- Simply call the tool silently. The tool itself speaks to the farmer.
- If you output text at the same time as a tool call, you are making an error.

## GREETING
New caller: "Namaste! Main KrishiMitra AI hoon. Aaj aapki kaise madad kar sakti hoon?"
"""

# -------------------------------------------------------------------------
# Crop Disease Specialist — a focused specialist agent for Day 9 handoff
# -------------------------------------------------------------------------
CROP_SPECIALIST_PROMPT = """
You are Arjun, a Fasal Visheshagya (Crop Disease and Pest Specialist) at KrishiMitra AI.

## YOUR JOB
You have ONE focused job: help farmers identify crop diseases and pest infestations, and give practical first-response advice.

## WHAT YOU HANDLE
- Identifying diseases from visible symptoms (yellowing, spots, mold, wilting, rot, blight)
- Identifying pest damage (insect holes, larvae, webbing, stem boring)
- Recommending whether to use neem-based or other bio-pesticides (mention type, NOT exact doses)
- Advising on immediate containment steps (remove infected leaves, isolate plants, improve drainage)
- Telling the farmer whether to consult a local Krishi Vigyan Kendra for confirmation

## WHAT YOU DO NOT HANDLE
- Mandi prices, weather, government schemes → tell the farmer to ask KrishiMitra main assistant
- Sowing time, irrigation, fertilizer dosage → outside your scope
- Financial crisis, flood, severe distress → outside your scope

## LANGUAGE & STYLE
- Mirror the farmer's language (Hindi/English/Hinglish).
- Be direct and practical, like a knowledgeable elder brother who knows farming.
- Keep every answer to 1-4 sentences. No bullet points, no markdown, no emojis.
- Ask one focused question at a time to narrow down the diagnosis.
- Use: "Samjha.", "Dekho,", "Achha,", "Yeh ho sakta hai..."
- NEVER give exact chemical doses. Say "thoda" or recommend visiting a dealer.
- If unsure, say: "Bilkul pakka kehna mushkil hai bina dekhe, lekin..." and give the most likely answer.

## DIAGNOSIS APPROACH
1. First confirm which crop and which part is affected (leaf, stem, root, fruit).
2. Ask about the symptom color, pattern, and when it started.
3. Give 1-2 most likely diagnoses with brief explanation.
4. Give one practical first step the farmer can take TODAY.
5. If serious, recommend: "Apne najdeeki Krishi Vigyan Kendra se ek baar zaroor dikhayein."

## GUARDRAILS
- Never guarantee a diagnosis. Always say it is likely, not certain.
- Never recommend specific pesticide brand names.
- Never invent statistics or research numbers.
"""


# -------------------------------------------------------------------------
# Day 9 — Crop Disease Specialist Agent
# -------------------------------------------------------------------------


class CropSpecialist(Agent):
    """Focused specialist for crop disease and pest identification."""

    def __init__(self, chat_ctx=None) -> None:
        super().__init__(
            instructions=CROP_SPECIALIST_PROMPT,
            chat_ctx=chat_ctx,
            tts=murf.TTS(
                voice="en-IN-samar",
                locale="en-IN",
                style="Conversation",
                streaming=False,
                verbose=True,
            ),
        )

    async def on_enter(self) -> None:
        """Rename the agent to Arjun in the room and greet the farmer."""
        try:
            await self.session.room.local_participant.set_name("Arjun")
            await self.session.room.local_participant.set_attributes({"speaker": "Arjun"})
            # Send an explicit data message so the frontend knows Arjun has taken over.
            # This is more reliable than relying on set_name propagation timing.
            await self.session.room.local_participant.publish_data(
                b'{"type":"speaker_change","name":"Arjun"}',
                reliable=True,
                topic="speaker",
            )
        except Exception as e:
            logger.warning("on_enter setup error: %s", e)

        await self.session.say(
            "Namaste! Main Arjun hoon, Fasal Visheshagya. "
            "Aap mujhe batayein — kaunsi fasal hai aur kya lakshan dikh rahe hain?",
            allow_interruptions=False,
        )

    async def transcription_node(self, text, model_settings):
        """Prepend 'Arjun - ' to every message in the transcript so the
        frontend chat always shows the correct speaker name."""
        prefix_sent = False

        async def _prefixed():
            nonlocal prefix_sent
            async for chunk in text:
                if not prefix_sent:
                    yield "Arjun - " + chunk
                    prefix_sent = True
                else:
                    yield chunk

        return Agent.default.transcription_node(self, _prefixed(), model_settings)

    def tts_node(self, text, model_settings):
        """Override to strip any leaked tool-call text before it reaches TTS."""
        return Agent.default.tts_node(self, _filter_tool_leakage(text), model_settings)


class Assistant(Agent):
    def __init__(self, user_id: str) -> None:
        super().__init__(instructions=SYSTEM_PROMPT)
        self._user_id = user_id

    async def on_user_turn_completed(
        self, turn_ctx, new_message
    ) -> None:
        """
        Before sending to LLM: if the user's message contains visible crop symptom keywords,
        force tool_choice so the LLM MUST call transfer_to_crop_specialist immediately
        instead of asking permission or generating any text first.
        """
        text = ""
        try:
            if hasattr(new_message, "content"):
                for part in new_message.content:
                    if isinstance(part, str):
                        text += part
                    elif hasattr(part, "text"):
                        text += part.text
        except Exception:
            pass

        if _has_crop_symptoms(text):
            logger.info(
                "Symptom keywords detected in user turn — injecting tool_choice=required hint. user=%s text=%r",
                self._user_id,
                text[:120],
            )
            # Append a system reminder so even a weak LLM knows what to do
            try:
                turn_ctx.append(
                    role="system",
                    text=(
                        "SYSTEM OVERRIDE: The farmer just described visible crop symptoms. "
                        "You MUST call transfer_to_crop_specialist RIGHT NOW. "
                        "Do NOT output any text. Do NOT ask permission. Just call the tool."
                    ),
                )
            except Exception as e:
                logger.warning("Could not inject system override: %s", e)

    def tts_node(self, text, model_settings):
        """Override to strip any leaked tool-call text before it reaches TTS."""
        return Agent.default.tts_node(self, _filter_tool_leakage(text), model_settings)

    async def transcription_node(self, text, model_settings):
        """Prepend 'Anisha - ' to every transcript message for the frontend chat."""
        prefix_sent = False

        async def _prefixed():
            nonlocal prefix_sent
            async for chunk in text:
                if not prefix_sent:
                    yield "Anisha - " + chunk
                    prefix_sent = True
                else:
                    yield chunk

        return Agent.default.transcription_node(self, _prefixed(), model_settings)

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
    # Tool: Handoff to Crop Disease Specialist (Day 9)
    # ------------------------------------------------------------------
    @function_tool
    async def transfer_to_crop_specialist(
        self,
        context: RunContext,
        symptom_summary: str,
    ) -> tuple:
        """
        Transfer the farmer to Arjun, the Fasal Visheshagya (Crop Disease and Pest Specialist).

        CALL THIS TOOL ONLY when the farmer describes VISIBLE SYMPTOMS on a crop:
        - Yellowing, browning, or spotted leaves
        - White powder, black mold, or rust on leaves or stems
        - Insects, larvae, holes, or webbing on the plant
        - Wilting, stem rot, root rot, or dying plants
        - Unusual lesions, blights, or discolouration suggesting disease or pest attack

        DO NOT call this tool for:
        - General crop care, sowing, or irrigation questions
        - Fertilizer or soil health questions
        - Mandi prices, weather, or government schemes
        - Any question you can answer yourself from knowledge

        Args:
            symptom_summary: A brief description of the crop symptoms the farmer described
                             (e.g. "tamatar ke patte peele pad rahe hain, kale dhabbe hain").
        """
        logger.info(
            "Handoff to CropSpecialist: user=%s symptoms=%r",
            self._user_id,
            symptom_summary,
        )
        # Announce the handoff to the farmer before switching agents
        await self.session.say(
            "Aapki fasal mein jo lakshan hain, uske liye main aapko hamare Fasal Visheshagya Arjun se jodti hoon.",
            allow_interruptions=False,
        )
        # Pass conversation history (without main-agent instructions) so the
        # specialist immediately understands what the farmer described.
        specialist = CropSpecialist(
            chat_ctx=self.chat_ctx.copy(exclude_instructions=True)
        )
        return specialist, "Connecting you to our Crop Disease Specialist Arjun."

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
        Search the internet. CALL THIS TOOL VERY RARELY.

        ALLOWED — only these 4 cases:
        1. Mandi/bhav: user asks today's market price for a specific crop
        2. Weather: user asks today's or tomorrow's forecast for a specific place
        3. Govt scheme: user asks PM-Kisan installment date or a specific scheme benefit
        4. Outbreak alert: user asks about an active pest or disease in a region

        FORBIDDEN — never call this for:
        - Crop care, how to grow crops, sowing/harvesting advice → answer from knowledge
        - Irrigation, soil health, fertilizers, NPK, farming tips → answer from knowledge
        - Any general agriculture question → answer from knowledge
        - Anything you already know → answer from knowledge

        If in doubt, answer directly without calling this tool.

        Args:
            query: Specific English search phrase, e.g. "wheat mandi price Wardha today"
        """
        logger.info("search_web called: query=%r user_id=%s", query, self._user_id)

        # Acknowledge the search so the farmer doesn't hear silence
        await self.session.say("Ek second...", allow_interruptions=False)

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

    # ------------------------------------------------------------------
    # Tool 5: Create a human escalation request (Day 7)
    # ------------------------------------------------------------------
    @function_tool
    async def create_escalation(
        self,
        context: RunContext,
        situation_type: str,
        summary: str,
        urgency: str,
        language: str,
        follow_up_method: str,
        what_agent_tried: str,
        caller_name: str | None = None,
    ) -> str:
        """
        Create a human escalation request when the farmer faces a SERIOUS crisis
        that requires expert human intervention.

        *** STRICT RULES — violating these is an error: ***
        1. ONLY call this tool AFTER farmer said YES to permission AND you have asked for their name and contact method.
        2. caller_name MUST be the farmer's personal name as they stated it (e.g. "Ramesh", "Sunita").
           NEVER use a city name, district, location, or anything from the summary as caller_name.
           NEVER invent or guess. If farmer did not give their name, pass null.

        Args:
            situation_type: One of "crop_emergency" or "farmer_crisis"
            summary: A concise 2-3 sentence description of what happened.
            urgency: One of "low", "medium", "high", "emergency"
            language: Farmer's language, e.g. "Hindi", "Hinglish", "English"
            follow_up_method: How they prefer to be contacted, e.g. "phone call", "WhatsApp"
            what_agent_tried: What you already told or tried before escalating
            caller_name: Farmer's personal name ONLY if they said it themselves. Otherwise null.
        """
        logger.info(
            "create_escalation called: user=%s situation=%s urgency=%s",
            self._user_id,
            situation_type,
            urgency,
        )

        # Speak immediately so farmer knows the agent is working
        await context.session.say(
            "Theek hai, main abhi aapki request register kar rahi hoon, ek second...",
            allow_interruptions=False,
        )

        # Sanitize: strip any digits that look like sensitive data (OTP, PIN)
        import re

        def _strip_sensitive(text: str) -> str:
            # Remove sequences that look like OTPs, PINs, or account numbers
            text = re.sub(r"\b\d{4,16}\b", "[REDACTED]", text)
            return text.strip()

        safe_summary = _strip_sensitive(summary)
        safe_tried = _strip_sensitive(what_agent_tried)

        # Auto-fill caller_name from saved memory if LLM didn't provide it
        resolved_name = caller_name
        if not resolved_name or resolved_name.strip().lower() in (
            "",
            "unknown",
            "none",
        ):
            saved = get_user(self._user_id)
            if saved and saved.get("name"):
                resolved_name = saved["name"]
                logger.info("Auto-resolved caller_name from DB: %s", resolved_name)

        # Create the escalation record in JSON DB
        reference_id = db_create_escalation(
            user_id=self._user_id,
            caller_name=resolved_name,
            situation_type=situation_type,
            summary=safe_summary,
            urgency=urgency,
            language=language,
            follow_up_method=follow_up_method,
            what_agent_tried=safe_tried,
        )

        # Retrieve the full record to send to Discord
        record = get_escalation(reference_id)
        if record:
            # Fire-and-forget — don't block the voice response
            loop = asyncio.get_event_loop()

            def _send_discord():
                discord_send_escalation(record)

            loop.run_in_executor(None, _send_discord)

        logger.info("Escalation created: %s", reference_id)
        return (
            f"Escalation created successfully. Reference ID: {reference_id}. "
            f"Now say this to the farmer: 'Theek hai, aapki jankari register ho chuki hai. "
            f"Aapka reference number hai {reference_id}. "
            f"Ek krishi expert 24 ghante ke andar aapse sampark karenge.' "
            f"Do NOT make up any other reference ID. Use exactly: {reference_id}."
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
    sip_hostname = (
        sip_address.split("@")[-1] if "@" in sip_address else "sip.linphone.org"
    )
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
            sip_number=sip_from,  # caller-id username (no sip: prefix, no @host)
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
            "Outbound call to %s failed: %s (HTTP %s)",
            sip_address,
            exc.message,
            exc.status,
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
        init_analytics()

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
        # Record call start in analytics
        # ---------------------------------------------------------------
        session_id = ctx.room.name
        channel = "sip" if is_outbound else "web"
        record_call_start(session_id, user_id, channel=channel)
        logger.info(
            "Analytics: call started session=%s channel=%s", session_id, channel
        )

        # Track per-session state for outcome detection
        _call_had_response = False  # True once the agent has spoken at least once
        _call_escalated = False  # True if create_escalation was called this session
        _call_language = None  # Will be updated from LLM response metadata

        # ---------------------------------------------------------------
        # Build voice pipeline (same for both inbound and outbound)
        # ---------------------------------------------------------------
        session = AgentSession(
            stt=deepgram.STT(model="nova-3", language="multi"),
            llm=openai.LLM(
                model="llama-3.1-8b-instant",
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
            min_endpointing_delay=0.2,
            max_endpointing_delay=4.0,
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
                # Only interrupt if the agent is currently speaking/generating
                # — calling interrupt() when idle can leave the pipeline stuck
                try:
                    session.interrupt()
                except Exception:
                    pass

                if _has_crop_symptoms(message):
                    logger.info(
                        "Direct chat handoff to CropSpecialist: user=%s text=%r",
                        user_id,
                        message[:120],
                    )
                    await session.say(
                        "Aapki fasal mein jo lakshan hain, uske liye main aapko hamare Fasal Visheshagya Arjun se jodti hoon.",
                        allow_interruptions=False,
                    )
                    session.update_agent(
                        CropSpecialist(
                            chat_ctx=agent_instance.chat_ctx.copy(
                                exclude_instructions=True
                            )
                        )
                    )
                    return

                session.generate_reply(user_input=message, input_modality="text")

        # ---------------------------------------------------------------
        # Start session
        # ---------------------------------------------------------------
        agent_instance = Assistant(user_id=user_id)
        await session.start(
            agent=agent_instance,
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

        # Set the agent's display name to Anisha so chat transcript shows the right label
        try:
            await ctx.room.local_participant.set_name("Anisha")
            await ctx.room.local_participant.set_attributes({"speaker": "Anisha"})
        except Exception:
            pass

        # Re-register chat handler AFTER session.start() so our handler wins
        # over the SDK's default (which drops messages when text_input_cb is None).
        if not is_outbound:
            for topic in CHAT_TOPICS:
                try:
                    ctx.room.unregister_text_stream_handler(topic)
                except Exception:
                    pass
            for topic in CHAT_TOPICS:
                ctx.room.register_text_stream_handler(topic, handle_chat_message)

        # ---------------------------------------------------------------
        # Analytics: track agent speech to know if farmer got a response
        # ---------------------------------------------------------------
        @session.on("agent_state_changed")
        def _on_agent_state(ev=None):
            nonlocal _call_had_response
            # Agent entered "speaking" state = farmer is receiving a response
            new_state = getattr(ev, "new_state", None)
            if new_state == "speaking":
                _call_had_response = True

        # ---------------------------------------------------------------
        # Analytics: detect when a participant disconnects / room closes
        # ---------------------------------------------------------------
        @ctx.room.on("participant_disconnected")
        def _on_participant_disconnected(participant: rtc.RemoteParticipant):
            # Only record the outcome when the farmer (not the agent) leaves
            if participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_AGENT:
                return

            nonlocal _call_escalated, _call_had_response, _call_language

            # Determine language from saved user profile
            try:
                saved = get_user(user_id)
                if saved and saved.get("language_preference"):
                    _call_language = saved["language_preference"]
            except Exception:
                pass

            # Determine outcome:
            # success  — agent spoke at least once (farmer got a response), or was escalated
            # failed   — farmer dropped before agent could respond
            if _call_escalated:
                # Escalation always counts as success (farmer got expert help)
                record_call_end(
                    session_id,
                    outcome="success",
                    language=_call_language,
                    escalated=True,
                    notes="Farmer escalated to human expert",
                )
                mark_call_escalated(session_id)
            elif _call_had_response:
                # Agent responded — call was at minimum partially helpful
                record_call_end(
                    session_id,
                    outcome="success",
                    language=_call_language,
                    notes="Farmer received agent response",
                )
            else:
                # Agent never spoke — farmer disconnected before getting any help
                record_call_end(
                    session_id,
                    outcome="failed",
                    failure_type="user_hangup",
                    language=_call_language,
                    notes="Farmer disconnected before agent responded (early disconnect)",
                )

        @ctx.room.on("disconnected")
        def _on_room_disconnected(_reason=None):
            """Fallback: record outcome if room closes without participant_disconnected."""
            try:
                conn_check = __import__("sqlite3").connect(
                    __import__("os").path.join(
                        __import__("os").path.dirname(__file__),
                        "krishimitra_memory.db",
                    ),
                    check_same_thread=False,
                )
                conn_check.row_factory = __import__("sqlite3").Row
                existing = conn_check.execute(
                    "SELECT outcome FROM call_analytics WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                conn_check.close()
                # Only update if still in_progress (not already closed by participant_disconnected)
                if existing and existing["outcome"] == "in_progress":
                    record_call_end(
                        session_id,
                        outcome="success" if _call_had_response else "failed",
                        failure_type=None if _call_had_response else "incomplete_task",
                        language=_call_language,
                        notes="Room closed",
                    )
            except Exception as exc:
                logger.warning("Analytics fallback error on room disconnect: %s", exc)

        # ---------------------------------------------------------------
        # Analytics: track escalation tool calls
        # ---------------------------------------------------------------
        # We patch create_escalation at the agent level by wrapping ctx shutdown
        # The simpler approach: mark escalated when the LLM calls the tool.
        # We detect this via the agent's tool usage through the session event.
        @session.on("tool_calls_collected")
        def _on_tool_calls(tool_calls=None, *_args, **_kwargs):
            nonlocal _call_escalated
            if not tool_calls:
                return
            for tc in tool_calls if hasattr(tool_calls, "__iter__") else []:
                name = getattr(tc, "name", "") or getattr(
                    getattr(tc, "function", None), "name", ""
                )
                if name == "create_escalation":
                    _call_escalated = True
                    logger.info(
                        "Analytics: escalation detected for session=%s", session_id
                    )

        # Speak greeting immediately after session starts.
        # For outbound: the call is already answered before we reach here, so
        # the farmer hears the opening the moment we start speaking.
        session.say(greeting, allow_interruptions=True)

    except Exception:
        import traceback

        traceback.print_exc()
        # Record call as failed due to API/agent error if session_id was set
        try:
            _sid = locals().get("session_id")
            if _sid:
                record_call_end(
                    _sid,
                    outcome="failed",
                    failure_type="api_error",
                    notes="Agent exception during call",
                )
        except Exception:
            pass
        raise


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=my_agent,
            prewarm_fnc=prewarm,
            agent_name="my-agent",
        )
    )
