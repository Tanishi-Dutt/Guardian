# Guardian — Gemini CLI instructions (Person B)

Read `CONTRACTS.md` first. It is the single source of truth.

**Only edit files in `ml/` and `agents/`.** Never touch `backend/`, `voice/` or `web/`. Shared root files change only after the group agrees, in their own commit.

## Your contract
`ml/scorer.py` must expose `score(transcript, call_id=None) -> dict` exactly as CONTRACTS §5 describes: all keys always present, returns in under 1.5 s, never raises, calls `step-5-preview` on every real call.
Person A imports it directly. The stand-in in the repo already has the right shape. Replace its internals, keep its signature.

## Tasks, in order
1. Real scorer: step-5-preview + scam rubric, JSON output, tested on 5 handwritten transcripts (by 8 PM, M1).
2. `ml/generate.py` (Gemini API): 1,500 scam + 1,000 legit transcripts with per-turn stage labels, JSONL `{script, label, turns:[{speaker,text,t_seconds,stage}]}`. Run in the background. Output to `ml/data/` (gitignored).
3. Family agent on Agentverse in `agents/`: "who called Mom?", "is this number safe?", "add to verified", "block this number", calling A's REST API (CONTRACTS §8). Use fake responses until A's endpoints exist (by 1 AM).
4. Train/test split by scam script (hold out 2), launch the Veri fine-tune (by midnight).
5. Synthetic call logs for 50 users + Linda's seed data (use CONTRACTS §4 constants).
6. Eval table: caught by 30/60/90 s, false alarms, latency. Fine-tune go/no-go (6 AM, M3).

## Git
`git pull --rebase` before starting and before every push. Small commits, at least hourly. Never commit `.env` or `ml/data/`.
