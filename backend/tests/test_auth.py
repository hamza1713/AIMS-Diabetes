"""
Auth router: register / login / refresh / forgot-password / change-password,
Bearer resolution in deps, and chat history scoped to the token user.
"""

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.api.deps import get_current_user_id
from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token, decode_token, TokenError, hash_password, verify_password

A = "/api/v1/auth"


def test_password_hashing_roundtrip():
    h = hash_password("correct horse")
    assert h != "correct horse"
    assert verify_password("correct horse", h)
    assert not verify_password("wrong", h)
    assert not verify_password("x", "not-a-bcrypt-hash")


def test_token_types_are_enforced():
    assert decode_token(create_access_token("42"), "access") == "42"
    assert decode_token(create_refresh_token("42"), "refresh") == "42"
    with pytest.raises(TokenError):
        decode_token(create_refresh_token("42"), "access")
    with pytest.raises(TokenError):
        decode_token("garbage.token.value", "access")


def test_register_login_refresh_flow(api, register_user):
    headers, body = register_user(name="Ayesha")
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0
    assert body["user"]["name"] == "Ayesha"
    assert body["user"]["email"] == body["_email"]
    assert "password_hash" not in body["user"]

    # duplicate email
    dup = api.post(f"{A}/register", json={"name": "X", "email": body["_email"].upper(), "password": "another-pass"})
    assert dup.status_code == 409

    # login (case-insensitive email)
    ok = api.post(f"{A}/login", json={"email": body["_email"].upper(), "password": body["_password"]})
    assert ok.status_code == 200
    assert ok.json()["user"]["id"] == body["user"]["id"]

    bad = api.post(f"{A}/login", json={"email": body["_email"], "password": "nope-nope"})
    assert bad.status_code == 401

    # refresh
    r = api.post(f"{A}/refresh", json={"refresh_token": body["refresh_token"]})
    assert r.status_code == 200
    assert r.json()["access_token"]
    # an access token is not a refresh token
    r2 = api.post(f"{A}/refresh", json={"refresh_token": body["access_token"]})
    assert r2.status_code == 401


def test_register_validation(api):
    assert api.post(f"{A}/register", json={"name": "A", "email": "not-an-email", "password": "longenough"}).status_code == 422
    assert api.post(f"{A}/register", json={"name": "A", "email": "a@example.com", "password": "short"}).status_code == 422


def test_forgot_password_does_not_leak_existence(api, register_user):
    _, body = register_user()
    known = api.post(f"{A}/forgot-password", json={"email": body["_email"]})
    unknown = api.post(f"{A}/forgot-password", json={"email": "nobody-here@example.com"})
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()


def test_change_password(api, register_user):
    headers, body = register_user()
    assert api.post(f"{A}/change-password", json={"current_password": "x", "new_password": "new-password-1"}).status_code == 401
    wrong = api.post(f"{A}/change-password", headers=headers,
                     json={"current_password": "wrong-one", "new_password": "new-password-1"})
    assert wrong.status_code == 400
    ok = api.post(f"{A}/change-password", headers=headers,
                  json={"current_password": body["_password"], "new_password": "new-password-1"})
    assert ok.status_code == 200
    assert api.post(f"{A}/login", json={"email": body["_email"], "password": "new-password-1"}).status_code == 200
    assert api.post(f"{A}/login", json={"email": body["_email"], "password": body["_password"]}).status_code == 401


def test_deps_bearer_wins_and_debug_fallback(monkeypatch):
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=create_access_token("7"))
    assert get_current_user_id(x_user_id="alice", user_id=None, credentials=creds) == "7"

    bad = HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad.token")
    with pytest.raises(HTTPException) as exc:
        get_current_user_id(x_user_id="alice", user_id=None, credentials=bad)
    assert exc.value.status_code == 401

    monkeypatch.setattr(settings, "DEBUG", True)
    assert get_current_user_id(x_user_id="alice", user_id=None, credentials=None) == "alice"

    monkeypatch.setattr(settings, "DEBUG", False)
    with pytest.raises(HTTPException) as exc:
        get_current_user_id(x_user_id="alice", user_id=None, credentials=None)
    assert exc.value.status_code == 401


def test_invalid_bearer_is_rejected_on_endpoints(api):
    res = api.get("/api/v1/health-logs/glucose", headers={"Authorization": "Bearer not-a-jwt"})
    assert res.status_code == 401


def test_header_fallback_disabled_when_not_debug(api, monkeypatch):
    monkeypatch.setattr(settings, "DEBUG", False)
    assert api.get("/api/v1/health-logs/glucose", headers={"X-User-Id": "alice"}).status_code == 401


def test_chat_history_uses_token_user(api, register_user):
    headers, body = register_user()
    uid = str(body["user"]["id"])
    assert api.get("/api/v1/chat/history", headers=headers).json() == []
    # legacy path form: own id ok, someone else's forbidden
    assert api.get(f"/api/v1/chat/history/{uid}", headers=headers).status_code == 200
    assert api.get("/api/v1/chat/history/someone_else", headers=headers).status_code == 403
    cleared = api.delete("/api/v1/chat/history", headers=headers).json()
    assert cleared["user_id"] == uid
