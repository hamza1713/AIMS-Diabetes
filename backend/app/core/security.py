"""
Security Primitives — Password Hashing & JWT
============================================
bcrypt password hashing and HS256 JWT access/refresh tokens.

Token claims:
  sub  — the user id as a string (the same value stored in every ``user_id`` column)
  type — "access" | "refresh"
  exp / iat — standard expiry / issued-at
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import bcrypt
import jwt

from app.core.config import settings
from app.core.logger import get_logger

log = get_logger(__name__)

_DEV_FALLBACK_SECRET = "diadoc-insecure-dev-secret-change-me"
_warned_dev_secret = False


class TokenError(Exception):
    """Raised when a JWT cannot be decoded or has the wrong type."""


def _secret() -> str:
    global _warned_dev_secret
    if settings.JWT_SECRET_KEY:
        return settings.JWT_SECRET_KEY
    if not settings.DEBUG:
        raise RuntimeError("JWT_SECRET_KEY must be set in .env when DEBUG is False.")
    if not _warned_dev_secret:
        log.warning("JWT_SECRET_KEY not set — using an insecure development key (DEBUG only).")
        _warned_dev_secret = True
    return _DEV_FALLBACK_SECRET


# ── Passwords ────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    # bcrypt only uses the first 72 bytes; truncate explicitly so long passwords don't error
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ── JWT ──────────────────────────────────────────────────────────────────────

def _create_token(subject: str, token_type: str, expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {
        "sub": str(subject),
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    return jwt.encode(payload, _secret(), algorithm=settings.JWT_ALGORITHM)


def create_access_token(subject: str) -> str:
    return _create_token(subject, "access", timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))


def create_refresh_token(subject: str) -> str:
    return _create_token(subject, "refresh", timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))


def decode_token(token: str, expected_type: str = "access") -> str:
    """Decodes a JWT and returns its subject (user id). Raises TokenError on any problem."""
    try:
        payload = jwt.decode(token, _secret(), algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Token has expired.") from exc
    except jwt.PyJWTError as exc:
        raise TokenError("Invalid token.") from exc
    if payload.get("type") != expected_type:
        raise TokenError(f"Expected a {expected_type} token.")
    sub = payload.get("sub")
    if not sub:
        raise TokenError("Token has no subject.")
    return str(sub)


def issue_token_pair(subject: str) -> Dict[str, Any]:
    return {
        "access_token": create_access_token(subject),
        "refresh_token": create_refresh_token(subject),
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }
