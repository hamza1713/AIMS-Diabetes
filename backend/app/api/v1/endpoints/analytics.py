"""
Analytics & Reports Endpoint
============================
  GET /analytics/summary?month=YYYY-MM

Monthly glucose control (average, Time-in-Range, eA1c, hypo/hyper counts, daily
and weekly averages, trend vs previous month), nutrition, exercise, water and
medication adherence.
"""

from collections import defaultdict
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id
from app.core.database import get_db
from app.core.timeutils import local_today, next_month, parse_month, range_bounds_utc, to_local_date, week_start
from app.models.db_models import WaterLog
from app.services.tracking_service import (
    adherence_for_range,
    daily_glucose_averages,
    exercise_between,
    glucose_stats,
    glucose_values_between,
    meals_between,
)
from app.services.user_service import get_preferences, target_range

router = APIRouter(prefix="/analytics")


def _trend(current: Optional[float], previous: Optional[float]) -> str:
    if current is None or previous is None:
        return "insufficient_data"
    delta = current - previous
    if abs(delta) < 5:
        return "stable"
    return "improving" if delta < 0 else "worsening"


@router.get("/summary", summary="Monthly Analytics Summary")
def analytics_summary(
    month: Optional[str] = Query(None, description="YYYY-MM (default current month)"),
    tz_offset: int = Query(0, ge=-840, le=840, description="Client UTC offset in minutes"),
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    first = parse_month(month, tz_offset)
    nxt = next_month(first)
    n_days = (nxt - first).days
    today = local_today(tz_offset)
    # days elapsed in the month so far (for per-day averages)
    elapsed = n_days if today >= nxt else max((today - first).days + 1, 0) if today >= first else 0
    start, end = range_bounds_utc(first, nxt, tz_offset)

    prefs = get_preferences(db, user_id)
    low, high = target_range(prefs)

    # Glucose
    logs = glucose_values_between(db, user_id, start, end)
    stats = glucose_stats([g.glucose_value for g in logs], low, high)
    prev_first = (first - timedelta(days=1)).replace(day=1)
    p_start, p_end = range_bounds_utc(prev_first, first, tz_offset)
    prev_stats = glucose_stats([g.glucose_value for g in glucose_values_between(db, user_id, p_start, p_end)], low, high)

    weekly = defaultdict(list)
    for g in logs:
        weekly[week_start(to_local_date(g.recorded_at, tz_offset))].append(g.glucose_value)
    weekly_out = [
        {"week_start": w.isoformat(), "average": round(sum(v) / len(v), 1), "readings": len(v)}
        for w, v in sorted(weekly.items())
    ]

    # Nutrition
    meals = meals_between(db, user_id, start, end)
    meal_days = {to_local_date(m.recorded_at, tz_offset) for m in meals}
    total_carbs = sum(m.carbs_grams or 0 for m in meals)
    total_kcal = sum(m.calories or 0 for m in meals)

    # Exercise
    ex = exercise_between(db, user_id, start, end)
    active_days = {to_local_date(e.performed_at, tz_offset) for e in ex}

    # Water
    water = (
        db.query(WaterLog)
        .filter(WaterLog.user_id == user_id, WaterLog.recorded_at >= start, WaterLog.recorded_at < end)
        .all()
    )
    water_days = defaultdict(int)
    for w in water:
        water_days[to_local_date(w.recorded_at, tz_offset)] += w.amount_ml

    adherence = adherence_for_range(db, user_id, first, elapsed, tz_offset) if elapsed else None

    return {
        "month": first.strftime("%Y-%m"),
        "days_in_month": n_days,
        "days_elapsed": elapsed,
        "glucose": {
            **stats,
            "target_min": low,
            "target_max": high,
            "previous_month_average": prev_stats["average"],
            "trend": _trend(stats["average"], prev_stats["average"]),
            "daily": daily_glucose_averages(logs, first, n_days, tz_offset),
            "weekly": weekly_out,
        },
        "nutrition": {
            "meals_logged": len(meals),
            "days_logged": len(meal_days),
            "avg_carbs_per_day": round(total_carbs / len(meal_days), 1) if meal_days else None,
            "avg_calories_per_day": round(total_kcal / len(meal_days), 1) if meal_days else None,
        },
        "exercise": {
            "sessions": len(ex),
            "active_days": len(active_days),
            "total_minutes": sum(e.duration_min for e in ex),
            "total_calories": round(sum(e.calories or 0 for e in ex), 1),
        },
        "water": {
            "avg_ml_per_day": round(sum(water_days.values()) / len(water_days), 1) if water_days else None,
            "days_goal_met": sum(1 for v in water_days.values() if v >= prefs.water_goal_ml),
            "goal_ml": prefs.water_goal_ml,
        },
        "medication_adherence_percent": adherence["adherence_percent"] if adherence else None,
    }
