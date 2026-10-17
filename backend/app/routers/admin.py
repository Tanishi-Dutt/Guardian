"""Family text replies (BLOCK / SAFE) and the demo reset."""
from fastapi import APIRouter, Request

from .. import config as C
from .. import db, events, live, notify
from .calls import form_or_json, norm
from .numbers import add_verified, block_number

router = APIRouter()


@router.post("/webhooks/photon")
async def photon_reply(request: Request):
    """Accepts Photon JSON ({from, text}) or a Twilio SMS form (From, Body)."""
    p = await form_or_json(request)
    sender = norm(p.get("from") or p.get("From") or "")
    text = (p.get("text") or p.get("Body") or p.get("message") or "").strip()
    word = text.split()[0].upper() if text else ""
    number = notify.last_alert_number.get(sender)
    # Allow "BLOCK +12135550142" to name the number explicitly.
    if len(text.split()) > 1 and any(ch.isdigit() for ch in text):
        number = norm(text.split(maxsplit=1)[1])
    if not number or word not in ("BLOCK", "SAFE"):
        return {"ok": True, "handled": False}
    user_id = await db.fetchval("SELECT user_id FROM trusted_contacts WHERE phone = $1", sender) or C.DEMO_USER_ID
    if word == "BLOCK":
        p = await block_number(user_id, number, "Blocked by family via text")
        reply = f"Guardian: {live.pretty(number)} is blocked. Scam score now {p['scam_score']}/100."
    else:
        await add_verified(user_id, number, "Marked safe by family", added_by=sender)
        reply = f"Guardian: {live.pretty(number)} is now on Mom's verified list."
    await notify.send_text(sender, reply)
    return {"ok": True, "handled": True, "action": word.lower(), "number": number}


@router.post("/demo/reset")
async def demo_reset():
    await events.flush()
    await db.reset()
    live.reset()
    notify.sent.clear()
    notify.last_alert_number.clear()
    events.publish("safety_updated", {"user_id": C.DEMO_USER_ID, "safety_score": 100})
    return {"ok": True}
