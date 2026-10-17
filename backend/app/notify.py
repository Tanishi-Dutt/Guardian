"""Family texts. Photon first, Twilio SMS fallback, log-only when neither is configured."""
import asyncio
import logging

import httpx

from . import config as C

log = logging.getLogger(__name__)
sent: list[dict] = []          # last texts, for tests and the demo console
last_alert_number: dict[str, str] = {}   # trusted phone -> number in the last alert (for BLOCK / SAFE)


async def _photon(to: str, text: str):
    # TODO(A): confirm Photon's send API at the event; this posts {to, from, text} with a bearer key.
    async with httpx.AsyncClient(timeout=5) as client:
        r = await client.post(C.PHOTON_SEND_URL, headers={"Authorization": f"Bearer {C.PHOTON_API_KEY}"},
                              json={"to": to, "from": C.PHOTON_FROM or None, "text": text})
        r.raise_for_status()


def _twilio_sms(to: str, text: str):
    from twilio.rest import Client
    Client(C.TWILIO_ACCOUNT_SID, C.TWILIO_AUTH_TOKEN).messages.create(to=to, from_=C.TWILIO_SMS_FROM, body=text)


async def send_text(to: str, text: str, number: str | None = None) -> str:
    """Returns the channel used: photon | twilio | dry_run | failed."""
    if number:
        last_alert_number[to] = number
    channel = "dry_run"
    try:
        if C.PHOTON_API_KEY and C.PHOTON_SEND_URL:
            await _photon(to, text)
            channel = "photon"
        elif C.TWILIO_ACCOUNT_SID and C.TWILIO_AUTH_TOKEN and C.TWILIO_SMS_FROM:
            await asyncio.to_thread(_twilio_sms, to, text)
            channel = "twilio"
        else:
            log.warning("No Photon/Twilio keys; would text %s: %s", to, text)
    except Exception:
        log.exception("family text to %s failed", to)
        channel = "failed"
    sent.append({"to": to, "text": text, "channel": channel})
    del sent[:-50]
    return channel
