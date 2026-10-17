"""Play a fake call through the real API, the same way Twilio + ElevenLabs would.

    python backend/scripts/simulate_call.py medicare          # scam, ends early
    python backend/scripts/simulate_call.py pharmacy          # legit, connected
    python backend/scripts/simulate_call.py son               # verified, rings through
    python backend/scripts/simulate_call.py medicare --base https://api.yourdomain.com --delay 3

Watch the dashboard (or `curl -N localhost:8000/stream/live`) while it runs.
"""
import argparse
import time
import uuid

import httpx

SCRIPTS = {
    "medicare": ("+12135550177", [
        ("Hi, you've reached Linda's assistant. This call is recorded and screened. Who's calling, and what's it about?",
         "Hello, this is John Miller from Medicare. Linda's benefits are about to be suspended."),
        ("Which department exactly? What's the direct callback number?",
         "I can't give that out, this is urgent, she needs to act today."),
        ("Linda doesn't handle account details by phone. Can you send this by mail?",
         "No, there's no time. I just need to verify her card number and she'll keep her coverage."),
    ]),
    "pharmacy": ("+18185550123", [
        ("Hi, you've reached Linda's assistant. This call is recorded and screened. Who's calling, and what's it about?",
         "Hi, this is Maria from Westwood Pharmacy, her prescription is ready for pickup."),
        ("What's a direct callback number?", "Sure, it's 310 555 2000, that's the pharmacy counter."),
        ("Could you send a reminder by mail instead?", "Of course, no problem. We just wanted to let her know."),
    ]),
    "son": ("+13105550111", []),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("script", choices=SCRIPTS)
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--delay", type=float, default=1.5, help="seconds between caller answers")
    ap.add_argument("--number", help="override caller number")
    a = ap.parse_args()

    number, turns = SCRIPTS[a.script]
    number = a.number or number
    sid = f"SIM{uuid.uuid4().hex[:10]}"
    with httpx.Client(base_url=a.base, timeout=10) as c:
        r = c.post("/calls/inbound", data={"From": number, "To": "+10000000000", "CallSid": sid})
        print(f"inbound {number} -> {r.status_code}\n{r.text}\n")
        for asked, said in turns:
            time.sleep(a.delay)
            t0 = time.perf_counter()
            out = c.post("/tools/assess", json={"call_id": f"conv_{sid}", "caller_number": number,
                                                "guardian_asked": asked, "caller_said": said}).json()
            ms = (time.perf_counter() - t0) * 1000
            print(f"GUARDIAN: {asked}\nCALLER:   {said}\n  -> {out['action']} risk={out['risk']} ({ms:.0f} ms)\n")
            if out["action"] != "continue":
                if out["say"]:
                    print(f"GUARDIAN: {out['say']}")
                break
        time.sleep(0.5)
        print("profile:", c.get(f"/numbers/{number}").json())


if __name__ == "__main__":
    main()
