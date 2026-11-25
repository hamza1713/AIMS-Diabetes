"""
Authentication & Multi-Tenancy Dependencies
============================================
Extracts caller identity for clinical record isolation and multi-tenancy.

Primary mechanism: ``Authorization: Bearer <access_token>`` (JWT issued by /auth/login).
Legacy mechanism (DEBUG only): ``X-User-Id`` header or ``?user_id=`` query param,
defaulting to ``"default_user"`` — kept so scripts and the existing test-suite work.
"""

from typing import Optional

from fastapi import Depends, Header, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.core.security import TokenError, decode_token

bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token from /api/v1/auth/login")


def _str_or_none(value) -> Optional[str]:
    """Dependency defaults are FieldInfo objects when the function is called directly."""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _unauthorized(detail: str = "Not authenticated.") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_token_user_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Optional[str]:
    """Returns the user id from a Bearer token, None if no token was sent, 401 if it is invalid."""
    if not isinstance(credentials, HTTPAuthorizationCredentials):
        return None
    try:
        return decode_token(credentials.credentials, expected_type="access")
    except TokenError as exc:
        raise _unauthorized(str(exc))


def get_current_user_id(
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    user_id: Optional[str] = Query(None),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> str:
    """
    Resolves the active user identity for patient isolation and multi-tenancy.

    1. A valid Bearer access token always wins (invalid/expired token -> 401).
    2. Only when DEBUG is true: 'X-User-Id' header, then 'user_id' query param,
       then 'default_user'.
    3. Otherwise -> 401.
    """
    token_uid = get_token_user_id(credentials)
    if token_uid:
        return token_uid
    if settings.DEBUG:
        return _str_or_none(x_user_id) or _str_or_none(user_id) or "default_user"
    raise _unauthorized()


def require_token_user_id(token_uid: Optional[str] = Depends(get_token_user_id)) -> str:
    """Strict variant: a Bearer token is mandatory regardless of DEBUG (used for /users/me etc.)."""
    if not token_uid:
        raise _unauthorized()
    return token_uid
