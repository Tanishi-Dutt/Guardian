"""Every tunable number in one place (CONTRACTS sections 4, 6, 10). Show this file on a slide."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def env(name, default=""):
    return os.getenv(name, default).strip()


# --- Environment ---
DATABASE_URL = env("DATABASE_URL", "postgres://postgres:guardian@localhost:5433/guardian")
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
LINDA_PHONE = env("LINDA_PHONE")
TRUSTED_PHONE = env("TRUSTED_PHONE")
GUARDIAN_NUMBER = env("GUARDIAN_NUMBER")
SCREENER_NUMBER = env("SCREENER_NUMBER")
# "register": hand the call to ElevenLabs via its Twilio register-call API (one number).
# "forward":  <Dial> the second Twilio number that is imported into the ElevenLabs agent.
SCREEN_MODE = env("SCREEN_MODE", "register")

TWILIO_ACCOUNT_SID = env("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = env("TWILIO_AUTH_TOKEN")
TWILIO_SMS_FROM = env("TWILIO_SMS_FROM") or GUARDIAN_NUMBER
PHOTON_API_KEY = env("PHOTON_API_KEY")
PHOTON_SEND_URL = env("PHOTON_SEND_URL")
PHOTON_FROM = env("PHOTON_FROM")

ELEVENLABS_API_KEY = env("ELEVENLABS_API_KEY")
ELEVENLABS_AGENT_ID = env("ELEVENLABS_AGENT_ID")
ELEVENLABS_WEBHOOK_SECRET = env("ELEVENLABS_WEBHOOK_SECRET")
ELEVENLABS_API = "https://api.elevenlabs.io/v1"

SENTRY_DSN = env("SENTRY_DSN")
RECORDINGS_DIR = ROOT / "backend" / "recordings"
LOCAL_TZ = env("LOCAL_TZ", "America/Los_Angeles")

# --- Demo constants (CONTRACTS section 4) ---
DEMO_USER_ID = "linda"
DEMO_USER_NAME = "Linda"
TRUSTED_NAME = env("TRUSTED_NAME", "David (son)")
VERIFIED_SEED = [
    ("+13105550111", "Son (David)"),
    ("+13105550199", "Dr. Patel's office"),
    ("+13105550123", "CVS Pharmacy"),
]
PREFLAGGED_NUMBER = "+12135550142"
PREFLAGGED_REASON = "Medicare impersonation"

# --- Router (section 6 / risk rules) ---
REJECT_SCORE = 80

# --- /tools/assess decision thresholds (section 6) ---
END_RISK = 0.70
CONNECT_RISK = 0.40
DECIDE_AFTER_TURNS = 3
DECIDE_AFTER_SECONDS = 60
HARD_STOP_SECONDS = 90
SCORER_TIMEOUT_S = 1.3

SAY = {
    "continue": "",
    "end": "Linda isn't available. Please send any official correspondence by mail. Goodbye.",
    "connect": "Thank you. Connecting you to Linda now.",
    "message": "Linda can't come to the phone right now. Please leave a short message with your name "
               "and callback number, and I'll pass it along.",
}

# --- Number scam score weights (section 10) ---
W_LIVE_RISK = 45          # x max live risk (0-1)
W_PER_FLAG = 10           # per Guardian user who flagged it
W_FLAG_MAX = 30
W_MANY_USERS = 10         # called >= MANY_USERS_N distinct users in 24 h
MANY_USERS_N = 5
W_SHORT_CALLS = 10        # >= SHORT_CALLS_N calls under SHORT_CALL_S in 24 h
SHORT_CALLS_N = 3
SHORT_CALL_S = 20
W_ODD_HOURS = 5           # any call 9 PM - 8 AM local in 24 h
ODD_HOURS_START, ODD_HOURS_END = 21, 8
W_VERIFIED = -40          # on anyone's verified list

# --- Linda's safety score (section 10) ---
SAFETY_UNVERIFIED_CONNECTED = -10
SAFETY_SCAM_SCREENED = -5
SAFETY_BANK_ALERT = -20

# --- Bank-app rule ---
BANK_ALERT_WINDOW_MIN = 10
EVIDENCE_RETENTION_DAYS = 90
