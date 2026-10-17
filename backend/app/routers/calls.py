"""Phone webhooks: the inbound router and the ElevenLabs post-call webhook."""
import base64
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from twilio.twiml.voice_response import VoiceResponse

from .. import config as C
from .. import db, events, live, risk

log = logging.getLogger(__name__)
router = APIRouter()


def norm(number: str | None) -> str:
    """Best-effort E.164."""
    if not number:
        return "unknown"
    digits = "".join(ch for ch in number if ch.isdigit())
    if number.strip().startswith("+"):
        return "+" + digits
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return number


async def form_or_json(request: Request) -> dict:
    if request.headers.get("content-type", "").startswith("application/json"):
        return await request.json()
    return dict(await request.form())


def twiml(vr: VoiceResponse | str) -> Response:
    return Response(str(vr), media_type="application/xml")


async def route_for(user_id: str, number: str) -> str:
    """Router rules 1-2: verified -> ring Linda; blocked or score >= 80 -> reject; else screen."""
    if await db.fetchval("SELECT 1 FROM verified_numbers WHERE user_id = $1 AND number = $2", user_id, number):
        return "verified"
    if await db.fetchval("SELECT 1 FROM blocked_numbers WHERE user_id = $1 AND number = $2", user_id, number):
        return "rejected"
    score = await db.fetchval("SELECT scam_score FROM number_profiles WHERE number = $1", number)
    return "rejected" if (score or 0) >= C.REJECT_SCORE else "screen"


async def screener_twiml(call: live.Call, to_number: str) -> Response:
    if C.SCREEN_MODE == "register" and C.ELEVENLABS_API_KEY and C.ELEVENLABS_AGENT_ID:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.post(
                    f"{C.ELEVENLABS_API}/convai/twilio/register-call",
                    headers={"xi-api-key": C.ELEVENLABS_API_KEY},
                    json={"agent_id": C.ELEVENLABS_AGENT_ID, "from_number": call.number,
                          "to_number": to_number, "direction": "inbound",
                          "conversation_initiation_client_data": {"dynamic_variables": {
                              "guardian_call_id": call.id, "caller_number": call.number}}})
                r.raise_for_status()
                return Response(r.text, media_type="application/xml")
        except Exception:
            log.exception("ElevenLabs register-call failed; falling back")
    vr = VoiceResponse()
    if C.SCREENER_NUMBER:
        vr.dial(C.SCREENER_NUMBER, caller_id=call.number if call.number.startswith("+") else None)
    else:
        vr.say("Hi, you've reached Linda's assistant. This call is recorded and screened. "
               "Linda isn't available right now. Please send any correspondence by mail.")
        vr.hangup()
    return twiml(vr)


@router.post("/calls/inbound")
async def inbound(request: Request):
    p = await form_or_json(request)
    number, to = norm(p.get("From")), norm(p.get("To"))
    call_id = p.get("CallSid") or f"call_{int(time.time() * 1000)}"
    user_id = await db.fetchval("SELECT id FROM users WHERE guardian_number = $1", to) or C.DEMO_USER_ID
    route = await route_for(user_id, number)
    call = await live.start(call_id, number, route, user_id)

    if route == "verified":
        await live.finalize(call, "passed_verified")
        vr = VoiceResponse()
        if C.LINDA_PHONE:
            vr.dial(C.LINDA_PHONE, caller_id=number if number.startswith("+") else None, timeout=25)
        else:
            vr.say("Connecting you to Linda.")
        return twiml(vr)
    if route == "rejected":
        await live.finalize(call, "rejected")
        vr = VoiceResponse()
        vr.reject(reason="busy")
        return twiml(vr)
    return await screener_twiml(call, to)


# ---------------------------------------------------------------- ElevenLabs post-call webhook
def verify_signature(body: bytes, header: str | None):
    if not C.ELEVENLABS_WEBHOOK_SECRET:
        return
    try:
        parts = dict(p.split("=", 1) for p in (header or "").split(","))
        ts, sig = parts["t"], parts["v0"]
    except (ValueError, KeyError):
        raise HTTPException(401, "bad signature header")
    if abs(time.time() - int(ts)) > 30 * 60:
        raise HTTPException(401, "stale signature")
    expected = hmac.new(C.ELEVENLABS_WEBHOOK_SECRET.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(401, "bad signature")


async def el_delete_conversation(conversation_id: str):
    """Recording rule 4: drop audio + transcript at ElevenLabs once a non-scam call is decided."""
    if not C.ELEVENLABS_API_KEY:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.delete(f"{C.ELEVENLABS_API}/convai/conversations/{conversation_id}",
                                    headers={"xi-api-key": C.ELEVENLABS_API_KEY})
            log.info("deleted ElevenLabs conversation %s: %s", conversation_id, r.status_code)
    except Exception:
        log.exception("failed to delete conversation %s", conversation_id)


async def el_fetch_audio(conversation_id: str) -> bytes | None:
    if not C.ELEVENLABS_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(f"{C.ELEVENLABS_API}/convai/conversations/{conversation_id}/audio",
                                 headers={"xi-api-key": C.ELEVENLABS_API_KEY})
            r.raise_for_status()
            return r.content
    except Exception:
        log.exception("failed to fetch audio for %s", conversation_id)
        return None


async def save_recording(call: live.Call, audio: bytes):
    C.RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    (C.RECORDINGS_DIR / f"{call.evidence_id}.mp3").write_bytes(audio)
    url = f"{C.PUBLIC_BASE_URL}/e/{call.evidence_id}/audio"
    await db.execute("UPDATE scam_evidence SET recording_url = $2 WHERE evidence_id = $1", call.evidence_id, url)
    score = await db.fetchval("SELECT scam_score FROM number_profiles WHERE number = $1", call.number)
    events.publish("evidence_saved", {"evidence_id": call.evidence_id, "number": call.number,
                                      "recording_url": url, "red_flags": call.red_flags, "score": score},
                   call.id, call.user_id)


def el_turns(transcript: list) -> list:
    return [{"speaker": "guardian" if t.get("role") == "agent" else "caller",
             "text": t.get("message") or "", "t": float(t.get("time_in_call_secs") or 0)}
            for t in transcript or [] if t.get("message")
            and float(t.get("time_in_call_secs") or 0) <= C.HARD_STOP_SECONDS]


async def find_call(data: dict) -> live.Call | None:
    conv_id = data.get("conversation_id")
    dyn = (data.get("conversation_initiation_client_data") or {}).get("dynamic_variables") or {}
    call = live.get(conv_id) or live.get(dyn.get("guardian_call_id") or "") \
        or live.get(dyn.get("system__call_sid") or "")
    if call is None and (dyn.get("system__caller_id") or dyn.get("caller_number")):
        call = await live.resolve(conv_id, norm(dyn.get("system__caller_id") or dyn.get("caller_number")))
    return call


async def handle_transcription(data: dict):
    conv_id = data.get("conversation_id")
    call = await find_call(data)
    if call is None:
        log.warning("post-call for unknown conversation %s; deleting it", conv_id)
        await el_delete_conversation(conv_id)
        return
    turns = el_turns(data.get("transcript"))
    if call.outcome is None:  # caller hung up or 90 s cutoff before the screener decided
        await live.finalize(call, live.ACTION_TO_OUTCOME.get(call.final_action)
                            or risk.final_outcome(call.max_risk))

    if call.outcome == "ended_scam":
        if turns:
            await db.execute("UPDATE scam_evidence SET transcript = $2 WHERE evidence_id = $1",
                             call.evidence_id, turns)
        if not (C.RECORDINGS_DIR / f"{call.evidence_id}.mp3").exists():
            if audio := await el_fetch_audio(conv_id):
                await save_recording(call, audio)
        return

    if call.outcome == "message":
        decided_t = (call.decided_at - call.started) if call.decided_at else 0
        said = [t["text"] for t in turns if t["speaker"] == "caller" and t["t"] >= decided_t - 5]
        if said:
            await db.execute(
                "INSERT INTO messages VALUES ($1, $2, $3, $4, $5) ON CONFLICT (call_id) DO UPDATE SET text = $5",
                call.id, call.user_id, call.number, call.started_at, " ".join(said))
    await el_delete_conversation(conv_id)


async def handle_audio(data: dict):
    call = await find_call(data)
    if call and call.outcome == "ended_scam" and data.get("full_audio"):
        await save_recording(call, base64.b64decode(data["full_audio"]))


@router.post("/calls/post-call")
async def post_call(request: Request, background: BackgroundTasks):
    body = await request.body()
    verify_signature(body, request.headers.get("elevenlabs-signature"))
    payload = json.loads(body or b"{}")
    kind, data = payload.get("type"), payload.get("data") or {}
    if kind == "post_call_transcription":
        background.add_task(handle_transcription, data)
    elif kind == "post_call_audio":
        background.add_task(handle_audio, data)
    return {"ok": True}


@router.get("/calls")
async def list_calls(user_id: str = C.DEMO_USER_ID, since: datetime | None = None):
    since = since or datetime.now(timezone.utc) - timedelta(days=7)
    rows = await db.fetch(
        """SELECT c.call_id, c.number, v.label, c.ts, c.seconds, c.outcome, c.max_risk AS risk
           FROM call_logs c LEFT JOIN verified_numbers v ON v.user_id = c.user_id AND v.number = c.number
           WHERE c.user_id = $1 AND c.ts >= $2 ORDER BY c.ts DESC LIMIT 200""", user_id, since)
    for r in rows:
        r["ts"] = r["ts"].isoformat()
    return rows
