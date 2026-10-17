# Guardian — shared contracts

**Read this before writing code.** This file is the single source of truth for how the three parts of Guardian talk to each other. If you need to change anything here, change it in its own commit and tell the group chat.

---

## 1. What we're building

Guardian is a **call firewall** between an older adult ("Linda") and phone scammers.

- Every call to Linda goes to a **Guardian phone number** first.
- **Verified** callers (family, doctor, pharmacy) ring Linda straight away. No screening, no recording.
- **Known scam numbers** (scam score ≥ 80) are rejected. Linda's phone never rings.
- **Unknown** callers are answered by a **screener voice agent** (Linda's assistant). It gives a recording notice, asks hard questions, and a live scorer judges the call every caller turn.
- The screener ends scam calls, takes a message when unsure, and connects clean callers to Linda with a short whisper.
- **Hard stop at 90 seconds**: recording and analysis end no matter what.
- **Only scam calls are kept** (audio + transcript in the evidence log). All other recordings are deleted once the call is decided.
- A **trusted family member** gets a text (Photon) for scam calls and for the bank-app alert.
- Every number gets a **scam score (0–100)**; Linda gets a weekly **safety score (0–100)**.
- The family can ask a **Guardian agent in ASI:One** (Fetch.ai): "who called Mom today?", "is this number safe?", "add to verified", "block this number".

The screener says it is **Linda's assistant**. It never claims to be Linda or a human.

---

## 2. Who owns what

| Person | AI tool | Owns (only edit these) | Role |
|---|---|---|---|
| **A** | Claude | `backend/` | Phone numbers, call router, `/tools/assess`, event stream, database, scores, family texts, post-call recording rules, deploy |
| **B** | Gemini | `ml/`, `agents/` | Scorer, transcript generation (Gemini API), Veri fine-tune, eval, synthetic call logs, ASI:One family agent |
| **C** | Claude | `voice/`, `web/` | Screener prompt + ElevenLabs agent, dashboard, phone simulator, design, README, pitch |

Shared files at the root (`CONTRACTS.md`, `CLAUDE.md`, `GEMINI.md`, `.env.example`, `.gitignore`): change only after telling the group.

**Never wait on someone else. Use the stand-ins:**
- A builds against the stand-in `ml/scorer.py` (already in the repo) until B replaces it.
- C builds the dashboard against fake events in `web/src/mock.ts` until A's stream works.
- B tests the family agent against fake API responses until A's endpoints exist.

---

## 3. Ports, URLs, environment

| Thing | Value |
|---|---|
| Backend (FastAPI) | `http://localhost:8000` |
| Web (Vite) | `http://localhost:5173` |
| Public backend URL | `PUBLIC_BASE_URL` (ngrok tonight, Vultr + GoDaddy domain later) |

All keys live in `.env` (never committed). Names are in `.env.example`. Share real values in the group chat privately.

---

## 4. Demo constants (everyone uses these exact values)

| Name | Value |
|---|---|
| Linda's user id | `linda` |
| Linda's real phone | `LINDA_PHONE` env var (a teammate's phone) |
| Trusted contact | `TRUSTED_PHONE` env var (judge 2 during the demo) |
| Son (verified) | `+13105550111`, label `Son (David)` |
| Dr. Patel (verified) | `+13105550199`, label `Dr. Patel's office` |
| Pharmacy (verified) | `+13105550123`, label `CVS Pharmacy` |
| Pre-flagged scam number | `+12135550142`, scam score 92, reason `Medicare impersonation` |

Use these in seed data, mocks and tests so everything lines up during the demo.

---

## 5. Contract A ↔ B: the scorer

B owns `ml/scorer.py`. A imports it directly (no separate service).

```python
from ml.scorer import score

result = score(transcript, call_id="abc123")
```

**Input** `transcript`: list of turns, oldest first.

```json
[
  {"speaker": "guardian", "text": "Hi, you've reached Linda's assistant. This call is recorded and screened. Who's calling?", "t": 0.0},
  {"speaker": "caller",   "text": "This is John from Medicare, I need to verify Linda's card number.", "t": 6.2}
]
```

- `speaker`: `"guardian"` or `"caller"`
- `t`: seconds since the call started

**Output** (always all keys):

```json
{
  "risk": 0.82,
  "stage": "payment_or_info",
  "red_flags": ["claims to be Medicare", "asks for card number", "refused callback number"],
  "action": "end",
  "model": "step5",
  "latency_ms": 640
}
```

| Key | Type | Values |
|---|---|---|
| `risk` | float | 0.0–1.0 |
| `stage` | str | `none`, `hook`, `authority`, `urgency`, `isolation`, `payment_or_info` |
| `red_flags` | list[str] | short phrases, max 5, shown on the dashboard |
| `action` | str | `end` if risk ≥ 0.7, else `continue` |
| `model` | str | `stub`, `step5`, `guardian-ft` |
| `latency_ms` | int | time the scorer took |

**Rules:**
- Must return in **under 1.5 s**. A slow scorer makes the voice agent sound like a bot.
- Must **never raise**. On any error, return `risk: 0.0`, `action: "continue"`, `model: "error"`, and log it.
- `step-5-preview` must be called on every real call (StepFun track requirement). If the fine-tuned model is used too, both run and the higher risk wins.

---

## 6. Contract A ↔ C: the voice agent tool

C configures the ElevenLabs agent. A serves this endpoint. The agent's prompt tells it to call this tool **after every caller answer**.

`POST {PUBLIC_BASE_URL}/tools/assess`

Request:

```json
{
  "call_id": "conv_abc123",
  "caller_number": "+12135550142",
  "guardian_asked": "What's a direct callback number?",
  "caller_said": "I can't give that out, this is urgent, she'll lose her coverage today."
}
```

- `call_id` and `caller_number`: pass from ElevenLabs system variables (conversation id, caller id). **C: confirm the exact variable names in ElevenLabs' docs and note them here.**

Response (must arrive in under 1.5 s):

```json
{
  "action": "end",
  "risk": 0.86,
  "say": "Linda isn't available. Please send any official correspondence by mail. Goodbye."
}
```

- `action: "continue"` → agent asks its next question.
- `action: "end"` → agent says `say` and hangs up.
- `action: "connect"` → only sent by A when screening is done and risk < 0.4; agent says "Connecting you now" and transfers to Linda.
- `action: "message"` → agent takes a message, then ends the call.

**Decision thresholds** (A owns them in `backend/app/config.py`):

| Condition | Action |
|---|---|
| risk ≥ 0.70 at any turn | `end` (scam) |
| after ≥ 3 caller turns or ≥ 60 s, risk < 0.40 | `connect` |
| after ≥ 3 caller turns or ≥ 60 s, 0.40 ≤ risk < 0.70 | `message` |
| otherwise | `continue` |
| 90 s reached | hard stop (agent max call length = 90 s) |

---

## 7. Contract A ↔ C: dashboard event stream

`GET {PUBLIC_BASE_URL}/stream/live` — server-sent events. Every event:

```json
{"type": "score", "call_id": "conv_abc123", "user_id": "linda", "ts": "2026-10-17T21:14:05Z", "data": { ... }}
```

| `type` | `data` |
|---|---|
| `call_started` | `{number, route: "screen" \| "verified" \| "rejected", profile: {scam_score, label, users_called_24h, flagged_by, top_reason}}` |
| `turn` | `{speaker, text, t}` |
| `score` | `{risk, stage, red_flags, model, latency_ms}` |
| `decision` | `{outcome: "connected" \| "message" \| "ended_scam" \| "rejected" \| "passed_verified", risk, seconds}` |
| `alert` | `{kind: "scam_call" \| "bank_app", to, text}` |
| `signal` | `{kind: "bank_app_open", during_call_with}` |
| `profile_updated` | `{number, scam_score, top_reason}` |
| `safety_updated` | `{user_id, safety_score}` |
| `evidence_saved` | `{evidence_id, number, recording_url, red_flags, score}` |

C's `web/src/mock.ts` must emit exactly these shapes.

---

## 8. REST API (A serves; C and B call it)

| Method + path | Body / query | Returns | Used by |
|---|---|---|---|
| `POST /calls/inbound` | phone provider webhook | routing instructions (TwiML or Photon equivalent) | phone provider |
| `POST /calls/post-call` | ElevenLabs post-call webhook | `200` | ElevenLabs |
| `POST /tools/assess` | see section 6 | see section 6 | voice agent |
| `GET /stream/live` | — | server-sent events | dashboard |
| `GET /calls` | `?user_id=linda&since=ISO` | `[{call_id, number, label, ts, seconds, outcome, risk}]` | dashboard, family agent |
| `GET /numbers/{number}` | — | `{number, scam_score, label, verified, users_called_24h, flagged_by, top_reason, first_seen}` | dashboard, family agent |
| `GET /verified` | `?user_id=linda` | `[{number, label}]` | dashboard, family agent |
| `POST /verified` | `{user_id, number, label}` | `{ok: true}` | dashboard, family agent |
| `DELETE /verified/{number}` | `?user_id=linda` | `{ok: true}` | dashboard |
| `POST /block` | `{user_id, number, reason}` | `{ok: true, scam_score}` | family agent, Photon reply |
| `GET /users/{user_id}/safety` | — | `{safety_score, scam_calls_blocked_7d, unverified_connected_7d, bank_alerts_7d}` | dashboard, family agent |
| `GET /evidence` | `?user_id=linda` | `[{evidence_id, number, ts, recording_url, transcript, red_flags, score}]` | dashboard |
| `POST /signals` | `{user_id, kind: "bank_app_open"}` | `{ok: true, alerted: bool}` | phone simulator |
| `POST /webhooks/photon` | Photon webhook | `200` | Photon (family replies BLOCK / SAFE) |
| `POST /demo/reset` | — | `{ok: true}` | anyone, between rehearsals |

All responses are JSON. Phone numbers are always E.164 (`+13105550111`).

---

## 9. Database (Tiger Data / Postgres) — A owns `backend/db/schema.sql`

```sql
CREATE TABLE users (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  guardian_number TEXT,
  real_phone TEXT
);

CREATE TABLE trusted_contacts (
  user_id TEXT REFERENCES users(id),
  name TEXT,
  phone TEXT
);

CREATE TABLE verified_numbers (
  user_id TEXT REFERENCES users(id),
  number TEXT,
  label TEXT,
  added_by TEXT,
  PRIMARY KEY (user_id, number)
);

CREATE TABLE call_logs (
  call_id TEXT,
  user_id TEXT,
  number TEXT,
  ts TIMESTAMPTZ NOT NULL,
  seconds REAL,
  outcome TEXT,          -- connected | message | ended_scam | rejected | passed_verified
  screened BOOLEAN,
  max_risk REAL
);
SELECT create_hypertable('call_logs', 'ts');

CREATE TABLE number_profiles (
  number TEXT PRIMARY KEY,
  first_seen TIMESTAMPTZ,
  total_calls INT DEFAULT 0,
  users_called_24h INT DEFAULT 0,
  flagged_by INT DEFAULT 0,
  max_live_risk REAL DEFAULT 0,
  scam_score INT DEFAULT 0,
  top_reason TEXT
);

CREATE TABLE scam_evidence (     -- scam calls ONLY
  evidence_id TEXT PRIMARY KEY,
  call_id TEXT,
  user_id TEXT,
  number TEXT,
  ts TIMESTAMPTZ,
  recording_url TEXT,
  transcript JSONB,
  red_flags JSONB,
  score REAL,
  delete_after TIMESTAMPTZ       -- ts + 90 days
);

CREATE TABLE signals (
  user_id TEXT,
  kind TEXT,                     -- bank_app_open
  ts TIMESTAMPTZ NOT NULL
);

CREATE TABLE events (
  call_id TEXT,
  user_id TEXT,
  ts TIMESTAMPTZ NOT NULL,
  type TEXT,
  data JSONB
);
SELECT create_hypertable('events', 'ts');
```

---

## 10. Scores (A computes; numbers here so B's seed data and C's slides match)

**Number scam score, 0–100** (sum, then clamp to 0–100):

| Part | Points |
|---|---|
| Highest live-call risk ever seen for this number | 45 × risk (0–1) |
| Guardian users who flagged it | 10 each, max 30 |
| Called 5+ different users in 24 h | +10 |
| 3+ calls under 20 s in 24 h | +10 |
| Calls between 9 PM and 8 AM | +5 |
| On any user's verified list | −40 |

**Linda's safety score, 0–100** (higher is safer). Start at 100 each week:

| Event in the last 7 days | Points |
|---|---|
| Unverified caller connected to Linda | −10 each |
| Scam call that reached screening | −5 each |
| Bank-app alert | −20 each |

Floor at 0.

---

## 11. Recording and privacy rules (everyone must follow)

1. The screener's first sentence includes **"This call is recorded."** (California requires all-party consent.)
2. Recording and analysis **stop at 90 s**.
3. Outcome `ended_scam` → keep audio + transcript in `scam_evidence` for 90 days.
4. Any other outcome → **delete** audio and transcript once the call is decided. Keep only the `call_logs` row. Keep the text of a message left for Linda.
5. Verified callers are **never** screened or recorded.
6. The bank-app alert only fires after a call with an **unverified** number, and only says "a banking app opened."
7. The screener never reveals anything about Linda and never claims to be human.

---

## 12. Git rules

- Edit only your own folders.
- `git pull --rebase` before starting work and before every push.
- Small commits, at least once an hour. Push to `main`.
- Changing this file → its own commit + message in the group chat.
- Never commit `.env`, keys, recordings, or `ml/data/`.

## 13. Milestones (all three test together)

| Time | Milestone |
|---|---|
| 8 PM Sat | **M1**: screener answers a real call with the recording notice; scorer returns JSON; Photon text reaches a phone; dashboard renders mock events |
| 1 AM Sun | **M2**: full call flow: scam call ended + saved + family texted; verified call rings through; legit call connected and recording deleted |
| 6 AM Sun | **M3**: fine-tune go/no-go |
| 8 AM Sun | **M4**: feature freeze (scores, bank-app alert, family agent working) |
| 11 AM Sun | **Submit** |
