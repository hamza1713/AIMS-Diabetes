"""
Authentication Endpoints
========================
Email + password accounts with JWT access/refresh tokens.

  POST /auth/register         -> TokenResponse (201)
  POST /auth/login            -> TokenResponse
  POST /auth/refresh          -> TokenResponse (new pair)
  POST /auth/forgot-password  -> generic message (stub — no email is sent yet)
  POST /auth/change-password  -> {"message"}  (Bearer token required)
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import require_token_user_id
from app.core.database import get_db
from app.core.limiter import limiter
from app.core.logger import get_logger
from app.core.security import TokenError, decode_token, hash_password, issue_token_pair, verify_password
from app.models.db_models import User
from app.models.domain import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
)
from app.services.user_service import get_preferences, get_user_by_uid, notify, user_to_profile

router = APIRouter(prefix="/auth")
log = get_logger(__name__)


def _tokens_for(user: User) -> TokenResponse:
    return TokenResponse(**issue_token_pair(str(user.id)), user=user_to_profile(user))


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED, summary="Create Account")
@limiter.limit("30/minute")
def register(request: Request, payload: RegisterRequest, db: Session = Depends(get_db)):
    email = payload.email.lower().strip()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    user = User(email=email, name=payload.name.strip(), password_hash=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    uid = str(user.id)
    get_preferences(db, uid)
    notify(db, uid, "Welcome to AIMS-Diabetes", "Start by logging your first glucose reading.", type_="info")
    log.info("Registered user id=%s", user.id)
    return _tokens_for(user)


@router.post("/login", response_model=TokenResponse, summary="Log In")
@limiter.limit("30/minute")
def login(request: Request, payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email.lower().strip()).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account is disabled.")
    return _tokens_for(user)


@router.post("/refresh", response_model=TokenResponse, summary="Refresh Access Token")
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    try:
        uid = decode_token(payload.refresh_token, expected_type="refresh")
    except TokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    user = get_user_by_uid(db, uid)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User no longer exists.")
    return _tokens_for(user)


@router.post("/forgot-password", summary="Request Password Reset (stub)")
@limiter.limit("10/minute")
def forgot_password(request: Request, payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """
    Stub: always returns the same message so account existence is not leaked.
    Email delivery is not implemented yet — the request is only logged.
    """
    exists = db.query(User).filter(User.email == payload.email.lower().strip()).first() is not None
    log.info("Password reset requested (account exists: %s) — email delivery not implemented.", exists)
    return {"message": "If an account exists for this email, a password reset link has been sent."}


@router.post("/change-password", summary="Change Password")
def change_password(
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(require_token_user_id),
):
    user = get_user_by_uid(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=400, detail="New password must differ from the current one.")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"message": "Password updated."}
