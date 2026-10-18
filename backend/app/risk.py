"""Risk engine: live-call decisions, number scam scores, Linda's safety score.

The formulas are pure functions (tested in backend/tests); the async helpers gather the facts
from Tiger Data and store the results.
"""
import math

from . import config as C
from . import db


# ---------------------------------------------------------------- live call decision (section 6)
def decide(risk: float, caller_turns: int, seconds: float) -> str:
    """Return continue | end | connect | message."""
    if risk >= C.END_RISK:
        return "end"
    if seconds >= C.HARD_STOP_SECONDS or caller_turns >= C.DECIDE_AFTER_TURNS \
            or seconds >= C.DECIDE_AFTER_SECONDS:
        return "connect" if risk < C.CONNECT_RISK else "message"
    return "continue"


def final_outcome(max_risk: float) -> str:
    """Outcome for a call that ended before the screener decided (caller hung up, 90 s cutoff)."""
    return "ended_scam" if max_risk >= C.END_RISK else "message"


# ---------------------------------------------------------------- number scam score (section 10)
def number_score(max_live_risk=0.0, flagged_by=0, users_24h=0, short_calls_24h=0,
                 odd_hour_calls_24h=0, verified_anywhere=False) -> int:
    s = C.W_LIVE_RISK * (max_live_risk or 0)
    s += min(C.W_PER_FLAG * (flagged_by or 0), C.W_FLAG_MAX)
    if users_24h >= C.MANY_USERS_N:
        s += C.W_MANY_USERS
    if short_calls_24h >= C.SHORT_CALLS_N:
        s += C.W_SHORT_CALLS
    if odd_hour_calls_24h > 0:
        s += C.W_ODD_HOURS
    if verified_anywhere:
        s += C.W_VERIFIED
    return max(0, min(100, math.floor(s + 0.5)))  # round half up, like the slide


FACTS_SQL = f"""
SELECT
  count(*) FILTER (WHERE ts > now() - interval '24 hours')                    AS calls_24h,
  count(DISTINCT user_id) FILTER (WHERE ts > now() - interval '24 hours')     AS users_24h,
  count(*) FILTER (WHERE ts > now() - interval '24 hours'
                   AND seconds < {C.SHORT_CALL_S})                            AS short_calls_24h,
  count(*) FILTER (WHERE ts > now() - interval '24 hours'
                   AND (extract(hour FROM ts AT TIME ZONE '{C.LOCAL_TZ}') >= {C.ODD_HOURS_START}
                     OR extract(hour FROM ts AT TIME ZONE '{C.LOCAL_TZ}') < {C.ODD_HOURS_END}))
                                                                              AS odd_hour_calls_24h,
  count(*)                                                                    AS total_calls,
  min(ts)                                                                     AS first_seen,
  coalesce(max(max_risk), 0)                                                  AS max_risk
FROM call_logs WHERE number = $1
"""


async def recompute_profile(number: str, conn=None) -> dict:
    """Rebuild one number's profile from call history and store it. Returns the profile row."""
    q = conn or db.pool
    f = dict(await q.fetchrow(FACTS_SQL, number))
    prof = await q.fetchrow("SELECT * FROM number_profiles WHERE number = $1", number)
    prof = dict(prof) if prof else {}
    verified_label = await q.fetchval(
        "SELECT label FROM verified_numbers WHERE number = $1 LIMIT 1", number)
    flagged_by = prof.get("flagged_by") or 0
    max_live = max(prof.get("max_live_risk") or 0, f["max_risk"] or 0)
    score = number_score(max_live, flagged_by, f["users_24h"], f["short_calls_24h"],
                         f["odd_hour_calls_24h"], verified_label is not None)

    if verified_label:
        reason = f"Verified: {verified_label}"
    elif prof.get("top_reason") and not prof["top_reason"].startswith("Verified"):
        reason = prof["top_reason"]
    elif flagged_by:
        reason = f"Flagged by {flagged_by} Guardian families"
    elif f["users_24h"] >= C.MANY_USERS_N:
        reason = f"Called {f['users_24h']} Guardian users in 24 h"
    elif f["short_calls_24h"] >= C.SHORT_CALLS_N:
        reason = "Many very short calls"
    else:
        reason = None

    first_seen = prof.get("first_seen") or f["first_seen"]
    row = await q.fetchrow(
        """INSERT INTO number_profiles
             (number, first_seen, total_calls, users_called_24h, flagged_by, max_live_risk, scam_score, top_reason)
           VALUES ($1, coalesce($2, now()), $3, $4, $5, $6, $7, $8)
           ON CONFLICT (number) DO UPDATE SET
             first_seen = coalesce(number_profiles.first_seen, EXCLUDED.first_seen),
             total_calls = EXCLUDED.total_calls, users_called_24h = EXCLUDED.users_called_24h,
             flagged_by = EXCLUDED.flagged_by, max_live_risk = EXCLUDED.max_live_risk,
             scam_score = EXCLUDED.scam_score, top_reason = EXCLUDED.top_reason
           RETURNING *""",
        number, first_seen, f["total_calls"], f["users_24h"], flagged_by, max_live, score, reason)
    return dict(row)


async def get_profile(number: str) -> dict:
    row = await db.fetchrow("SELECT * FROM number_profiles WHERE number = $1", number)
    return row or {"number": number, "scam_score": 0, "users_called_24h": 0, "flagged_by": 0,
                   "top_reason": None, "first_seen": None, "total_calls": 0, "max_live_risk": 0}


# ---------------------------------------------------------------- safety score (section 10)
def safety_score(unverified_connected=0, scam_screened=0, bank_alerts=0) -> int:
    s = 100 + C.SAFETY_UNVERIFIED_CONNECTED * unverified_connected \
        + C.SAFETY_SCAM_SCREENED * scam_screened + C.SAFETY_BANK_ALERT * bank_alerts
    return max(0, min(100, s))


async def user_safety(user_id: str) -> dict:
    row = await db.fetchrow(
        """SELECT
             count(*) FILTER (WHERE outcome = 'connected' AND screened)  AS unverified_connected,
             count(*) FILTER (WHERE outcome = 'ended_scam')              AS scam_screened,
             count(*) FILTER (WHERE outcome IN ('ended_scam', 'rejected')) AS blocked
           FROM call_logs WHERE user_id = $1 AND ts > now() - interval '7 days'""", user_id)
    bank = await db.fetchval(
        """SELECT count(*) FROM signals WHERE user_id = $1 AND kind = 'bank_alert'
           AND ts > now() - interval '7 days'""", user_id)
    return {
        "safety_score": safety_score(row["unverified_connected"], row["scam_screened"], bank),
        "scam_calls_blocked_7d": row["blocked"],
        "unverified_connected_7d": row["unverified_connected"],
        "bank_alerts_7d": bank,
    }
