"""
Tracking Service — serializers & aggregations
=============================================
ORM -> response conversion and per-day aggregation helpers shared by the
glucose / meals / exercise / water / medications routers, the dashboard and analytics.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.timeutils import as_utc, day_bounds_utc, range_bounds_utc, to_local_date
from app.models.db_models import (
    ExerciseLog,
    GlucoseLog,
    MealLog,
    Medication,
    MedicationDose,
    Notification,
    UserPreferences,
    WaterLog,
)
from app.models.domain import (
    GLUCOSE_TYPE_TO_WHEN,
    ExerciseLogResponse,
    GlucoseLogResponse,
    MealLogResponse,
    MedicationDoseResponse,
    MedicationResponse,
    NotificationResponse,
    NutritionTotals,
    WaterLogResponse,
)
from app.services.user_service import glucose_status


# ── Serializers ──────────────────────────────────────────────────────────────

def glucose_out(g: GlucoseLog, prefs: Optional[UserPreferences] = None) -> GlucoseLogResponse:
    return GlucoseLogResponse(
        id=g.id,
        user_id=g.user_id,
        measurement_type=g.measurement_type,
        glucose_value=g.glucose_value,
        notes=g.notes,
        when=g.context or GLUCOSE_TYPE_TO_WHEN.get(g.measurement_type),
        status=glucose_status(g.glucose_value, g.measurement_type, prefs),
        recorded_at=as_utc(g.recorded_at),
    )


def meal_out(m: MealLog) -> MealLogResponse:
    return MealLogResponse(
        id=m.id,
        user_id=m.user_id,
        meal_type=m.meal_type,
        name=m.name,
        description=m.description or "",
        carbs_grams=m.carbs_grams,
        calories=m.calories,
        protein_g=m.protein_g,
        fat_g=m.fat_g,
        logged_at=as_utc(m.recorded_at),
    )


def exercise_out(e: ExerciseLog) -> ExerciseLogResponse:
    return ExerciseLogResponse(
        id=e.id, activity=e.activity, duration_min=e.duration_min, calories=e.calories,
        intensity=e.intensity, notes=e.notes, performed_at=as_utc(e.performed_at),
    )


def water_out(w: WaterLog) -> WaterLogResponse:
    return WaterLogResponse(id=w.id, amount_ml=w.amount_ml, recorded_at=as_utc(w.recorded_at))


def medication_out(m: Medication) -> MedicationResponse:
    return MedicationResponse(
        id=m.id, name=m.name, dosage=m.dosage, form=m.form, frequency=m.frequency,
        times=list(m.times or []), instructions=m.instructions,
        start_date=as_utc(m.start_date), end_date=as_utc(m.end_date),
        active=bool(m.active), created_at=as_utc(m.created_at),
    )


def dose_out(d: MedicationDose) -> MedicationDoseResponse:
    return MedicationDoseResponse(
        id=d.id, medication_id=d.medication_id, scheduled_time=d.scheduled_time,
        status=d.status, taken_at=as_utc(d.taken_at),
    )


def notification_out(n: Notification) -> NotificationResponse:
    return NotificationResponse(
        id=n.id, type=n.type or "info", title=n.title, body=n.body,
        read=bool(n.read), created_at=as_utc(n.created_at),
    )


# ── Generic window query ─────────────────────────────────────────────────────

def in_window(query, column, window: Optional[Tuple[datetime, datetime]]):
    if window is None:
        return query
    start, end = window
    return query.filter(column >= start, column < end)


# ── Nutrition ────────────────────────────────────────────────────────────────

def nutrition_totals(meals: Iterable[MealLog]) -> NutritionTotals:
    t = NutritionTotals()
    for m in meals:
        t.calories += m.calories or 0
        t.carbs_g += m.carbs_grams or 0
        t.protein_g += m.protein_g or 0
        t.fat_g += m.fat_g or 0
        t.meal_count += 1
    t.calories, t.carbs_g = round(t.calories, 1), round(t.carbs_g, 1)
    t.protein_g, t.fat_g = round(t.protein_g, 1), round(t.fat_g, 1)
    return t


def meals_between(db: Session, user_id: str, start: datetime, end: datetime) -> List[MealLog]:
    return (
        db.query(MealLog)
        .filter(MealLog.user_id == user_id, MealLog.recorded_at >= start, MealLog.recorded_at < end)
        .order_by(MealLog.recorded_at.asc())
        .all()
    )


# ── Glucose ──────────────────────────────────────────────────────────────────

def glucose_values_between(db: Session, user_id: str, start: datetime, end: datetime) -> List[GlucoseLog]:
    return (
        db.query(GlucoseLog)
        .filter(
            GlucoseLog.user_id == user_id,
            GlucoseLog.recorded_at >= start,
            GlucoseLog.recorded_at < end,
            GlucoseLog.measurement_type != "HbA1c",
        )
        .order_by(GlucoseLog.recorded_at.asc())
        .all()
    )


def glucose_stats(values: List[float], low: float = 70.0, high: float = 180.0) -> Dict[str, Optional[float]]:
    if not values:
        return {"readings": 0, "average": None, "time_in_range_percent": None,
                "estimated_hba1c": None, "hypo_readings": 0, "hyper_readings": 0,
                "min": None, "max": None}
    avg = sum(values) / len(values)
    in_range = sum(1 for v in values if low <= v <= high)
    return {
        "readings": len(values),
        "average": round(avg, 1),
        "time_in_range_percent": round(in_range / len(values) * 100, 1),
        "estimated_hba1c": round((avg + 46.7) / 28.7, 1),
        "hypo_readings": sum(1 for v in values if v < low),
        "hyper_readings": sum(1 for v in values if v > high),
        "min": round(min(values), 1),
        "max": round(max(values), 1),
    }


def daily_glucose_averages(
    logs: List[GlucoseLog], first_day: date, n_days: int, tz_offset: int = 0
) -> List[Dict]:
    buckets: Dict[date, List[float]] = defaultdict(list)
    for g in logs:
        buckets[to_local_date(g.recorded_at, tz_offset)].append(g.glucose_value)
    out = []
    for i in range(n_days):
        d = first_day + timedelta(days=i)
        vals = buckets.get(d, [])
        out.append({"date": d.isoformat(), "average": round(sum(vals) / len(vals), 1) if vals else None,
                    "readings": len(vals)})
    return out


# ── Exercise / Water ─────────────────────────────────────────────────────────

def exercise_between(db: Session, user_id: str, start: datetime, end: datetime) -> List[ExerciseLog]:
    return (
        db.query(ExerciseLog)
        .filter(ExerciseLog.user_id == user_id, ExerciseLog.performed_at >= start, ExerciseLog.performed_at < end)
        .order_by(ExerciseLog.performed_at.asc())
        .all()
    )


def water_total(db: Session, user_id: str, day: date, tz_offset: int = 0) -> int:
    start, end = day_bounds_utc(day, tz_offset)
    rows = (
        db.query(WaterLog)
        .filter(WaterLog.user_id == user_id, WaterLog.recorded_at >= start, WaterLog.recorded_at < end)
        .all()
    )
    return int(sum(r.amount_ml for r in rows))


# ── Medications ──────────────────────────────────────────────────────────────

def medication_active_on(m: Medication, day: date) -> bool:
    if not m.active:
        return False
    if m.start_date and m.start_date.date() > day:
        return False
    if m.end_date and m.end_date.date() < day:
        return False
    return True


def scheduled_slots(m: Medication) -> List[Optional[str]]:
    """Dose slots per day: the configured times, or a single unscheduled slot."""
    return list(m.times) if m.times else [None]


def doses_between(db: Session, user_id: str, start: datetime, end: datetime) -> List[MedicationDose]:
    return (
        db.query(MedicationDose)
        .filter(MedicationDose.user_id == user_id, MedicationDose.taken_at >= start, MedicationDose.taken_at < end)
        .all()
    )


def medication_schedule_for_day(
    db: Session, user_id: str, day: date, tz_offset: int = 0
) -> List[Dict]:
    """Every dose slot due on ``day`` with whether it was taken / skipped."""
    meds = db.query(Medication).filter(Medication.user_id == user_id).all()
    start, end = day_bounds_utc(day, tz_offset)
    doses = doses_between(db, user_id, start, end)
    by_med: Dict[int, List[MedicationDose]] = defaultdict(list)
    for d in doses:
        by_med[d.medication_id].append(d)

    items = []
    for m in meds:
        if not medication_active_on(m, day):
            continue
        remaining = sorted(by_med.get(m.id, []), key=lambda d: d.taken_at)
        for slot in scheduled_slots(m):
            match = next((d for d in remaining if d.scheduled_time == slot), None)
            if match is None:
                match = next((d for d in remaining if d.scheduled_time is None), None)
            if match is not None:
                remaining.remove(match)
            items.append({
                "medication_id": m.id,
                "name": m.name,
                "dosage": m.dosage,
                "time": slot,
                "status": match.status if match else "pending",
                "dose_id": match.id if match else None,
                "taken_at": as_utc(match.taken_at) if match else None,
            })
    items.sort(key=lambda i: (i["time"] or "99:99", i["name"]))
    return items


def adherence_for_range(
    db: Session, user_id: str, first_day: date, n_days: int, tz_offset: int = 0
) -> Dict:
    """Scheduled vs taken dose counts per day and per medication."""
    meds = db.query(Medication).filter(Medication.user_id == user_id).all()
    start, end = range_bounds_utc(first_day, first_day + timedelta(days=n_days), tz_offset)
    doses = [d for d in doses_between(db, user_id, start, end) if d.status == "taken"]
    taken_by: Dict[Tuple[int, date], int] = defaultdict(int)
    for d in doses:
        taken_by[(d.medication_id, to_local_date(d.taken_at, tz_offset))] += 1

    by_day = []
    per_med: Dict[int, Dict] = {m.id: {"medication_id": m.id, "name": m.name, "scheduled": 0, "taken": 0} for m in meds}
    tot_s = tot_t = 0
    for i in range(n_days):
        day = first_day + timedelta(days=i)
        s = t = 0
        for m in meds:
            if not medication_active_on(m, day):
                continue
            slots = len(scheduled_slots(m))
            took = min(taken_by.get((m.id, day), 0), slots)
            s += slots
            t += took
            per_med[m.id]["scheduled"] += slots
            per_med[m.id]["taken"] += took
        tot_s += s
        tot_t += t
        by_day.append({"date": day.isoformat(), "scheduled": s, "taken": t,
                       "adherence_percent": round(t / s * 100, 1) if s else None})

    meds_out = []
    for v in per_med.values():
        if v["scheduled"]:
            v["adherence_percent"] = round(v["taken"] / v["scheduled"] * 100, 1)
            meds_out.append(v)
    return {
        "scheduled": tot_s,
        "taken": tot_t,
        "adherence_percent": round(tot_t / tot_s * 100, 1) if tot_s else None,
        "by_day": by_day,
        "by_medication": meds_out,
    }
