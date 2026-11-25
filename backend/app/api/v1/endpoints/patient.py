"""
Patient Longitudinal Health Tracking Endpoints
==============================================
Logs blood glucose readings, calculates Time-in-Range (TIR) and estimated HbA1c,
and logs patient meals with macros and daily totals.

Date filters: ``?date=YYYY-MM-DD`` (a local day) or ``?days=N`` (last N local days),
with ``?tz_offset=`` = client UTC offset in minutes (e.g. 300 for UTC+5).
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id
from app.core.database import get_db
from app.core.timeutils import day_bounds_utc, local_today, parse_date, resolve_window
from app.models.db_models import GlucoseLog, MealLog
from app.models.domain import (
    GlucoseLogCreate,
    GlucoseLogResponse,
    MealDailyTotals,
    MealLogCreate,
    MealLogResponse,
)
from app.services.health_service import health_service
from app.services.tracking_service import glucose_out, in_window, meal_out, nutrition_totals
from app.services.user_service import get_preferences, glucose_status, notify

router = APIRouter()

TZ_QUERY = Query(0, ge=-840, le=840, description="Client UTC offset in minutes, e.g. 300 for UTC+05:00")


# ── Glucose ──────────────────────────────────────────────────────────────────

@router.post("/health-logs/glucose", response_model=GlucoseLogResponse, summary="Log Blood Glucose Measurement")
def log_glucose(
    entry: GlucoseLogCreate,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    Logs a blood glucose measurement. Send ``when`` (fasting, before_meal, after_meal,
    bedtime, random) and optional ``recorded_at``; legacy ``measurement_type`` still works.
    Out-of-range readings create a glucose alert notification (if enabled in preferences).
    """
    log = health_service.add_glucose_log(db=db, entry=entry, user_id=current_user_id)
    prefs = get_preferences(db, current_user_id)
    status = glucose_status(log.glucose_value, log.measurement_type, prefs)
    if status in ("low", "high"):
        title = "Low glucose reading" if status == "low" else "High glucose reading"
        notify(
            db, current_user_id, title,
            f"You logged {log.glucose_value:g} mg/dL, outside your {prefs.target_glucose_min:g}–"
            f"{prefs.target_glucose_max:g} mg/dL target.",
            type_="alert", pref_key="glucose_alerts",
        )
    return glucose_out(log, prefs)


@router.get("/health-logs/glucose", response_model=List[GlucoseLogResponse], summary="Get Blood Glucose Log History")
def get_glucose_logs(
    date: Optional[str] = Query(None, description="Local day YYYY-MM-DD"),
    days: Optional[int] = Query(None, ge=1, le=366, description="Last N local days incl. today"),
    tz_offset: int = TZ_QUERY,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """Retrieves glucose entries ordered newest first, optionally filtered by ``date`` or ``days``."""
    q = db.query(GlucoseLog).filter(GlucoseLog.user_id == current_user_id)
    q = in_window(q, GlucoseLog.recorded_at, resolve_window(date, days, tz_offset))
    prefs = get_preferences(db, current_user_id)
    return [glucose_out(g, prefs) for g in q.order_by(GlucoseLog.recorded_at.desc()).all()]


@router.get("/health-logs/glucose/summary", summary="Get Glycemic Metrics & Time-in-Range")
def get_glucose_summary(
    days: int = 30,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """Calculates Time-in-Range %, estimated HbA1c (ADAG formula), average glucose, and clinical stats."""
    return health_service.get_glucose_summary(db=db, user_id=current_user_id, days=days)


@router.delete("/health-logs/glucose/{log_id}", status_code=204, summary="Delete a Glucose Reading")
def delete_glucose_log(
    log_id: int,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    row = db.query(GlucoseLog).filter(GlucoseLog.id == log_id, GlucoseLog.user_id == current_user_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Glucose reading not found.")
    db.delete(row)
    db.commit()


# ── Meals ────────────────────────────────────────────────────────────────────

@router.post("/health-logs/meals", response_model=MealLogResponse, summary="Log Patient Meal & Carbohydrates")
def log_meal(
    meal: MealLogCreate,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """Logs a meal with carbohydrates and optional name, calories, protein, fat and ``logged_at``."""
    row = health_service.add_meal_log(
        db=db,
        meal_type=meal.meal_type,
        description=meal.description or meal.name or "",
        carbs_grams=meal.carbs_grams,
        user_id=current_user_id,
        name=meal.name,
        calories=meal.calories,
        protein_g=meal.protein_g,
        fat_g=meal.fat_g,
        logged_at=meal.logged_at,
    )
    return meal_out(row)


@router.get("/health-logs/meals", response_model=List[MealLogResponse], summary="Get Meal Log History")
def get_meals(
    date: Optional[str] = Query(None, description="Local day YYYY-MM-DD"),
    days: Optional[int] = Query(None, ge=1, le=366),
    tz_offset: int = TZ_QUERY,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """Meals ordered newest first, optionally filtered by ``date`` or ``days``."""
    q = db.query(MealLog).filter(MealLog.user_id == current_user_id)
    q = in_window(q, MealLog.recorded_at, resolve_window(date, days, tz_offset))
    return [meal_out(m) for m in q.order_by(MealLog.recorded_at.desc()).all()]


@router.get("/health-logs/meals/daily-totals", response_model=MealDailyTotals, summary="Daily Nutrition Totals")
def get_meal_daily_totals(
    date: Optional[str] = Query(None, description="Local day YYYY-MM-DD (default today)"),
    tz_offset: int = TZ_QUERY,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """Calories / carbs / protein / fat totals for a day, per meal type, and the user's goals."""
    day = parse_date(date) or local_today(tz_offset)
    start, end = day_bounds_utc(day, tz_offset)
    meals = (
        db.query(MealLog)
        .filter(MealLog.user_id == current_user_id, MealLog.recorded_at >= start, MealLog.recorded_at < end)
        .all()
    )
    by_type = {}
    for mt in sorted({m.meal_type for m in meals}):
        by_type[mt] = nutrition_totals([m for m in meals if m.meal_type == mt])
    prefs = get_preferences(db, current_user_id)
    return MealDailyTotals(
        date=day.isoformat(),
        totals=nutrition_totals(meals),
        goals={"calories": prefs.daily_calorie_goal, "carbs_g": prefs.daily_carbs_goal_g},
        by_meal_type=by_type,
    )


@router.delete("/health-logs/meals/{meal_id}", status_code=204, summary="Delete a Meal")
def delete_meal(
    meal_id: int,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    row = db.query(MealLog).filter(MealLog.id == meal_id, MealLog.user_id == current_user_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Meal not found.")
    db.delete(row)
    db.commit()
