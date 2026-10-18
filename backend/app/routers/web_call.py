"""Browser phone: start and end a call without Twilio (web/phone.html).

The page picks a caller number, asks here which route it takes (same rules as /calls/inbound),
and for screened calls gets a signed ElevenLabs URL so the API key stays on the server. The
agent's `assess` tool then runs in the browser and posts to /tools/assess with this call_id.
"""
import logging
import uuid

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import config as C
from .. import live, risk
from .calls import norm, route_for

log = logging.getLogger(__name__)
router = APIRouter()


class WebStartIn(BaseModel):
    from_number: str
    user_id: str = C.DEMO_USER_ID


async def signed_url() -> str | None:
    if not (C.ELEVENLABS_API_KEY and C.ELEVENLABS_AGENT_ID):
        return None
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{C.ELEVENLABS_API}/convai/conversation/get-signed-url",
                                 params={"agent_id": C.ELEVENLABS_AGENT_ID},
                                 headers={"xi-api-key": C.ELEVENLABS_API_KEY})
            r.raise_for_status()
            return r.json()["signed_url"]
    except Exception:
        log.exception("ElevenLabs signed URL failed")
        return None


@router.post("/calls/web/start")
async def web_start(body: WebStartIn):
    number = norm(body.from_number)
    call_id = f"web_{uuid.uuid4().hex[:10]}"
    route = await route_for(body.user_id, number)
    url = await signed_url() if route == "screen" else None
    if route == "screen" and url is None:
        raise HTTPException(503, "ElevenLabs agent not reachable: check ELEVENLABS_API_KEY and ELEVENLABS_AGENT_ID")
    call = await live.start(call_id, number, route, body.user_id)
    if route != "screen":
        await live.finalize(call, "passed_verified" if route == "verified" else "rejected")
        return {"call_id": call_id, "route": route, "number": number}
    return {"call_id": call_id, "route": route, "number": number, "signed_url": url,
            "dynamic_variables": {"guardian_call_id": call_id, "caller_number": number}}


@router.post("/calls/web/{call_id}/end")
async def web_end(call_id: str):
    """Caller hung up or the 90 s cutoff hit before the screener decided. Safe to call twice."""
    call = live.get(call_id)
    if call is None:
        return {"ok": False}
    if call.outcome is None:
        await live.finalize(call, live.ACTION_TO_OUTCOME.get(call.final_action)
                            or risk.final_outcome(call.max_risk))
    return {"ok": True, "outcome": call.outcome}
