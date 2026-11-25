"""
Exercise Tracking Endpoints
===========================
  POST   /health-logs/exercise                 log a workout
  GET    /health-logs/exercise?date=|days=      list (newest first)
  GET    /health-logs/exercise/weekly-summary   minutes vs weekly goal (default 150)
  DELETE /health-logs/exercise/{id}
"""

from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id
from app.core.database import get_db
from app.core.timeutils import local_today, parse_date, range_bounds_utc, resolve_window, to_local_date, to_naive_utc, week_start
from app.models.db_models import ExerciseLog
from app.models.domain import ExerciseLogCreate, ExerciseLogResponse
from app.services.tracking_service import exercise_between, exercise_out, in_window
from app.services.user_service import get_preferences, notify

router = APIRouter(prefix="/health-logs/exercise")
TZ_QUERY = Query(0, ge=-840, le=840, description="Client UTC offset in minutes")


def weekly_summary(db: Session, user_id: str, first_day, tz_offset: int = 0) -> dict:
    start, end = range_bounds_utc(first_day, first_day + timedelta(days=7), tz_offset)
    rows = exercise_between(db, user_id, start, end)
    goal = get_preferences(db, user_id).weekly_exercise_goal_min
    by_day = {first_day + timedelta(days=i): 0 for i in range(7)}
    calories = 0.0
    for r in rows:
        d = to_local_date(r.performed_at, tz_offset)
        if d in by_day:
            by_day[d] += r.duration_min
        calories += r.calories or 0
    total = sum(by_day.values())
    return {
        "week_start": first_day.isoformat(),
        "week_end": (first_day + timedelta(days=6)).isoformat(),
        "total_minutes": total,
        "goal_minutes": goal,
        "goal_percent": round(total / goal * 100, 1) if goal else None,
        "active_days": sum(1 for v in by_day.values() if v > 0),
        "sessions": len(rows),
        "calories": round(calories, 1),
        "by_day": [{"date": d.isoformat(), "minutes": m} for d, m in by_day.items()],
    }


@router.post("", response_model=ExerciseLogResponse, summary="Log a Workout")
def log_exercise(
    payload: ExerciseLogCreate,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    before = weekly_summary(db, user_id, week_start(local_today()))["total_minutes"]
    row = ExerciseLog(
        user_id=user_id,
        activity=payload.activity.strip(),
        duration_min=payload.duration_min,
        calories=payload.calories,
        intensity=payload.intensity,
        notes=payload.notes,
    )
    performed_at = to_naive_utc(payload.performed_at)
    if performed_at is not None:
        row.performed_at = performed_at
    db.add(row)
    db.commit()
    db.refresh(row)
    summary = weekly_summary(db, user_id, week_start(local_today()))
    goal = summary["goal_minutes"]
    if goal and before < goal <= summary["total_minutes"]:
        notify(db, user_id, "Weekly exercise goal reached!", f"You've hit {goal} active minutes this week.",
               type_="achievement")
    return exercise_out(row)


@router.get("", response_model=List[ExerciseLogResponse], summary="List Workouts")
def list_exercise(
    date: Optional[str] = Query(None, description="Local day YYYY-MM-DD"),
    days: Optional[int] = Query(None, ge=1, le=366),
    tz_offset: int = TZ_QUERY,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    q = db.query(ExerciseLog).filter(ExerciseLog.user_id == user_id)
    q = in_window(q, ExerciseLog.performed_at, resolve_window(date, days, tz_offset))
    return [exercise_out(e) for e in q.order_by(ExerciseLog.performed_at.desc()).all()]


@router.get("/weekly-summary", summary="Weekly Exercise Summary vs Goal")
def get_weekly_summary(
    week: Optional[str] = Query(None, description="Any day in the week, YYYY-MM-DD (default this week, Mon–Sun)"),
    tz_offset: int = TZ_QUERY,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    first = week_start(parse_date(week, "week") or local_today(tz_offset))
    return weekly_summary(db, user_id, first, tz_offset)


@router.delete("/{log_id}", status_code=204, summary="Delete a Workout")
def delete_exercise(log_id: int, db: Session = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    row = db.query(ExerciseLog).filter(ExerciseLog.id == log_id, ExerciseLog.user_id == user_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Workout not found.")
    db.delete(row)
    db.commit()
