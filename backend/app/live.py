"""Live call state and the end-of-call pipeline.

A call is known by the id Twilio gave it at /calls/inbound (CallSid). ElevenLabs uses its own
conversation id in /tools/assess and the post-call webhook; `resolve()` links the two by caller
number, so the dashboard sees one call_id from ring to decision.
"""
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import config as C
from . import db, events, notify, risk

log = logging.getLogger(__name__)


@dataclass
class Call:
    id: str
    number: str
    user_id: str = C.DEMO_USER_ID
    route: str = "screen"
    started: float = field(default_factory=time.monotonic)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    transcript: list = field(default_factory=list)
    caller_turns: int = 0
    max_risk: float = 0.0
    red_flags: list = field(default_factory=list)
    outcome: str | None = None
    final_action: str | None = None   # set by /tools/assess the moment it decides
    evidence_id: str | None = None
    decided_at: float | None = None
    conversation_id: str | None = None

    @property
    def seconds(self) -> float:
        return round(time.monotonic() - self.started, 1)

    def t(self) -> float:
        return min(self.seconds, float(C.HARD_STOP_SECONDS))


ACTION_TO_OUTCOME = {"end": "ended_scam", "connect": "connected", "message": "message"}

calls: dict[str, Call] = {}
aliases: dict[str, str] = {}   # ElevenLabs conversation id -> our call id


def pretty(number: str) -> str:
    d = number[-10:] if number and number.startswith("+1") else None
    return f"({d[:3]}) {d[3:6]}-{d[6:]}" if d and d.isdigit() else (number or "unknown number")


def reset():
    calls.clear()
    aliases.clear()


def get(call_id: str) -> Call | None:
    return calls.get(aliases.get(call_id, call_id))


async def profile_summary(number: str, user_id: str = C.DEMO_USER_ID) -> dict:
    p = await risk.get_profile(number)
    label = await db.fetchval(
        "SELECT label FROM verified_numbers WHERE user_id = $1 AND number = $2", user_id, number)
    return {"scam_score": p["scam_score"], "label": label, "users_called_24h": p["users_called_24h"],
            "flagged_by": p["flagged_by"], "top_reason": p["top_reason"]}


async def start(call_id: str, number: str, route: str, user_id: str = C.DEMO_USER_ID) -> Call:
    call = Call(id=call_id, number=number, route=route, user_id=user_id)
    calls[call_id] = call
    events.publish("call_started", {"number": number, "route": route,
                                    "profile": await profile_summary(number, user_id)},
                   call_id, user_id)
    return call


async def resolve(call_id: str, caller_number: str | None) -> Call:
    """Find the live call for an ElevenLabs conversation, linking ids on first sight."""
    if call := get(call_id):
        return call
    cutoff = time.monotonic() - 180
    candidates = [c for c in calls.values()
                  if c.route == "screen" and c.outcome is None and c.conversation_id is None
                  and c.started > cutoff and (not caller_number or c.number == caller_number)]
    if candidates:
        call = max(candidates, key=lambda c: c.started)
        call.conversation_id = call_id
        aliases[call_id] = call.id
        return call
    # No inbound webhook seen (e.g. ElevenLabs playground or direct-to-agent number): start fresh.
    call = await start(call_id, caller_number or "unknown", "screen")
    call.conversation_id = call_id
    return call


def add_turn(call: Call, speaker: str, text: str):
    if not text:
        return
    turn = {"speaker": speaker, "text": text, "t": call.t()}
    call.transcript.append(turn)
    if speaker == "caller":
        call.caller_turns += 1
    events.publish("turn", turn, call.id, call.user_id)


async def family_contacts(user_id: str) -> list[str]:
    rows = await db.fetch("SELECT phone FROM trusted_contacts WHERE user_id = $1", user_id)
    phones = [r["phone"] for r in rows if r["phone"]]
    return phones or ([C.TRUSTED_PHONE] if C.TRUSTED_PHONE else [])


async def alert_family(call_id, user_id, kind, text, number=None):
    for to in await family_contacts(user_id):
        await notify.send_text(to, text, number=number)
        events.publish("alert", {"kind": kind, "to": to, "text": text}, call_id, user_id)


def scam_text(call: Call, score: int, evidence_id: str) -> str:
    when = datetime.now().strftime("%-I:%M %p")
    flags = "; ".join(call.red_flags[:3]) or "high scam risk"
    return (f"Guardian: Blocked a likely scam call to Mom at {when} from {pretty(call.number)}. "
            f"Red flags: {flags}. Scam score {score}/100. "
            f"Recording: {C.PUBLIC_BASE_URL}/e/{evidence_id}. "
            f"Reply BLOCK to block this number for everyone, or SAFE if you know them.")


def whisper(call: Call) -> str:
    first = next((t["text"] for t in call.transcript if t["speaker"] == "caller"), "")
    about = (first[:80] + "...") if len(first) > 80 else first
    return f"{pretty(call.number)}: \"{about}\" Low risk." if about else f"{pretty(call.number)}, low risk."


async def log_call(call_id, user_id, number, outcome, seconds, screened, max_risk, ts=None):
    await db.execute("INSERT INTO call_logs VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
                     call_id, user_id, number, ts or datetime.now(timezone.utc),
                     seconds, outcome, screened, max_risk)


async def finalize(call: Call, outcome: str) -> Call:
    """Decide the call once: log it, update scores, keep or drop the evidence, alert the family."""
    if call.outcome:
        return call
    call.outcome = outcome
    call.decided_at = time.monotonic()
    seconds = call.t()
    data = {"outcome": outcome, "risk": round(call.max_risk, 2), "seconds": seconds}
    if outcome == "connected":
        data["whisper"] = whisper(call)
    events.publish("decision", data, call.id, call.user_id)

    screened = call.route == "screen"
    await log_call(call.id, call.user_id, call.number, outcome, seconds, screened,
                   call.max_risk if screened else None, call.started_at)

    if outcome == "ended_scam":
        call.evidence_id = uuid.uuid4().hex[:8]
        reason = call.red_flags[0] if call.red_flags else None
        if reason:
            await db.execute(
                """INSERT INTO number_profiles (number, first_seen, top_reason) VALUES ($1, now(), $2)
                   ON CONFLICT (number) DO UPDATE SET top_reason = EXCLUDED.top_reason""",
                call.number, reason[:1].upper() + reason[1:])
    profile = await risk.recompute_profile(call.number)
    events.publish("profile_updated", {"number": call.number, "scam_score": profile["scam_score"],
                                       "top_reason": profile["top_reason"]}, call.id, call.user_id)

    if outcome == "ended_scam":
        await db.execute(
            """INSERT INTO scam_evidence (evidence_id, call_id, user_id, number, ts, recording_url,
                                          transcript, red_flags, score, delete_after)
               VALUES ($1, $2, $3, $4, $5, NULL, $6, $7, $8, $9)""",
            call.evidence_id, call.id, call.user_id, call.number, call.started_at, call.transcript,
            call.red_flags, call.max_risk, call.started_at + timedelta(days=C.EVIDENCE_RETENTION_DAYS))
        events.publish("evidence_saved", {"evidence_id": call.evidence_id, "number": call.number,
                                          "recording_url": None, "red_flags": call.red_flags,
                                          "score": profile["scam_score"]}, call.id, call.user_id)
        await alert_family(call.id, call.user_id, "scam_call",
                           scam_text(call, profile["scam_score"], call.evidence_id), call.number)
    elif screened:
        # Recording rule 4: nothing but the call_logs row survives a non-scam call.
        call.transcript = []

    if outcome in ("ended_scam", "connected", "rejected"):
        s = await risk.user_safety(call.user_id)
        events.publish("safety_updated", {"user_id": call.user_id, "safety_score": s["safety_score"]},
                       call.id, call.user_id)
    return call
