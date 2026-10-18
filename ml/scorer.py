"""Live scam scorer (CONTRACTS.md section 5): Claude reads the call so far; keyword rules back it up.

score() never raises. Claude Haiku judges the whole conversation (who the caller claims to be, what
they want, pressure, secrecy, payment or account requests). The keyword rules below run on every
call too, so a slow or failed API call still yields a score. Set ANTHROPIC_API_KEY to enable Claude;
SCORER_MODEL overrides the model.
"""
import json
import logging
import os
import time

log = logging.getLogger(__name__)

STAGES = ["none", "hook", "authority", "urgency", "isolation", "payment_or_info"]

# (stage, weight, red flag, keywords)
RULES = [
    ("authority", 0.25, "claims to be an official agency",
     ["medicare", "irs", "social security", "fraud department", "government", "police", "sheriff"]),
    ("authority", 0.15, "claims to be tech support",
     ["microsoft", "apple support", "tech support", "your computer", "virus"]),
    ("urgency", 0.2, "creates urgency or threats",
     ["urgent", "immediately", "right now", "today only", "lose her", "lose your",
      "suspended", "arrest", "warrant", "shut off", "shutoff", "final notice"]),
    ("isolation", 0.2, "asks to keep it secret",
     ["don't tell", "do not tell", "keep this between", "secret", "don't hang up"]),
    ("payment_or_info", 0.45, "asks for payment or account details",
     ["card number", "gift card", "wire", "bitcoin", "crypto", "account number",
      "routing number", "social security number", "ssn", "pin", "password", "verify her card",
      "zelle", "western union"]),
    ("hook", 0.1, "prize or windfall hook",
     ["you've won", "you have won", "prize", "lottery", "sweepstakes", "refund"]),
    ("hook", 0.25, "refuses callback number or ID",
     ["can't give", "cannot give", "no callback", "don't have an id", "i can't share"]),
]

END_THRESHOLD = 0.7
MODEL = os.getenv("SCORER_MODEL", "claude-haiku-5-5")
CLAUDE_TIMEOUT_S = float(os.getenv("SCORER_CLAUDE_TIMEOUT_S", "6"))

SYSTEM = """You are the scam detector inside Guardian, a call firewall protecting Linda, 78.
You read a live phone call transcript (LINDA and CALLER) and judge how likely it is that the CALLER is
running a scam, based on everything said so far.

Raise risk for: claiming to be a government agency, tax office, police, Medicare, Social Security, a bank
or fraud department, tech support, a utility, or a relative in trouble; threats (arrest, fines, cut-off,
lost benefits); urgency or "today only"; secrecy ("don't tell anyone"); asking for money, fees, gift
cards, wire transfers, crypto, card or account numbers, SSN, PINs, passwords or one-time codes; refusing
or dodging a callback number, name, ID or a letter by mail; prizes or windfalls that need a payment first.
Ordinary callers (doctor's office, pharmacy, delivery, family, contractors, surveys) who answer questions
plainly and ask for no money or private data are low risk.

risk: 0.0-1.0. Use >= 0.7 once the caller asks for payment or sensitive info under a false identity or
pressure. Use 0.4-0.7 for strong signs without the ask yet. Keep legit callers under 0.3.
stage: furthest scam stage reached: none, hook, authority, urgency, isolation, payment_or_info.
red_flags: up to 4 short phrases (under 6 words each) describing what the caller did, e.g.
"claims to be tax office", "demands $2,000 payment". Empty when there are none."""

SCHEMA = {
    "type": "object",
    "properties": {
        "risk": {"type": "number"},
        "stage": {"type": "string", "enum": STAGES},
        "red_flags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["risk", "stage", "red_flags"],
    "additionalProperties": False,
}

_client = None


def _anthropic():
    global _client
    if _client is None and os.getenv("ANTHROPIC_API_KEY"):
        import anthropic
        _client = anthropic.Anthropic(timeout=CLAUDE_TIMEOUT_S, max_retries=1)
    return _client


def _keywords(transcript) -> dict:
    text = " ".join(t.get("text", "") for t in transcript if t.get("speaker") == "caller").lower()
    risk, stage_idx, flags = 0.0, 0, []
    for stage, weight, flag, words in RULES:
        if any(w in text for w in words):
            risk += weight
            stage_idx = max(stage_idx, STAGES.index(stage))
            if flag not in flags:
                flags.append(flag)
    return {"risk": round(min(risk, 1.0), 2), "stage": STAGES[stage_idx], "red_flags": flags}


def _claude(transcript) -> dict | None:
    client = _anthropic()
    if client is None:
        return None
    lines = "\n".join(f"{'CALLER' if t.get('speaker') == 'caller' else 'LINDA'}: {t.get('text', '')}"
                      for t in transcript if t.get("text"))
    resp = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM,
        messages=[{"role": "user", "content": f"Transcript so far:\n{lines}"}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
    )
    if resp.stop_reason != "end_turn":
        log.warning("scorer stop_reason %s", resp.stop_reason)
        return None
    data = json.loads(next(b.text for b in resp.content if b.type == "text"))
    stage = data.get("stage") if data.get("stage") in STAGES else "none"
    return {"risk": max(0.0, min(1.0, float(data.get("risk") or 0))), "stage": stage,
            "red_flags": [str(f) for f in data.get("red_flags") or []]}


def score(transcript, call_id=None):
    """transcript: [{"speaker": "guardian"|"caller", "text": str, "t": float}, ...]"""
    start = time.perf_counter()
    try:
        kw = _keywords(transcript)
        model = "stub"
        try:
            ai = _claude(transcript)
        except Exception:
            log.exception("Claude scorer failed for call %s; using keyword rules", call_id)
            ai = None
        result = kw
        if ai is not None:
            model = MODEL
            flags = ai["red_flags"] + [f for f in kw["red_flags"] if f not in ai["red_flags"]]
            stage = max(ai["stage"], kw["stage"], key=STAGES.index)
            result = {"risk": round(max(ai["risk"], kw["risk"]), 2), "stage": stage, "red_flags": flags}
        return {
            "risk": result["risk"],
            "stage": result["stage"],
            "red_flags": result["red_flags"][:5],
            "action": "end" if result["risk"] >= END_THRESHOLD else "continue",
            "model": model,
            "latency_ms": int((time.perf_counter() - start) * 1000),
        }
    except Exception:
        log.exception("scorer failed for call %s", call_id)
        return {
            "risk": 0.0,
            "stage": "none",
            "red_flags": [],
            "action": "continue",
            "model": "error",
            "latency_ms": int((time.perf_counter() - start) * 1000),
        }
