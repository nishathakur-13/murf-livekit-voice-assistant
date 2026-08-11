# Backend — Voice Agent with Murf Falcon TTS

The Python backend for the Voice Agent Starter. It runs a real-time voice AI pipeline using [LiveKit Agents](https://docs.livekit.io/agents), connecting Murf Falcon TTS, Deepgram STT, and Google Gemini into a single conversational agent.

## How It Works

```
User speaks → [Deepgram STT] → text → [Gemini LLM] → response → [Murf Falcon TTS] → audio → User hears
```

LiveKit handles the real-time audio transport. The agent connects to LiveKit as a participant, listens for user speech, and responds with synthesized audio.

## Setup

### 1. Install dependencies

```bash
cd backend
uv sync
```

### 2. Configure environment

```bash
cp .env.example .env.local
```

Fill in your keys in `.env.local`:

| Variable             | Where to get it                                           |
| -------------------- | --------------------------------------------------------- |
| `LIVEKIT_URL`        | [LiveKit Cloud](https://cloud.livekit.io/) → Settings     |
| `LIVEKIT_API_KEY`    | [LiveKit Cloud](https://cloud.livekit.io/) → Settings     |
| `LIVEKIT_API_SECRET` | [LiveKit Cloud](https://cloud.livekit.io/) → Settings     |
| `MURF_API_KEY`       | [murf.ai/api/dashboard](https://murf.ai/api/dashboard)    |
| `DEEPGRAM_API_KEY`   | [deepgram.com](https://console.deepgram.com/)             |
| `GOOGLE_API_KEY`     | [aistudio.google.com](https://aistudio.google.com/apikey) |

For LiveKit Cloud users, you can auto-populate LiveKit credentials:

```bash
lk cloud auth
lk app env -w -d .env.local
```

### 3. Download models

```bash
uv run python src/agent.py download-files
```

This downloads Silero VAD and the LiveKit turn detector models.

### 4. Run the agent

```bash
# Development mode (auto-reload)
uv run python src/agent.py dev

# Or test directly in your terminal (no frontend needed)
uv run python src/agent.py console

# Production
uv run python src/agent.py start
```

## Configuration

All configuration lives in [`src/agent.py`](src/agent.py).

### System prompt

The `SYSTEM_PROMPT` constant at the top of `agent.py` controls what your agent does. Change it to build any voice-powered use case.

#### Example prompts

**Customer Support (default):**

```
You are a friendly and efficient customer support agent for a tech company. Help users with account issues, billing questions, and product troubleshooting. Be concise, empathetic, and solution-oriented. If you don't know something, say so honestly and offer to escalate.
```

**Language Tutor:**

```
You are a patient and encouraging language tutor helping the user practice conversational Spanish. Speak primarily in Spanish but switch to English to explain grammar or vocabulary when needed. Correct mistakes gently and suggest better phrasing. Keep conversations natural and fun.
```

**AI Receptionist:**

```
You are a professional receptionist for a medical clinic. Help callers schedule appointments, answer questions about office hours and services, and take messages for doctors. Be warm but efficient. Ask for the caller's name and reason for calling upfront.
```

**Interview Coach:**

```
You are an experienced interview coach. Conduct mock interviews with the user for software engineering roles. Ask one behavioral or technical question at a time, let the user answer fully, then give specific feedback on their response — what was strong, what could improve, and a suggested reframe. Keep the tone encouraging but honest.
```

**Sales Assistant:**

```
You are a knowledgeable sales assistant for an electronics store. Help customers find the right product by asking about their needs, budget, and preferences. Compare options clearly, highlight trade-offs, and make a recommendation. Never be pushy — focus on helping the customer make the best decision for them.
```

**Fitness Coach:**

```
You are an upbeat personal fitness coach. Help users plan workouts, suggest exercises for specific muscle groups, and answer questions about form and technique. Ask about their fitness level and any injuries before recommending exercises. Keep instructions clear and motivating.
```

**Storyteller / Bedtime Narrator:**

```
You are a creative storyteller who tells original bedtime stories for children aged 4–8. Ask the child (or parent) for a character name, a favorite animal, and a setting, then weave a short, calming story. Use vivid but simple language. End each story on a peaceful, sleepy note.
```

**Meeting Summarizer:**

```
You are a meeting assistant. The user will describe what happened in a meeting or read you their notes. Summarize the key decisions, action items (with owners if mentioned), and any open questions. Be concise and structured. Ask clarifying questions if something is ambiguous.
```

**Trivia Game Host:**

```
You are an enthusiastic trivia game host. Ask the user one trivia question at a time from a mix of categories — science, history, pop culture, geography, and sports. Wait for their answer, tell them if they're right or wrong, give a brief fun fact, then move to the next question. Keep score and announce it every 5 questions.
```

**Mental Health Check-in Companion:**

```
You are a gentle, non-clinical wellness companion. Help users talk through their day, reflect on how they're feeling, and practice simple grounding exercises like deep breathing or gratitude lists. You are not a therapist — if the user expresses serious distress or mentions self-harm, gently encourage them to reach out to a professional or crisis helpline.
```

### Mandi Price Lookup (Day 5 — Real Data Tool)

KrishiMitra uses the **Agmarknet dataset** from [data.gov.in](https://data.gov.in/resource/variety-wise-daily-market-prices-data-commodity) to look up real wholesale mandi prices.

| Property | Detail |
|---|---|
| Data source | [Agmarknet via data.gov.in](https://data.gov.in/resource/variety-wise-daily-market-prices-data-commodity) — Government of India, Ministry of Agriculture |
| Data type | **Live government data** (not a local/hardcoded dataset) |
| Update frequency | Daily, published by APMC mandis |
| Freshness lag | Typically **1–3 days** behind actual trade dates — Agmarknet publishes as mandis report |
| API | REST, JSON, free with registration at data.gov.in |
| Authentication | `DATA_GOV_API_KEY` env variable (falls back to public demo key if unset) |

**Spoken data freshness:** When the agent speaks a mandi price, it always mentions the date the record is from (e.g. "Yeh data 8 August ka hai"). This is deliberate — yesterday's rate and today's rate may be different selling decisions for a farmer.

**Graceful failure:** If the API is unreachable (timeout, HTTP error, no records), the agent says something like: "Abhi mandi ka data nahi mil raha — net ya server ki dikkat ho sakti hai. Kuch der baad try karein, ya apne najdeeki APMC se pata kar lein." It never hallucinates a price.

**Advanced — district chaining:** If the farmer's district was saved in Day 4 memory, the `get_mandi_price` tool automatically uses it without asking again.

To use your own API key:
1. Register free at [data.gov.in](https://data.gov.in/user/register)
2. Add to `.env.local`: `DATA_GOV_API_KEY=your_key_here`

### Voice

Set the `voice` argument in the `murf.TTS(...)` call:

```python
tts=murf.TTS(
    voice="en-US-matthew",    # Change this
    style="Conversation",
    tokenizer=tokenize.basic.SentenceTokenizer(min_sentence_len=2),
    text_pacing=True
)
```

Some voice options:

| Voice ID | Description                      |
| -------- | -------------------------------- |
| `Anisha` | Indian English, female (default) |
| `Pooja`  | Indian English, female           |
| `Samar`  | Indian English, male             |
| `Amara`  | US English, female               |
| `Hazel`  | UK English, female               |
| `Bertie` | UK English, male                 |
| `Gordon` | US English, male                 |

Browse all 150+ voices: [Murf Voice Library](https://murf.ai/api/docs/voices-styles/voice-library).

### STT (Speech-to-Text)

Default is Deepgram Nova-3. Change in the `AgentSession(stt=...)` call:

```python
stt=deepgram.STT(model="nova-3")
```

### LLM

Default is Google Gemini. To switch:

- **Gemini (default):** Set `GOOGLE_API_KEY` in `.env.local`
- **OpenAI:** Set `OPENAI_API_KEY`, install `livekit-agents[openai]`, and change the `llm=` argument

## Testing

The project includes an eval suite based on the LiveKit Agents [testing framework](https://docs.livekit.io/agents/build/testing/):

```bash
uv run pytest
```

Tests are in [`tests/test_agent.py`](tests/test_agent.py) and use LLM-as-judge evaluations to verify the agent behaves correctly (friendly greetings, grounding, refusing harmful requests).

To run tests in CI, you'll need to add `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET` as repository secrets.

## Deployment

### Railway

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/deploy/tIVCF1?referralCode=cNjn2P&utm_medium=integration&utm_source=template&utm_campaign=generic)

Set these environment variables in Railway:

- `MURF_API_KEY`
- `DEEPGRAM_API_KEY`
- `GOOGLE_API_KEY`
- `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`

### Docker

A production-ready [Dockerfile](Dockerfile) is included:

```bash
docker build -t murf-voice-agent .
docker run --env-file .env.local murf-voice-agent
```

## Project Structure

```
backend/
├── src/
│   └── agent.py          # Agent entrypoint — pipeline, prompt, config
├── tests/
│   └── test_agent.py     # LLM-judged eval suite
├── .env.example           # Environment variable template
├── pyproject.toml         # Python dependencies (uv)
├── Dockerfile             # Production container
└── railway.toml           # Railway deploy config
```

## Links

- [Murf Falcon TTS Docs](https://murf.ai/api/docs/text-to-speech/streaming)
- [Murf Voice Library](https://murf.ai/api/docs/voices-styles/voice-library)
- [LiveKit Agents Docs](https://docs.livekit.io/agents)
- [Deepgram Nova-3 Docs](https://developers.deepgram.com)

## License

MIT — see [LICENSE](LICENSE).

---

## Day 6 — Outbound Calls (Telephony)

KrishiMitra can now **make outbound calls** to farmers, delivering a daily farming tip over the phone. This is the Learning & Literacy use case: a scheduled call that reaches the farmer proactively instead of waiting for them to call in.

### How it works

```
outbound_call.py
  → LiveKit: create room + dispatch agent (with phone_number in metadata)
    → agent.py: receives job, reads phone_number from metadata
      → LiveKit SIP: create_sip_participant (outbound trunk → Twilio → PSTN)
        → farmer's phone rings → farmer answers
          → agent delivers: who is calling + why + how to stop + farming tip
```

The agent uses Murf Falcon TTS (voice: Anisha, Indian English) — same voice as the inbound agent.

### Prerequisites

1. **Twilio account** with an Elastic SIP Trunk  
   - [console.twilio.com](https://console.twilio.com) → Elastic SIP Trunking → Create trunk  
   - Termination tab → note the SIP URI (e.g. `mytrunk.pstn.twilio.com`)  
   - Create a credential list (username + password), attach to the trunk  
   - Buy or port a Twilio phone number for caller ID  

2. **LiveKit Cloud** project (you already have this)

### Step 1: Configure environment

Add to `backend/.env.local`:

```env
# Twilio SIP Termination URI (from Twilio elastic trunk → Termination tab)
TWILIO_SIP_TERM_URI=mytrunk.pstn.twilio.com

# Credential list username/password attached to the Twilio trunk
TWILIO_SIP_USERNAME=your-credential-list-username
TWILIO_SIP_PASSWORD=your-credential-list-password

# Twilio phone number (caller ID), E.164 format
TWILIO_PHONE_NUMBER=+12015551234
```

### Step 2: Create the LiveKit outbound SIP trunk (once)

```bash
uv run python src/setup_outbound_trunk.py
```

Copy the printed `LIVEKIT_SIP_OUTBOUND_TRUNK_ID` into `.env.local`:

```env
LIVEKIT_SIP_OUTBOUND_TRUNK_ID=ST_xxxxxxxxxxxxxxxxxxxx
```

### Step 3: Start the agent worker

```bash
uv run python src/agent.py start
```

The agent listens for dispatched jobs. Use `start` (not `dev`) for phone testing — `dev` connects to the LiveKit playground browser UI, not SIP.

### Step 4: Trigger an outbound call

```bash
# Single call — basic
uv run python src/outbound_call.py --to +919876543210

# Single call — with a specific farming topic
uv run python src/outbound_call.py --to +919876543210 --topic "kharif crop soil preparation"

# Dry run — see what would happen without placing a real call
uv run python src/outbound_call.py --to +919876543210 --dry-run
```

### Opening statement (Day 6 requirement)

Every outbound call opens with a mandatory three-part disclosure — who is calling, why, and how to stop:

> "Namaste! Main KrishiMitra AI hoon, ek automated farming assistant.
> Main aapko aaj ka farming tip dene ke liye call kar rahi hoon — topic hai: [topic].
> Agar aap yeh call nahi chahte, to bas 'band karo' ya 'stop' bolein aur main turant call khatam kar dungi.
> Kya aap tayaar hain?"

### Outcome handling

| Outcome | SIP code | What happens |
|---|---|---|
| Call answered | 200 OK | Agent delivers the tip and has a conversation |
| Call rejected / busy | 486, 603 | `SipCallError` raised, job shut down, logged as `USER_REJECTED` |
| No answer / timeout | 408, 480 | `SipCallError` raised, job shut down, logged as `NO_ANSWER` |
| Trunk failure | 5xx | `SipCallError` raised, job shut down, logged as `TRUNK_FAILURE` |
| Mid-call hang-up | CLIENT_INITIATED | `participant_disconnected` event, logged as `COMPLETED` |

### New files

| File | Purpose |
|---|---|
| `src/outbound_call.py` | CLI trigger — dispatches agent with phone number + topic |
| `src/setup_outbound_trunk.py` | One-time script to register Twilio SIP trunk with LiveKit |

### Linphone alternative (if Twilio trial is exhausted)

If your Twilio free trial is used up, you can test locally using [Linphone](https://linphone.org/en/) as a SIP softphone. See `../supplementary/outbound-over-linphone.md` for the Linphone-specific SIP trunk configuration.
