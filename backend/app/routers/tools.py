"""POST /tools/assess: the voice agent calls this after every caller answer (CONTRACTS section 6)."""
import asyncio
import logging

import sentry_sdk
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

from ml.scorer import score

from .. import config as C
from .. import events, live, risk
from .calls import norm

log = logging.getLogger(__name__)
router = APIRouter()


class AssessIn(BaseModel):
    call_id: str
    caller_number: str | None = None
    guardian_asked: str | None = ""
    caller_said: str | None = ""


async def run_scorer(transcript: list, call_id: str) -> dict:
    with sentry_sdk.start_span(op="scorer", name="ml.scorer.score") as span:
        try:
            result = await asyncio.wait_for(asyncio.to_thread(score, list(transcript), call_id),
                                            C.SCORER_TIMEOUT_S)
        except asyncio.TimeoutError:
            log.warning("scorer timed out for %s", call_id)
            result = {"risk": 0.0, "stage": "none", "red_flags": [], "action": "continue",
                      "model": "timeout", "latency_ms": int(C.SCORER_TIMEOUT_S * 1000)}
        span.set_data("risk", result.get("risk"))
        span.set_data("model", result.get("model"))
        return result


@router.post("/tools/assess")
async def assess(body: AssessIn, background: BackgroundTasks):
    call = await live.resolve(body.call_id, norm(body.caller_number) if body.caller_number else None)
    if call.final_action:  # already decided; repeat the same answer
        return {"action": call.final_action, "risk": round(call.max_risk, 2), "say": C.SAY[call.final_action]}

    live.add_turn(call, "guardian", (body.guardian_asked or "").strip())
    live.add_turn(call, "caller", (body.caller_said or "").strip())

    result = await run_scorer(call.transcript, call.id)
    r = float(result.get("risk") or 0)
    call.max_risk = max(call.max_risk, r)
    for flag in result.get("red_flags") or []:
        if flag not in call.red_flags:
            call.red_flags.append(flag)
    events.publish("score", {"risk": round(r, 2), "stage": result.get("stage", "none"),
                             "red_flags": result.get("red_flags") or [], "model": result.get("model"),
                             "latency_ms": result.get("latency_ms")}, call.id, call.user_id)

    action = risk.decide(call.max_risk, call.caller_turns, call.seconds)
    if action != "continue":
        call.final_action = action
        # Logging, scores, evidence and the family text happen after the agent has its answer.
        background.add_task(live.finalize, call, live.ACTION_TO_OUTCOME[action])
    return {"action": action, "risk": round(call.max_risk, 2), "say": C.SAY[action]}
