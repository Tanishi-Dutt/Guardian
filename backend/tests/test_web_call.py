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


def test_family_gets_one_heads_up_before_the_scam_text(client):
    from backend.app import notify
    cid, ask = "web_warn1", {"caller_number": "+12135550178", "guardian_asked": "Who is calling?"}
    lines = ("This is John from Medicare, her benefits are suspended.",
             "It's about her benefits, please hold.",
             "I just need to verify her card number, this is urgent.")
    for said in lines:
        client.post("/tools/assess", json={"call_id": cid, "caller_said": said, **ask})
    texts = [s["text"] for s in notify.sent if "(213) 555-0178" in s["text"]]
    assert len(texts) == 2
    assert "Heads up" in texts[0] and "Blocked" in texts[1]


def test_listen_scores_every_turn_and_ends_on_scam(client):
    from backend.app import live, notify
    call = client.portal.call(live.start, "web_listen1", "+12135550179", "screen")
    turn = lambda a, c: client.post(f"/calls/web/{call.id}/turn", json={"agent_said": a, "caller_said": c}).json()
    assert turn("Hello? Who's this?", "Hi, lovely weather today.")["action"] == "continue"
    out = turn("Oh? Who is calling?", "This is John from Medicare, her benefits are suspended.")
    assert out["action"] == "continue" and out["risk"] >= 0.4
    out = turn("What do you need?", "I need her card number right now, it's urgent.")
    assert out["action"] == "end" and out["risk"] >= 0.7
    assert turn("Hello?", "Still there?")["action"] == "end"   # stays ended
    texts = [s["text"] for s in notify.sent if "(213) 555-0179" in s["text"]]
    assert len(texts) == 2 and "Heads up" in texts[0] and "Blocked" in texts[1]
    assert {c["call_id"]: c["outcome"] for c in web_calls(client)}["web_listen1"] == "ended_scam"
    assert client.post("/calls/web/nope/turn", json={"caller_said": "hi"}).status_code == 404

