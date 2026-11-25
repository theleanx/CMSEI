import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["ADMIN_PASSWORD"] = "test-admin-pw"
os.environ["RATE_PER_MINUTE_IP"] = "100000"
os.environ["RATE_ASSESS_PER_MINUTE_IP"] = "100000"

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def fresh(client):
    """A client with its own cookies, so tests do not share sessions."""
    from app.main import app
    with TestClient(app) as c:
        yield c


def csrf_of(c):
    c.get("/")
    return c.cookies.get("mse_csrf")
