"""
Home Dashboard Endpoint
=======================
One call for the home screen: latest glucose + 7-day sparkline, today's water,
exercise, meals and medication progress, pending dose reminders, unread
notification count and the most recent risk assessment.
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id
from app.api.v1.endpoints.exercise import weekly_summary
from app.api.v1.endpoints.notifications import unread_count
from app.core.database import get_db
from app.core.timeutils import as_utc, day_bounds_utc, local_today, range_bounds_utc, week_start
from app.models.db_models import GlucoseLog, RiskAssessmentLog
from app.services.tracking_service import (
    daily_glucose_averages,
    exercise_between,
    glucose_out,
    glucose_stats,
    glucose_values_between,
    meals_between,
    medication_schedule_for_day,
    nutrition_totals,
    water_total,
)
from app.services.user_service import get_preferences, get_user_by_uid, target_range

router = APIRouter()


@router.get("/dashboard", summary="Home Dashboard Aggregate")
def get_dashboard(
    tz_offset: int = Query(0, ge=-840, le=840, description="Client UTC offset in minutes"),
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    today = local_today(tz_offset)
    prefs = get_preferences(db, user_id)
    low, high = target_range(prefs)
    user = get_user_by_uid(db, user_id)

    # Glucose
    latest = (
        db.query(GlucoseLog)
        .filter(GlucoseLog.user_id == user_id, GlucoseLog.measurement_type != "HbA1c")
        .order_by(GlucoseLog.recorded_at.desc())
        .first()
    )
    first_day = today - timedelta(days=6)
    start7, end7 = range_bounds_utc(first_day, today + timedelta(days=1), tz_offset)
    logs7 = glucose_values_between(db, user_id, start7, end7)
    stats7 = glucose_stats([g.glucose_value for g in logs7], low, high)

    # Today
    t_start, t_end = day_bounds_utc(today, tz_offset)
    meals_today = nutrition_totals(meals_between(db, user_id, t_start, t_end))
    exercise_today = exercise_between(db, user_id, t_start, t_end)
    week = weekly_summary(db, user_id, week_start(today), tz_offset)
    water_ml = water_total(db, user_id, today, tz_offset)
    schedule = medication_schedule_for_day(db, user_id, today, tz_offset)
    pending = [s for s in schedule if s["status"] == "pending"]

    risk = (
        db.query(RiskAssessmentLog)
        .filter(RiskAssessmentLog.user_id == user_id)
        .order_by(RiskAssessmentLog.assessed_at.desc())
        .first()
    )

    return {
        "date": today.isoformat(),
        "user": {"id": user.id, "name": user.name, "photo_url": user.photo_url} if user else None,
        "glucose": {
            "latest": glucose_out(latest, prefs) if latest else None,
            "unit": prefs.glucose_unit,
            "target_min": low,
            "target_max": high,
            "sparkline": daily_glucose_averages(logs7, first_day, 7, tz_offset),
            "last_7_days": stats7,
        },
        "water": {
            "total_ml": water_ml,
            "goal_ml": prefs.water_goal_ml,
            "percent": round(water_ml / prefs.water_goal_ml * 100, 1) if prefs.water_goal_ml else None,
        },
        "exercise": {
            "today_minutes": sum(e.duration_min for e in exercise_today),
            "today_calories": round(sum(e.calories or 0 for e in exercise_today), 1),
            "week_minutes": week["total_minutes"],
            "weekly_goal_minutes": week["goal_minutes"],
        },
        "meals": {
            **meals_today.model_dump(),
            "calorie_goal": prefs.daily_calorie_goal,
            "carbs_goal_g": prefs.daily_carbs_goal_g,
        },
        "medications": {
            "scheduled_today": len(schedule),
            "taken_today": sum(1 for s in schedule if s["status"] == "taken"),
            "next_dose": pending[0] if pending else None,
        },
        "reminders": [
            {"type": "medication", "title": f"Take {p['name']}" + (f" {p['dosage']}" if p["dosage"] else ""),
             "time": p["time"], "medication_id": p["medication_id"]}
            for p in pending
        ],
        "unread_notifications": unread_count(db, user_id),
        "last_risk_assessment": {
            "id": risk.id,
            "assessment_type": risk.assessment_type,
            "score": risk.risk_score,
            "risk_level": risk.risk_level,
            "assessed_at": as_utc(risk.assessed_at),
        } if risk else None,
    }
