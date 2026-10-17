"""GET /stream/live: server-sent events for the dashboard (CONTRACTS section 7)."""
import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .. import events

router = APIRouter()
KEEPALIVE_S = 15


@router.get("/stream/live")
async def stream_live(request: Request, user_id: str | None = None):
    q = events.subscribe()

    async def gen():
        try:
            yield ": connected\n\n"
            while not await request.is_disconnected():
                try:
                    ev = await asyncio.wait_for(q.get(), KEEPALIVE_S)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                if user_id and ev["user_id"] != user_id:
                    continue
                yield f"event: {ev['type']}\ndata: {json.dumps(ev, default=str)}\n\n"
        finally:
            events.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
