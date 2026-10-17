# Guardian — Claude Code instructions

Read `CONTRACTS.md` first. It is the single source of truth for endpoints, event shapes, the scorer interface, the database schema, scores and recording rules.

## Who am I working for?
At the start of a session, if it is not obvious, ask: **"Are you Person A (backend) or Person C (voice + web)?"**

| Person | Only edit | Never touch |
|---|---|---|
| A | `backend/` | `ml/`, `agents/`, `voice/`, `web/` |
| C | `voice/`, `web/` | `backend/`, `ml/`, `agents/` |

Shared root files (`CONTRACTS.md`, `CLAUDE.md`, `GEMINI.md`, `.env.example`, `.gitignore`) change only when the user says the group agreed. A contract change goes in its own commit.

## Rules
- Never wait on another person: A builds against the stand-in `ml/scorer.py`; C builds against `web/src/mock.ts` fake events that match CONTRACTS §7 exactly.
- Phone numbers are always E.164. Demo constants are in CONTRACTS §4.
- `git pull --rebase` before starting and before every push. Small commits, at least hourly, to `main`.
- Never commit `.env`, keys, recordings or `ml/data/`.
- Backend runs from the repo root: `uvicorn backend.app.main:app --port 8000`.
