"""End-to-end call flows against the API (local DB, stand-in scorer, dry-run texts)."""
from backend.app import live, notify

SCAM = "+12135550199"
LEGIT = "+18185550123"

MEDICARE = [
    ("Hi, you've reached Linda's assistant. This call is recorded and screened. Who's calling?",
     "This is John from Medicare, calling about Linda's benefits."),
    ("What's a direct callback number?",
     "I can't give that out, this is urgent, she'll lose her coverage today. I need her card number."),
]
PHARMACY = [
    ("Who's calling, and what's it about?", "Hi, this is Maria from the Westwood pharmacy."),
    ("What's a direct callback number?", "Sure, it's 310 555 2000."),
    ("Can you send this by mail instead?", "Of course, it's just that her prescription is ready."),
]


def inbound(client, number, sid):
    return client.post("/calls/inbound", data={"From": number, "To": "+13105559999", "CallSid": sid})


def assess(client, call_id, number, asked, said):
    return client.post("/tools/assess", json={"call_id": call_id, "caller_number": number,
                                              "guardian_asked": asked, "caller_said": said}).json()


def test_seed_preflagged_number(client):
    n = client.get("/numbers/+12135550142").json()
    assert n["scam_score"] == 92 and n["top_reason"] == "Medicare impersonation" and not n["verified"]
    assert len(client.get("/verified").json()) == 3


def test_verified_rings_linda(client):
    r = inbound(client, "+13105550111", "CA-son")
    assert "<Dial" in r.text and "+13105550000" in r.text
    calls = client.get("/calls").json()
    assert calls[0]["call_id"] == "CA-son" and calls[0]["outcome"] == "passed_verified"


def test_known_scam_rejected(client):
    r = inbound(client, "+12135550142", "CA-rej")
    assert "<Reject" in r.text
    assert any(c["call_id"] == "CA-rej" and c["outcome"] == "rejected" for c in client.get("/calls").json())


def test_scam_call_ended_saved_and_family_texted(client):
    r = inbound(client, SCAM, "CA-scam")
    assert "<Reject" not in r.text and "+13105550000" not in r.text
    out = assess(client, "conv_scam", SCAM, *MEDICARE[0])
    assert out["action"] == "continue"
    out = assess(client, "conv_scam", SCAM, *MEDICARE[1])
    assert out["action"] == "end" and out["risk"] >= 0.7 and "mail" in out["say"]
    # ElevenLabs conversation id was linked to the Twilio call id
    assert live.get("conv_scam").id == "CA-scam"

    ev = client.get("/evidence").json()
    assert len(ev) == 1 and ev[0]["number"] == SCAM and len(ev[0]["transcript"]) == 4
    assert notify.sent[-1]["to"] == "+13105550100" and "BLOCK" in notify.sent[-1]["text"]
    assert f"http://test/e/{ev[0]['evidence_id']}" in notify.sent[-1]["text"]
    prof = client.get(f"/numbers/{SCAM}").json()
    assert prof["scam_score"] >= 30 and prof["top_reason"] == "Claims to be an official agency"
    assert client.get(f"/e/{ev[0]['evidence_id']}").status_code == 200
    assert client.get("/users/linda/safety").json()["safety_score"] == 95
    # A repeat assess after the decision gives the same answer
    assert assess(client, "conv_scam", SCAM, "?", "hello?")["action"] == "end"


def test_legit_call_connected_and_transcript_dropped(client):
    inbound(client, LEGIT, "CA-legit")
    actions = [assess(client, "conv_legit", LEGIT, a, s)["action"] for a, s in PHARMACY]
    assert actions == ["continue", "continue", "connect"]
    assert client.get("/evidence").json() == []
    assert live.get("CA-legit").transcript == []
    calls = client.get("/calls").json()
    assert calls[0]["outcome"] == "connected"
    assert client.get("/users/linda/safety").json()["unverified_connected_7d"] == 1


def test_post_call_message_kept_conversation_text_dropped(client):
    inbound(client, LEGIT, "CA-msg")
    assess(client, "conv_msg", LEGIT, "Who's calling?", "It's about an urgent matter, I'd rather not say.")
    client.post("/calls/post-call", json={"type": "post_call_transcription", "data": {
        "conversation_id": "conv_msg",
        "transcript": [{"role": "agent", "message": "Who's calling?", "time_in_call_secs": 1},
                       {"role": "user", "message": "Tell her Bob called about the roof.", "time_in_call_secs": 9}]}})
    calls = client.get("/calls").json()
    assert calls[0]["call_id"] == "CA-msg" and calls[0]["outcome"] == "message"
    assert client.get("/messages").json()[0]["text"] == "Tell her Bob called about the roof."


def test_bank_app_during_unverified_call_alerts_family(client):
    inbound(client, LEGIT, "CA-bank")
    r = client.post("/signals", json={"user_id": "linda", "kind": "bank_app_open"}).json()
    assert r == {"ok": True, "alerted": True}
    assert "banking app during" in notify.sent[-1]["text"]
    assert client.get("/users/linda/safety").json()["bank_alerts_7d"] == 1


def test_bank_app_without_call_is_quiet(client):
    assert client.post("/signals", json={"user_id": "linda", "kind": "bank_app_open"}).json()["alerted"] is False


def test_block_then_router_rejects(client):
    r = client.post("/block", json={"user_id": "linda", "number": LEGIT, "reason": "test"}).json()
    assert r["ok"] and r["scam_score"] == 10
    assert "<Reject" in inbound(client, LEGIT, "CA-blocked").text


def test_family_text_reply_block_and_safe(client):
    notify.last_alert_number["+13105550100"] = SCAM
    r = client.post("/webhooks/photon", json={"from": "+13105550100", "text": "BLOCK"}).json()
    assert r["handled"] and r["action"] == "block" and r["number"] == SCAM
    r = client.post("/webhooks/photon", json={"from": "+13105550100", "text": "SAFE"}).json()
    assert r["action"] == "safe"
    assert client.get(f"/numbers/{SCAM}").json()["verified"]


def test_verified_add_and_delete(client):
    client.post("/verified", json={"user_id": "linda", "number": "(310) 555-0177", "label": "Neighbor"})
    assert {"number": "+13105550177", "label": "Neighbor"} in client.get("/verified").json()
    client.delete("/verified/+13105550177")
    assert len(client.get("/verified").json()) == 3
