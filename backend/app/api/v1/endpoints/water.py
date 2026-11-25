"""
Water Intake Endpoints
======================
  POST   /health-logs/water                 add a drink (ml)
  GET    /health-logs/water?date=|days=      list (newest first)
  GET    /health-logs/water/daily?date=      total vs daily goal (default 2000 ml)
  DELETE /health-logs/water/{id}
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id
from app.core.database import get_db
from app.core.timeutils import day_bounds_utc, local_today, parse_date, resolve_window, to_naive_utc
from app.models.db_models import WaterLog
from app.models.domain import WaterLogCreate, WaterLogResponse
from app.services.tracking_service import in_window, water_out, water_total
from app.services.user_service import get_preferences, notify

router = APIRouter(prefix="/health-logs/water")
TZ_QUERY = Query(0, ge=-840, le=840, description="Client UTC offset in minutes")


@router.post("", response_model=WaterLogResponse, summary="Log Water Intake")
def log_water(payload: WaterLogCreate, db: Session = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    today = local_today()
    before = water_total(db, user_id, today)
    row = WaterLog(user_id=user_id, amount_ml=payload.amount_ml)
    recorded_at = to_naive_utc(payload.recorded_at)
    if recorded_at is not None:
        row.recorded_at = recorded_at
    db.add(row)
    db.commit()
    db.refresh(row)
    goal = get_preferences(db, user_id).water_goal_ml
    if goal and before < goal <= water_total(db, user_id, today):
        notify(db, user_id, "Hydration goal reached!", f"You drank {goal} ml today. Great job!", type_="achievement")
    return water_out(row)


@router.get("", response_model=List[WaterLogResponse], summary="List Water Intake")
def list_water(
    date: Optional[str] = Query(None, description="Local day YYYY-MM-DD"),
    days: Optional[int] = Query(None, ge=1, le=366),
    tz_offset: int = TZ_QUERY,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    q = db.query(WaterLog).filter(WaterLog.user_id == user_id)
    q = in_window(q, WaterLog.recorded_at, resolve_window(date, days, tz_offset))
    return [water_out(w) for w in q.order_by(WaterLog.recorded_at.desc()).all()]


@router.get("/daily", summary="Daily Water Total vs Goal")
def daily_water(
    date: Optional[str] = Query(None, description="Local day YYYY-MM-DD (default today)"),
    tz_offset: int = TZ_QUERY,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    day = parse_date(date) or local_today(tz_offset)
    start, end = day_bounds_utc(day, tz_offset)
    rows = (
        db.query(WaterLog)
        .filter(WaterLog.user_id == user_id, WaterLog.recorded_at >= start, WaterLog.recorded_at < end)
        .order_by(WaterLog.recorded_at.asc())
        .all()
    )
    total = int(sum(r.amount_ml for r in rows))
    goal = get_preferences(db, user_id).water_goal_ml
    return {
        "date": day.isoformat(),
        "total_ml": total,
        "goal_ml": goal,
        "percent": round(total / goal * 100, 1) if goal else None,
        "remaining_ml": max(goal - total, 0) if goal else None,
        "entries": [water_out(r) for r in rows],
    }


@router.delete("/{log_id}", status_code=204, summary="Delete a Water Entry")
def delete_water(log_id: int, db: Session = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    row = db.query(WaterLog).filter(WaterLog.id == log_id, WaterLog.user_id == user_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Water entry not found.")
    db.delete(row)
    db.commit()
