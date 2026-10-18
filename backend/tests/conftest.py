"""Tests run against the local TimescaleDB (backend/docker-compose.yml), never Tiger Cloud,
and with every outbound key blanked so nothing is texted or deleted for real."""
import os

os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL",
                                            "postgres://postgres:guardian@localhost:5433/guardian")
for key in ("PHOTON_SIDECAR_URL", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "ELEVENLABS_API_KEY",
            "ELEVENLABS_WEBHOOK_SECRET", "SENTRY_DSN", "SCREENER_NUMBER", "ANTHROPIC_API_KEY"):
    os.environ[key] = ""
os.environ["TRUSTED_PHONE"] = "+13105550100"
os.environ["LINDA_PHONE"] = "+13105550000"
os.environ["PUBLIC_BASE_URL"] = "http://test"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def _client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client(_client):
    assert _client.post("/demo/reset").json() == {"ok": True}
    return _client
