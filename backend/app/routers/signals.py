"""POST /signals: "a banking app opened" from Linda's phone (risk rule 4)."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from .. import config as C
from .. import db, events, live

router = APIRouter()


class SignalIn(BaseModel):
    user_id: str = C.DEMO_USER_ID
    kind: str = "bank_app_open"


async def recent_unverified_call(user_id: str):
    """(number, during) for a live screened call, or one that ended in the last 10 minutes."""
    active = [c for c in live.calls.values()
              if c.user_id == user_id and c.route == "screen" and c.outcome in (None, "connected")
              and c.seconds < C.HARD_STOP_SECONDS + 600]
    if active:
        c = max(active, key=lambda c: c.started)
        return c.number, c.outcome is None or c.seconds <= C.HARD_STOP_SECONDS, c.id
    row = await db.fetchrow(
        """SELECT c.call_id, c.number FROM call_logs c
           WHERE c.user_id = $1 AND c.ts > $2 AND c.outcome NOT IN ('passed_verified', 'rejected')
             AND NOT EXISTS (SELECT 1 FROM verified_numbers v WHERE v.user_id = c.user_id AND v.number = c.number)
           ORDER BY c.ts DESC LIMIT 1""",
        user_id, datetime.now(timezone.utc) - timedelta(minutes=C.BANK_ALERT_WINDOW_MIN))
    return (row["number"], False, row["call_id"]) if row else (None, False, None)


@router.post("/signals")
async def post_signal(body: SignalIn):
    await db.execute("INSERT INTO signals (user_id, kind, ts) VALUES ($1, $2, now())", body.user_id, body.kind)
    if body.kind != "bank_app_open":
        return {"ok": True, "alerted": False}
    number, during, call_id = await recent_unverified_call(body.user_id)
    events.publish("signal", {"kind": body.kind, "during_call_with": number}, call_id, body.user_id)
    if not number:
        return {"ok": True, "alerted": False}
    when = "during" if during else "right after"
    text = (f"Guardian URGENT: Mom opened a banking app {when} a call from {live.pretty(number)}, "
            f"a number that isn't on her verified list. Please call her now.")
    await live.alert_family(call_id, body.user_id, "bank_app", text, number)
    return {"ok": True, "alerted": True}
