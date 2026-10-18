"""Generate screener-call transcripts with Claude to top the dataset up to 2,500 calls.

Each transcript is a call between a caller and Guardian's screener ("Agent"), so the model learns
how scammers react when questioned (dodging, pressure, refusing a callback number) and how legit
callers answer the same questions. Same JSONL schema as ml/transcripts.jsonl:
  {script, label: scam|legit, turns: [{speaker: Caller|Agent, text, t_seconds, stage}], source}

Targets (build plan): 1,500 scam + 1,000 legit overall. Existing rows in ml/transcripts.jsonl are
counted, and this script appends only the shortfall to the same file. Re-running resumes where
it stopped.

    ANTHROPIC_API_KEY=... [ANTHROPIC_WORKSPACE_ID=wrkspc_...] python ml/generate_screener.py [--concurrency 12]
"""
import argparse
import asyncio
import json
import os
import random
from collections import Counter
from pathlib import Path

import anthropic
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
OUT = ROOT / "ml" / "transcripts.jsonl"
MODEL = "claude-haiku-5-5"
TARGET = {"scam": 1500, "legit": 1000}

SCAM_SCRIPTS = {
    "medicare": "Caller claims to be from Medicare; benefits or card 'need re-verification', asks for Medicare/SSN or card number.",
    "irs": "Caller claims to be IRS/Treasury; back taxes owed, arrest warrant threatened, pay by gift cards or wire today.",
    "grandchild": "Caller pretends to be the grandchild (or their lawyer/officer) in jail or a car accident; needs bail money fast, 'don't tell Mom and Dad'.",
    "tech_support": "Caller claims to be Microsoft/Apple support; computer infected, wants remote access and a payment for the 'fix'.",
    "bank_fraud_fake": "Caller claims to be the bank's fraud department; suspicious charges, asks for the one-time code, PIN or to move money to a 'safe account'.",
    "utility_shutoff": "Caller claims to be the power/water company; service cut off within the hour unless paid by prepaid card.",
    "prize_lottery": "Caller says Linda won a sweepstakes/lottery; must pay taxes or a processing fee first to release the prize.",
    "romance": "Caller is an online 'friend' or sweetheart Linda supposedly met; sweet talk, then a crisis that needs money or gift cards, secrecy.",
}
LEGIT_SCRIPTS = {
    "doctor_office": "Dr. Patel's office confirming or rescheduling an appointment; happy to call back on the main office line.",
    "pharmacy": "Pharmacy saying a prescription is ready or needs insurance info at the counter; gives store number.",
    "delivery": "Delivery driver or courier who can't find the house or needs a gate code / safe drop spot.",
    "bank_fraud_real": "Real bank fraud alert: asks only to confirm whether a recent charge was hers, never asks for PIN/codes/passwords, "
                       "and says to call the number on the back of her card.",
    "contractor": "Roofer/plumber Linda (or her son) hired, scheduling a visit or quoting a repair; gives business name and number.",
    "charity": "Local charity or church calling to thank for a past gift or invite to an event; fine with a mailed letter, no pressure.",
    "survey": "Polling or customer-satisfaction survey; a few questions, no payment or personal financial info.",
}

CALLER_STYLES = ["calm and polished", "pushy and impatient", "friendly and chatty", "nervous and rushed",
                 "formal and scripted", "confused, repeats themselves", "elderly and slow", "young, casual slang"]
OUTCOMES_SCAM = ["caller dodges every question and escalates until asking for payment or account details",
                 "caller gets angry at the questions and hangs up",
                 "caller invents a fake callback number and employee ID, then pushes for card or account details",
                 "caller tries to get transferred to Linda directly and insists it's urgent and private"]
OUTCOMES_LEGIT = ["caller answers every question plainly and gives a real callback number",
                  "caller is briefly annoyed by the screening but cooperates",
                  "caller agrees to send it by mail or leave a message instead",
                  "caller sounds a bit urgent but never asks for money, codes or account details"]

SCHEMA = {
    "type": "object",
    "properties": {
        "turns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "speaker": {"type": "string", "enum": ["Agent", "Caller"]},
                    "text": {"type": "string"},
                    "t_seconds": {"type": "number"},
                    "stage": {"type": "string",
                              "enum": ["none", "hook", "authority", "urgency", "isolation", "payment_or_info"]},
                },
                "required": ["speaker", "text", "t_seconds", "stage"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["turns"],
    "additionalProperties": False,
}

SYSTEM = """You write realistic phone-call transcripts for training a scam-call detector.

Every call is to Linda, 78, and is answered by Guardian, her AI call screener (speaker "Agent").
The Agent:
- Opens with: it is Linda's assistant, the call is recorded and screened, and asks who is calling and why.
- Asks pointed questions: full name and organization, a direct callback number, an employee or reference ID,
  and whether it can be sent by mail. It follows up on vague answers.
- Never shares anything about Linda, never claims to be Linda or a human, keeps replies short.

The other speaker is the "Caller". Write natural spoken language: contractions, fillers, interruptions,
the occasional transcription slip. Vary names, companies, amounts and wording; avoid stock phrases.

Each turn has t_seconds: seconds since the call started, increasing, realistic for speech
(about 2-3 words per second plus pauses), and the whole call ends by 90 seconds.

Each turn has a stage, the scam stage the CALL has reached at that turn:
none -> hook -> authority -> urgency -> isolation -> payment_or_info.
Legit calls use "none" on every turn. In scam calls, Agent turns repeat the stage reached so far,
stages never go backwards, and not every scam reaches every stage."""


def targets_needed() -> dict[str, int]:
    have = Counter()
    if OUT.exists():
        for line in OUT.open():
            if line.strip():
                have[json.loads(line).get("label")] += 1
    return {label: max(0, TARGET[label] - have[label]) for label in TARGET}


def plan_jobs(need: dict[str, int]) -> list[tuple[str, str, str]]:
    """Spread the shortfall evenly over each label's scripts."""
    jobs = []
    for label, scripts in (("scam", SCAM_SCRIPTS), ("legit", LEGIT_SCRIPTS)):
        names = list(scripts)
        for i in range(need[label]):
            name = names[i % len(names)]
            jobs.append((label, name, scripts[name]))
    random.shuffle(jobs)
    return jobs


def user_prompt(label: str, description: str) -> str:
    outcome = random.choice(OUTCOMES_SCAM if label == "scam" else OUTCOMES_LEGIT)
    turns = random.randint(6, 14)
    return (f"Write one {label.upper()} call.\n"
            f"Scenario: {description}\n"
            f"Caller style: {random.choice(CALLER_STYLES)}.\n"
            f"How it goes: {outcome}.\n"
            f"Length: about {turns} turns, Agent speaks first, ending by 90 seconds.")


def valid(turns: list[dict], label: str) -> bool:
    if len(turns) < 4 or turns[0]["speaker"] != "Agent" or "record" not in turns[0]["text"].lower():
        return False
    ts = [t["t_seconds"] for t in turns]
    if ts != sorted(ts) or ts[-1] > 95:
        return False
    if label == "legit" and any(t["stage"] != "none" for t in turns):
        return False
    return all(t["text"].strip() for t in turns)


async def generate_one(client, sem, job, out_f, lock, stats):
    label, script, description = job
    async with sem:
        for _ in range(3):
            try:
                resp = await client.messages.create(
                    model=MODEL,
                    max_tokens=8000,
                    system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
                    messages=[{"role": "user", "content": user_prompt(label, description)}],
                    output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
                )
            except (anthropic.BadRequestError, anthropic.AuthenticationError, anthropic.PermissionDeniedError):
                raise  # config problem: stop everything
            except anthropic.APIError as e:  # SDK already retried 429/5xx/connection errors
                stats["errors"] += 1
                print(f"  api error ({script}): {e}")
                await asyncio.sleep(5)
                continue
            if resp.stop_reason != "end_turn":
                stats["rejected"] += 1
                continue
            text = next((b.text for b in resp.content if b.type == "text"), "")
            turns = json.loads(text)["turns"]
            if not valid(turns, label):
                stats["rejected"] += 1
                continue
            row = {"script": script, "label": label, "turns": turns, "source": f"claude_screener/{MODEL}"}
            async with lock:
                out_f.write(json.dumps(row) + "\n")
                out_f.flush()
                stats[label] += 1
                done = stats["scam"] + stats["legit"]
                if done % 25 == 0:
                    print(f"  {done}/{stats['total']} written (scam {stats['scam']}, legit {stats['legit']}, "
                          f"rejected {stats['rejected']}, errors {stats['errors']})", flush=True)
            return


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrency", type=int, default=12)
    ap.add_argument("--limit", type=int, help="generate at most N (for a test run)")
    a = ap.parse_args()

    need = targets_needed()
    jobs = plan_jobs(need)[: a.limit]
    print(f"Need scam {need['scam']}, legit {need['legit']}; generating {len(jobs)} with {MODEL} -> {OUT.name}")
    if not jobs:
        return

    headers = {"anthropic-workspace-id": os.environ["ANTHROPIC_WORKSPACE_ID"]} \
        if os.environ.get("ANTHROPIC_WORKSPACE_ID") else None
    client = anthropic.AsyncAnthropic(max_retries=6, timeout=120, default_headers=headers)
    sem, lock = asyncio.Semaphore(a.concurrency), asyncio.Lock()
    stats = Counter(total=len(jobs))
    with OUT.open("a") as out_f:
        await asyncio.gather(*(generate_one(client, sem, j, out_f, lock, stats) for j in jobs))
    print(f"Done: scam {stats['scam']}, legit {stats['legit']}, rejected {stats['rejected']}, "
          f"errors {stats['errors']}. Still needed: {targets_needed()}")


if __name__ == "__main__":
    asyncio.run(main())
