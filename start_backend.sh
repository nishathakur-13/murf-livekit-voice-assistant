#!/bin/bash
# Unset any system-level env vars that override .env.local
unset GROQ_API_KEY
unset GOOGLE_API_KEY
unset OPENAI_API_KEY

cd "$(dirname "$0")/backend"
uv run python src/agent.py dev
