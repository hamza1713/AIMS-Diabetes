"""
User, Preferences & Notification Helpers
========================================
Shared helpers used by the auth, users, tracking, dashboard and analytics routers.
"""

from __future__ import annotations

from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.core.logger import get_logger
from app.core.timeutils import as_utc
from app.models.db_models import Notification, User, UserPreferences
from app.models.domain import UserProfile

log = get_logger(__name__)


def compute_bmi(height_cm: Optional[float], weight_kg: Optional[float]) -> Optional[float]:
    if not height_cm or not weight_kg:
        return None
    m = height_cm / 100.0
    return round(weight_kg / (m * m), 1)


def bmi_category(bmi: Optional[float]) -> Optional[str]:
    if bmi is None:
        return None
    if bmi < 18.5:
        return "Underweight"
    if bmi < 25:
        return "Normal"
    if bmi < 30:
        return "Overweight"
    return "Obese"


def user_to_profile(user: User) -> UserProfile:
    bmi = compute_bmi(user.height_cm, user.weight_kg)
    return UserProfile(
        id=user.id,
        email=user.email,
        name=user.name or "",
        age=user.age,
        gender=user.gender,
        height_cm=user.height_cm,
        weight_kg=user.weight_kg,
        diabetes_type=user.diabetes_type,
        photo_url=user.photo_url,
        bmi=bmi,
        bmi_category=bmi_category(bmi),
        created_at=as_utc(user.created_at),
    )


def get_user_by_uid(db: Session, user_id: str) -> Optional[User]:
    """Resolves a token subject / user_id string to a User row (None for legacy string ids)."""
    if not user_id or not str(user_id).isdigit():
        return None
    return db.query(User).filter(User.id == int(user_id)).first()


def get_preferences(db: Session, user_id: str) -> UserPreferences:
    """Returns the user's preferences row, creating it with defaults on first access."""
    prefs = db.query(UserPreferences).filter(UserPreferences.user_id == user_id).first()
    if prefs is None:
        prefs = UserPreferences(user_id=user_id)
        db.add(prefs)
        db.commit()
        db.refresh(prefs)
    return prefs


def glucose_status(value: float, measurement_type: str, prefs: Optional[UserPreferences] = None) -> Optional[str]:
    if measurement_type == "HbA1c":
        return None
    low = prefs.target_glucose_min if prefs and prefs.target_glucose_min else 70.0
    high = prefs.target_glucose_max if prefs and prefs.target_glucose_max else 180.0
    if value < low:
        return "low"
    if value > high:
        return "high"
    return "normal"


def target_range(prefs: Optional[UserPreferences]) -> Tuple[float, float]:
    if prefs is None:
        return 70.0, 180.0
    return prefs.target_glucose_min or 70.0, prefs.target_glucose_max or 180.0


def notify(
    db: Session,
    user_id: str,
    title: str,
    body: Optional[str] = None,
    type_: str = "info",
    pref_key: Optional[str] = None,
    commit: bool = True,
) -> Optional[Notification]:
    """
    Creates an in-app notification. When ``pref_key`` names a boolean preference
    (e.g. 'glucose_alerts') and the user turned it off, nothing is created.
    """
    try:
        if pref_key:
            prefs = get_preferences(db, user_id)
            if not getattr(prefs, pref_key, True):
                return None
        n = Notification(user_id=user_id, title=title, body=body, type=type_)
        db.add(n)
        if commit:
            db.commit()
            db.refresh(n)
        return n
    except Exception as exc:  # notifications must never break the main write
        log.warning("Failed to create notification for user '%s': %s", user_id, exc)
        db.rollback()
        return None
