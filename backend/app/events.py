"""Dashboard event bus (CONTRACTS section 7): fan out to SSE subscribers, persist to `events`."""
import asyncio
import logging
from datetime import datetime, timezone

from . import config, db

log = logging.getLogger(__name__)
_subscribers: set[asyncio.Queue] = set()
_pending: set[asyncio.Task] = set()


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=500)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue):
    _subscribers.discard(q)


async def _persist(ev):
    try:
        await db.execute("INSERT INTO events (call_id, user_id, ts, type, data) VALUES ($1, $2, $3, $4, $5)",
                         ev["call_id"], ev["user_id"], datetime.fromisoformat(ev["ts"]), ev["type"], ev["data"])
    except Exception:
        log.exception("failed to persist event %s", ev["type"])


def publish(type_: str, data: dict, call_id: str | None = None, user_id: str = config.DEMO_USER_ID) -> dict:
    ev = {"type": type_, "call_id": call_id, "user_id": user_id,
          "ts": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
          "data": data}
    for q in list(_subscribers):
        try:
            q.put_nowait(ev)
        except asyncio.QueueFull:
            pass  # slow dashboard tab; drop rather than block the call
    task = asyncio.get_running_loop().create_task(_persist({**ev, "ts": ev["ts"].replace("Z", "+00:00")}))
    _pending.add(task)
    task.add_done_callback(_pending.discard)
    return ev


async def flush():
    """Wait for pending event writes (tests, reset)."""
    if _pending:
        await asyncio.gather(*list(_pending), return_exceptions=True)
