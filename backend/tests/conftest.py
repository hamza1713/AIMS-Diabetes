"""
Pytest Configuration & Fixtures
===============================
Provides shared TestClient fixture and test environment configuration.
"""

import os
import sys
import pytest
from fastapi.testclient import TestClient

# Ensure backend root is on sys.path
backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

from app.main import app


@pytest.fixture(scope="session")
def client():
    """Returns a test client for exercising FastAPI endpoints."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def api(client, tmp_path_factory):
    """
    Test client whose get_db points at a throw-away SQLite file, so the mobile-API
    tests (users, tracking, medications, ...) never write to diabetes_assistant.db.
    Rate limiting is disabled for the duration.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.database import Base, get_db
    from app.core.limiter import limiter

    db_file = tmp_path_factory.mktemp("db") / "test_mobile_api.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def _get_test_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _get_test_db
    was_enabled = limiter.enabled
    limiter.enabled = False
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_db, None)
        limiter.enabled = was_enabled
        engine.dispose()


@pytest.fixture
def register_user(api):
    """Factory: registers a fresh user and returns (auth_headers, token_response_json)."""
    import uuid

    def _register(name="Test User", password="s3cret-pass!"):
        email = f"user_{uuid.uuid4().hex[:10]}@example.com"
        res = api.post("/api/v1/auth/register", json={"name": name, "email": email, "password": password})
        assert res.status_code == 201, res.text
        body = res.json()
        body["_email"], body["_password"] = email, password
        return {"Authorization": f"Bearer {body['access_token']}"}, body

    return _register
