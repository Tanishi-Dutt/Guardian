"""Profiles, verified list, blocking, safety score and the evidence log (CONTRACTS section 8)."""
import html

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from .. import config as C
from .. import db, events, live, risk
from .calls import norm

router = APIRouter()


class VerifiedIn(BaseModel):
    user_id: str = C.DEMO_USER_ID
    number: str
    label: str = ""


class BlockIn(BaseModel):
    user_id: str = C.DEMO_USER_ID
    number: str
    reason: str = "Blocked by family"


def iso(v):
    return v.isoformat() if v else None


def profile_updated(p: dict, user_id: str):
    events.publish("profile_updated", {"number": p["number"], "scam_score": p["scam_score"],
                                       "top_reason": p["top_reason"]}, None, user_id)


@router.get("/numbers/{number}")
async def get_number(number: str, user_id: str = C.DEMO_USER_ID):
    number = norm(number)
    p = await risk.get_profile(number)
    label = await db.fetchval(
        "SELECT label FROM verified_numbers WHERE user_id = $1 AND number = $2", user_id, number)
    return {"number": number, "scam_score": p["scam_score"], "label": label, "verified": label is not None,
            "users_called_24h": p["users_called_24h"], "flagged_by": p["flagged_by"],
            "top_reason": p["top_reason"], "first_seen": iso(p["first_seen"])}


@router.get("/verified")
async def list_verified(user_id: str = C.DEMO_USER_ID):
    return await db.fetch(
        "SELECT number, label FROM verified_numbers WHERE user_id = $1 ORDER BY label", user_id)


async def add_verified(user_id: str, number: str, label: str, added_by: str = "family") -> dict:
    number = norm(number)
    await db.execute(
        """INSERT INTO verified_numbers (user_id, number, label, added_by) VALUES ($1, $2, $3, $4)
           ON CONFLICT (user_id, number) DO UPDATE SET label = EXCLUDED.label""",
        user_id, number, label or live.pretty(number), added_by)
    await db.execute("DELETE FROM blocked_numbers WHERE user_id = $1 AND number = $2", user_id, number)
    p = await risk.recompute_profile(number)
    profile_updated(p, user_id)
    return p


@router.post("/verified")
async def post_verified(body: VerifiedIn):
    await add_verified(body.user_id, body.number, body.label)
    return {"ok": True}


@router.delete("/verified/{number}")
async def delete_verified(number: str, user_id: str = C.DEMO_USER_ID):
    number = norm(number)
    await db.execute("DELETE FROM verified_numbers WHERE user_id = $1 AND number = $2", user_id, number)
    profile_updated(await risk.recompute_profile(number), user_id)
    return {"ok": True}


async def block_number(user_id: str, number: str, reason: str) -> dict:
    """Risk rule 5: a family flag blocks the number for this user and raises its score for everyone."""
    number = norm(number)
    already = await db.fetchval(
        "SELECT 1 FROM blocked_numbers WHERE user_id = $1 AND number = $2", user_id, number)
    await db.execute(
        """INSERT INTO blocked_numbers (user_id, number, reason) VALUES ($1, $2, $3)
           ON CONFLICT (user_id, number) DO UPDATE SET reason = EXCLUDED.reason""", user_id, number, reason)
    await db.execute("DELETE FROM verified_numbers WHERE user_id = $1 AND number = $2", user_id, number)
    if not already:
        await db.execute(
            """INSERT INTO number_profiles (number, first_seen, flagged_by) VALUES ($1, now(), 1)
               ON CONFLICT (number) DO UPDATE SET flagged_by = number_profiles.flagged_by + 1""", number)
    p = await risk.recompute_profile(number)
    profile_updated(p, user_id)
    return p


@router.post("/block")
async def post_block(body: BlockIn):
    p = await block_number(body.user_id, body.number, body.reason)
    return {"ok": True, "scam_score": p["scam_score"]}


@router.get("/users/{user_id}/safety")
async def get_safety(user_id: str):
    return await risk.user_safety(user_id)


@router.get("/evidence")
async def list_evidence(user_id: str = C.DEMO_USER_ID):
    rows = await db.fetch(
        """SELECT evidence_id, number, ts, recording_url, transcript, red_flags, score
           FROM scam_evidence WHERE user_id = $1 AND delete_after > now() ORDER BY ts DESC""", user_id)
    for r in rows:
        r["ts"] = iso(r["ts"])
    return rows


@router.get("/messages")
async def list_messages(user_id: str = C.DEMO_USER_ID):
    rows = await db.fetch("SELECT call_id, number, ts, text FROM messages WHERE user_id = $1 ORDER BY ts DESC",
                          user_id)
    for r in rows:
        r["ts"] = iso(r["ts"])
    return rows


@router.get("/e/{evidence_id}/audio")
async def evidence_audio(evidence_id: str):
    path = C.RECORDINGS_DIR / f"{evidence_id}.mp3"
    if not evidence_id.isalnum() or not path.exists():
        raise HTTPException(404, "recording not found")
    return FileResponse(path, media_type="audio/mpeg")


@router.get("/e/{evidence_id}", response_class=HTMLResponse)
async def evidence_page(evidence_id: str):
    """The link in the family text: recording, transcript and red flags for one scam call."""
    ev = await db.fetchrow("SELECT * FROM scam_evidence WHERE evidence_id = $1", evidence_id)
    if not ev:
        raise HTTPException(404, "evidence not found")
    score = await db.fetchval("SELECT scam_score FROM number_profiles WHERE number = $1", ev["number"])
    turns = "".join(
        f"<p><b>{'Guardian' if t['speaker'] == 'guardian' else 'Caller'}</b> "
        f"<small>{t.get('t', 0):.0f}s</small><br>{html.escape(t['text'])}</p>" for t in ev["transcript"] or [])
    flags = "".join(f"<li>{html.escape(f)}</li>" for f in ev["red_flags"] or [])
    audio = f'<audio controls src="{html.escape(ev["recording_url"])}"></audio>' if ev["recording_url"] else \
        "<p><i>Recording is being saved…</i></p>"
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Guardian evidence</title>
<style>body{{font:18px system-ui;max-width:640px;margin:24px auto;padding:0 16px;color:#222}}
h1{{color:#b42318}}audio{{width:100%}}small{{color:#888}}</style></head><body>
<h1>Scam call blocked</h1>
<p>{html.escape(live.pretty(ev['number']))} · {ev['ts']:%b %d, %I:%M %p} UTC · scam score <b>{score}/100</b></p>
{audio}<h3>Red flags</h3><ul>{flags}</ul><h3>Transcript</h3>{turns}
<p><small>Kept for 90 days as evidence. Report at reportfraud.ftc.gov.</small></p></body></html>"""
