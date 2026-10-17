"""Stand-in scam scorer (owned by Person B — replace the internals, keep the signature).

Contract: CONTRACTS.md section 5. Keyword rules only, so Person A can build the
whole call flow before the real step-5-preview / fine-tuned scorer lands.
"""
import logging
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


def score(transcript, call_id=None):
    """transcript: [{"speaker": "guardian"|"caller", "text": str, "t": float}, ...]"""
    start = time.perf_counter()
    try:
        text = " ".join(
            turn.get("text", "") for turn in transcript if turn.get("speaker") == "caller"
        ).lower()
        risk, stage_idx, flags = 0.0, 0, []
        for stage, weight, flag, words in RULES:
            if any(w in text for w in words):
                risk += weight
                stage_idx = max(stage_idx, STAGES.index(stage))
                if flag not in flags:
                    flags.append(flag)
        risk = round(min(risk, 1.0), 2)
        return {
            "risk": risk,
            "stage": STAGES[stage_idx],
            "red_flags": flags[:5],
            "action": "end" if risk >= END_THRESHOLD else "continue",
            "model": "stub",
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
