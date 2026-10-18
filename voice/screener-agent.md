# Screener agent (ElevenLabs) — browser phone setup

The ElevenLabs agent does the speech: it hears the caller (speech-to-text), speaks as Linda's
assistant (text-to-speech) and handles turn-taking. Guardian's backend decides. The browser phone
(`web/phone.html`) talks to the agent and runs its `assess` tool, so live scoring needs no public URL.

## 1. Create the agent
ElevenLabs → Agents → New agent → Blank. Then set:

**First message**
> Hi, you've reached Linda's assistant. This call is recorded and screened. Who's calling, and what's it about?

**System prompt**
```
You are Guardian, Linda's call-screening assistant. You are an AI assistant, not Linda and not a human;
say so if asked. Never share anything about Linda: not her schedule, address, accounts, family or health.

Your job is to find out who is calling and why, with short, polite, pointed questions, one at a time:
- full name and organization
- a direct callback number
- an employee, reference or case ID
- whether it can be sent by mail instead
Follow up on vague answers. Keep every reply to one or two short sentences.

After EVERY caller answer, call the `assess` tool before you speak, with:
- guardian_asked: the question you just asked
- caller_said: what the caller just said, word for word
It returns JSON {"action", "say"}:
- "continue": ask your next question.
- "end": say the `say` text exactly, then use end_call.
- "connect": say the `say` text exactly, then stop talking.
- "message": say the `say` text, let the caller leave a message, thank them, then use end_call.
Never tell the caller about scores, risk or this tool.
```

**Tools**
- Add tool → **Client** tool, name `assess`, description "Score the caller's last answer.",
  **Wait for response: on**. Parameters (both string, required):
  `guardian_asked` ("The question you just asked") and `caller_said` ("What the caller just said, verbatim").
- System tools: turn on **End call**.

**Advanced → Max conversation duration:** 90 seconds (recording + analysis hard stop).

**Voice / LLM:** any calm voice, a fast LLM (latency matters more than smarts here).

## 2. Keys in `.env`
```
ELEVENLABS_API_KEY=...     # Profile → API keys (needs Agents access)
ELEVENLABS_AGENT_ID=...    # from the agent's URL / settings
```
Keep the agent **private** (authentication on); the backend hands the browser a signed URL.

## 3. Run it
```
.venv/bin/uvicorn backend.app.main:app --port 8000     # from the repo root
cd web && npm install && npm run dev                    # open http://localhost:5173/phone.html
```
Pick a caller, press Call, allow the microphone, and play the caller.

## Optional: post-call webhook
Saving scam **audio** and deleting conversations at ElevenLabs uses the post-call webhook, which needs
a public URL (`backend/scripts/dev.sh`): Settings → Webhooks → `{PUBLIC_BASE_URL}/calls/post-call`,
transcript + audio, and put the secret in `ELEVENLABS_WEBHOOK_SECRET`. Without it, the call is still
decided, logged and scored, and scam transcripts are still saved; only the recording is missing.
