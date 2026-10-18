"""Browser phone: /calls/web/start routes like /calls/inbound, /calls/web/{id}/end decides once."""


def web_calls(client):
    return [c for c in client.get("/calls").json() if c["call_id"].startswith("web_")]


def test_verified_and_rejected_routes(client):
    son = client.post("/calls/web/start", json={"from_number": "+13105550111"}).json()
    assert son["route"] == "verified"
    scam = client.post("/calls/web/start", json={"from_number": "(213) 555-0142"}).json()
    assert scam["route"] == "rejected" and scam["number"] == "+12135550142"
    outcomes = {c["number"]: c["outcome"] for c in web_calls(client)}
    assert outcomes == {"+13105550111": "passed_verified", "+12135550142": "rejected"}


def test_screen_without_elevenlabs_is_503_and_logs_nothing(client):
    r = client.post("/calls/web/start", json={"from_number": "+12135550177"})
    assert r.status_code == 503
    assert web_calls(client) == []


def test_end_after_scam_assess(client):
    cid = "web_test1"
    for said in ("This is John from Medicare.", "I can't give a callback number, it's urgent.",
                 "I just need to verify her card number."):
        out = client.post("/tools/assess", json={"call_id": cid, "caller_number": "+12135550177",
                                                 "guardian_asked": "Who is calling?", "caller_said": said}).json()
    assert out["action"] == "end"
    assert client.post(f"/calls/web/{cid}/end").json() == {"ok": True, "outcome": "ended_scam"}
    assert client.post(f"/calls/web/{cid}/end").json()["outcome"] == "ended_scam"   # idempotent
    assert client.post("/calls/web/unknown/end").json() == {"ok": False}
