"""
User Profile & Preferences Endpoints
====================================
  GET/PUT /users/me              -> UserProfile (BMI computed from height/weight)
  GET/PUT /users/me/preferences  -> UserPreferencesSchema
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, require_token_user_id
from app.core.database import get_db
from app.models.db_models import User
from app.models.domain import UserPreferencesSchema, UserPreferencesUpdate, UserProfile, UserProfileUpdate
from app.services.user_service import get_preferences, get_user_by_uid, user_to_profile

router = APIRouter(prefix="/users")


def _load_user(db: Session, user_id: str) -> User:
    user = get_user_by_uid(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return user


@router.get("/me", response_model=UserProfile, summary="Get My Profile")
def get_me(db: Session = Depends(get_db), user_id: str = Depends(require_token_user_id)):
    return user_to_profile(_load_user(db, user_id))


@router.put("/me", response_model=UserProfile, summary="Update My Profile")
def update_me(
    payload: UserProfileUpdate,
    db: Session = Depends(get_db),
    user_id: str = Depends(require_token_user_id),
):
    user = _load_user(db, user_id)
    data = payload.model_dump(exclude_unset=True)
    if "email" in data and data["email"]:
        email = data["email"].lower().strip()
        clash = db.query(User).filter(User.email == email, User.id != user.id).first()
        if clash:
            raise HTTPException(status_code=409, detail="That email is already in use.")
        data["email"] = email
    for key, value in data.items():
        if key in ("name", "email") and value is None:
            continue  # required columns can't be nulled
        setattr(user, key, value.strip() if isinstance(value, str) and key == "name" else value)
    db.commit()
    db.refresh(user)
    return user_to_profile(user)


@router.get("/me/preferences", response_model=UserPreferencesSchema, summary="Get My App Preferences")
def get_my_preferences(db: Session = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    return UserPreferencesSchema.model_validate(get_preferences(db, user_id))


@router.put("/me/preferences", response_model=UserPreferencesSchema, summary="Update My App Preferences")
def update_my_preferences(
    payload: UserPreferencesUpdate,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    prefs = get_preferences(db, user_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(prefs, key, value)
    if prefs.target_glucose_min >= prefs.target_glucose_max:
        db.rollback()
        raise HTTPException(status_code=422, detail="target_glucose_min must be below target_glucose_max.")
    db.commit()
    db.refresh(prefs)
    return UserPreferencesSchema.model_validate(prefs)
