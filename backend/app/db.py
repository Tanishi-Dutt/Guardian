"""asyncpg pool, schema, demo seed and reset."""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import asyncpg

from . import config

log = logging.getLogger(__name__)
SCHEMA = Path(__file__).resolve().parents[1] / "db" / "schema.sql"
TABLES = ["events", "call_logs", "number_profiles", "scam_evidence", "signals", "messages",
          "blocked_numbers", "verified_numbers", "trusted_contacts", "users"]

pool: asyncpg.Pool | None = None


async def _init_conn(conn):
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def connect():
    global pool
    for attempt in range(1, 4):  # slow venue Wi-Fi can time out the TLS handshake to Tiger Cloud
        try:
            pool = await asyncpg.create_pool(config.DATABASE_URL, min_size=3, max_size=10, timeout=30,
                                             command_timeout=15, init=_init_conn)
            break
        except (OSError, asyncio.TimeoutError) as e:
            if attempt == 3:
                raise
            log.warning("database connect attempt %d failed (%s); retrying", attempt, type(e).__name__)
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA.read_text())
        if not await conn.fetchval("SELECT 1 FROM users WHERE id = $1", config.DEMO_USER_ID):
            await seed(conn)


async def close():
    if pool:
        await pool.close()


async def fetch(sql, *args):
    return [dict(r) for r in await pool.fetch(sql, *args)]


async def fetchrow(sql, *args):
    row = await pool.fetchrow(sql, *args)
    return dict(row) if row else None


async def fetchval(sql, *args):
    return await pool.fetchval(sql, *args)


async def execute(sql, *args):
    return await pool.execute(sql, *args)


async def reset():
    async with pool.acquire() as conn:
        await conn.execute(f"TRUNCATE {', '.join(TABLES)}")
        await seed(conn)


def last_local_hour(hour: int) -> datetime:
    """Most recent past occurrence of `hour`:00 local time, as UTC."""
    tz = ZoneInfo(config.LOCAL_TZ)
    now = datetime.now(tz)
    t = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if t > now:
        t -= timedelta(days=1)
    return t.astimezone(timezone.utc)


async def seed(conn):
    """Linda, her trusted contact and verified list, a little call history, and the pre-flagged
    scam number (CONTRACTS section 4). The scam number's call pattern is real data, so its score
    is computed by the same formula as every other number (lands on 92)."""
    from .risk import recompute_profile  # avoid import cycle

    uid = config.DEMO_USER_ID
    now = datetime.now(timezone.utc)
    await conn.execute(
        "INSERT INTO users (id, name, guardian_number, real_phone) VALUES ($1, $2, $3, $4)",
        uid, config.DEMO_USER_NAME, config.GUARDIAN_NUMBER or None, config.LINDA_PHONE or None)
    if config.TRUSTED_PHONE:
        await conn.execute("INSERT INTO trusted_contacts VALUES ($1, $2, $3)",
                           uid, config.TRUSTED_NAME, config.TRUSTED_PHONE)
    await conn.executemany(
        "INSERT INTO verified_numbers (user_id, number, label, added_by) VALUES ($1, $2, $3, 'family')",
        [(uid, n, label) for n, label in config.VERIFIED_SEED])

    # A normal week for Linda: verified calls ring through.
    history = [
        ("+13105550111", 3, 412), ("+13105550199", 2, 95), ("+13105550123", 1, 40),
        ("+13105550111", 1, 630),
    ]
    await conn.executemany(
        "INSERT INTO call_logs VALUES ($1, $2, $3, $4, $5, 'passed_verified', false, 0)",
        [(f"seed-l{i}", uid, n, now - timedelta(days=d, hours=i), s)
         for i, (n, d, s) in enumerate(history)])

    # Pre-flagged scam number: 6 users, 12 s each, around 3 AM, flagged by 3 families,
    # live risk 0.82 on an earlier screened call.
    scam = config.PREFLAGGED_NUMBER
    t0 = last_local_hour(3)
    await conn.executemany(
        "INSERT INTO call_logs VALUES ($1, $2, $3, $4, 12, 'ended_scam', true, 0.82)",
        [(f"seed-s{i}", f"u{i:02d}", scam, t0 + timedelta(minutes=4 * i)) for i in range(1, 7)])
    await conn.execute(
        "INSERT INTO number_profiles (number, first_seen, flagged_by, max_live_risk, top_reason) "
        "VALUES ($1, $2, 3, 0.82, $3)", scam, t0, config.PREFLAGGED_REASON)
    for n, _ in config.VERIFIED_SEED:
        await conn.execute("INSERT INTO number_profiles (number, first_seen) VALUES ($1, $2)",
                           n, now - timedelta(days=60))
    for n in [scam] + [n for n, _ in config.VERIFIED_SEED]:
        await recompute_profile(n, conn=conn)
