-- Guardian schema (CONTRACTS section 9). Idempotent: safe to run on every startup.
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  guardian_number TEXT,
  real_phone TEXT
);

CREATE TABLE IF NOT EXISTS trusted_contacts (
  user_id TEXT REFERENCES users(id),
  name TEXT,
  phone TEXT
);

CREATE TABLE IF NOT EXISTS verified_numbers (
  user_id TEXT REFERENCES users(id),
  number TEXT,
  label TEXT,
  added_by TEXT,
  PRIMARY KEY (user_id, number)
);

CREATE TABLE IF NOT EXISTS call_logs (
  call_id TEXT,
  user_id TEXT,
  number TEXT,
  ts TIMESTAMPTZ NOT NULL,
  seconds REAL,
  outcome TEXT,          -- connected | message | ended_scam | rejected | passed_verified
  screened BOOLEAN,
  max_risk REAL
);
SELECT create_hypertable('call_logs', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS call_logs_number_ts ON call_logs (number, ts DESC);
CREATE INDEX IF NOT EXISTS call_logs_user_ts ON call_logs (user_id, ts DESC);

CREATE TABLE IF NOT EXISTS number_profiles (
  number TEXT PRIMARY KEY,
  first_seen TIMESTAMPTZ,
  total_calls INT DEFAULT 0,
  users_called_24h INT DEFAULT 0,
  flagged_by INT DEFAULT 0,
  max_live_risk REAL DEFAULT 0,
  scam_score INT DEFAULT 0,
  top_reason TEXT
);

CREATE TABLE IF NOT EXISTS scam_evidence (     -- scam calls ONLY
  evidence_id TEXT PRIMARY KEY,
  call_id TEXT,
  user_id TEXT,
  number TEXT,
  ts TIMESTAMPTZ,
  recording_url TEXT,
  transcript JSONB,
  red_flags JSONB,
  score REAL,
  delete_after TIMESTAMPTZ       -- ts + 90 days
);

CREATE TABLE IF NOT EXISTS signals (
  user_id TEXT,
  kind TEXT,                     -- bank_app_open
  ts TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
  call_id TEXT,
  user_id TEXT,
  ts TIMESTAMPTZ NOT NULL,
  type TEXT,
  data JSONB
);
SELECT create_hypertable('events', 'ts', if_not_exists => TRUE);

-- Additions owned by A (not yet in CONTRACTS section 9) --------------------
-- Per-user blocks from the family ("block this number"): rejected for this user regardless of score.
CREATE TABLE IF NOT EXISTS blocked_numbers (
  user_id TEXT REFERENCES users(id),
  number TEXT,
  reason TEXT,
  ts TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, number)
);

-- Text of messages left for Linda (audio and transcript are deleted; the message text is kept).
CREATE TABLE IF NOT EXISTS messages (
  call_id TEXT PRIMARY KEY,
  user_id TEXT,
  number TEXT,
  ts TIMESTAMPTZ NOT NULL,
  text TEXT
);
