# Linda (ElevenLabs agent) — browser demo setup

In the browser demo the ElevenLabs agent **is Linda**, a 78-year-old grandmother. Visitors call her and try
to scam her. Guardian listens: `web/src/phone.ts` posts every exchange to `POST /calls/web/{id}/turn`, the
scorer (`ml/scorer.py`, Claude Haiku + keyword rules) reads the whole call so far, the family gets a
Photon iMessage heads-up at risk ≥ 0.4, and at risk ≥ 0.7 Guardian steps in: the page sends Linda a
`GUARDIAN ALERT` contextual update, she says goodbye, the call ends, the evidence is saved and the family
gets the "Blocked" text.

The agent needs no tools other than **End call**; scoring does not depend on the LLM calling anything.

## Agent settings (agent `Linda (Guardian demo)`, id in `ELEVENLABS_AGENT_ID`)

- **Voice:** Grandma Oxley (`vFLqXa8bgbofGarf6fZh`)
- **First message:** "Hello? This is Linda. Just so you know, my calls are recorded. Who's calling, dear?"
  (keeps the all-party recording notice California requires)
- **System tools:** End call
- **Max conversation duration:** 90 seconds
- **Authentication:** on (the backend hands the browser a signed URL)
- **Prompt (summary):** warm, chatty grandmother; lets callers explain what they want but never gives out
  personal or financial information or agrees to pay; stalls instead; follows any `GUARDIAN ALERT` by saying
  goodbye and ending the call; tells the truth if sincerely asked whether she is an AI.

## Keys

`.env` / Railway: `ELEVENLABS_API_KEY`, `ELEVENLABS_AGENT_ID`, and `ANTHROPIC_API_KEY` for the scorer
(without it the scorer falls back to keyword rules only).

## Run locally
```
.venv/bin/uvicorn backend.app.main:app --port 8000     # from the repo root
cd web && npm install && npm run dev                    # http://localhost:5173 (landing) or /phone.html
```

## Optional: post-call webhook
Saving scam **audio** uses the ElevenLabs post-call webhook: `{PUBLIC_BASE_URL}/calls/post-call`, transcript +
audio, secret in `ELEVENLABS_WEBHOOK_SECRET`. Without it, scam calls are still decided, logged and texted,
and their transcripts saved; only the recording is missing.
