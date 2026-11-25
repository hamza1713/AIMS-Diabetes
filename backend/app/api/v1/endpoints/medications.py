"""
Medication Endpoints
====================
  POST   /medications                     create
  GET    /medications?active_only=        list
  GET    /medications/today?date=         today's dose schedule with taken/pending status
  GET    /medications/adherence?week=     weekly adherence (Mon–Sun)
  GET    /medications/{id}                read
  PUT    /medications/{id}                partial update
  DELETE /medications/{id}
  POST   /medications/{id}/doses          mark a dose taken / skipped
  GET    /medications/{id}/doses?date=|days=
"""

from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id
from app.core.database import get_db
from app.core.timeutils import local_today, parse_date, resolve_window, to_naive_utc, week_start
from app.models.db_models import Medication, MedicationDose
from app.models.domain import (
    MedicationCreate,
    MedicationDoseCreate,
    MedicationDoseResponse,
    MedicationResponse,
    MedicationUpdate,
)
from app.services.tracking_service import (
    adherence_for_range,
    dose_out,
    in_window,
    medication_out,
    medication_schedule_for_day,
)

router = APIRouter(prefix="/medications")
TZ_QUERY = Query(0, ge=-840, le=840, description="Client UTC offset in minutes")


def _get_med(db: Session, med_id: int, user_id: str) -> Medication:
    med = db.query(Medication).filter(Medication.id == med_id, Medication.user_id == user_id).first()
    if not med:
        raise HTTPException(status_code=404, detail="Medication not found.")
    return med


@router.post("", response_model=MedicationResponse, status_code=201, summary="Add Medication")
def create_medication(payload: MedicationCreate, db: Session = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    data = payload.model_dump()
    data["start_date"] = to_naive_utc(data["start_date"])
    data["end_date"] = to_naive_utc(data["end_date"])
    med = Medication(user_id=user_id, **data)
    db.add(med)
    db.commit()
    db.refresh(med)
    return medication_out(med)


@router.get("", response_model=List[MedicationResponse], summary="List Medications")
def list_medications(
    active_only: bool = False,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    q = db.query(Medication).filter(Medication.user_id == user_id)
    if active_only:
        q = q.filter(Medication.active.is_(True))
    return [medication_out(m) for m in q.order_by(Medication.name.asc()).all()]


@router.get("/today", summary="Dose Schedule for a Day")
def medications_today(
    date: Optional[str] = Query(None, description="Local day YYYY-MM-DD (default today)"),
    tz_offset: int = TZ_QUERY,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    day = parse_date(date) or local_today(tz_offset)
    items = medication_schedule_for_day(db, user_id, day, tz_offset)
    return {
        "date": day.isoformat(),
        "scheduled": len(items),
        "taken": sum(1 for i in items if i["status"] == "taken"),
        "items": items,
    }


@router.get("/adherence", summary="Weekly Medication Adherence")
def medication_adherence(
    week: Optional[str] = Query(None, description="Any day in the week, YYYY-MM-DD (default this week)"),
    tz_offset: int = TZ_QUERY,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    first = week_start(parse_date(week, "week") or local_today(tz_offset))
    result = adherence_for_range(db, user_id, first, 7, tz_offset)
    return {"week_start": first.isoformat(), "week_end": (first + timedelta(days=6)).isoformat(), **result}


@router.get("/{med_id}", response_model=MedicationResponse, summary="Get Medication")
def get_medication(med_id: int, db: Session = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    return medication_out(_get_med(db, med_id, user_id))


@router.put("/{med_id}", response_model=MedicationResponse, summary="Update Medication")
def update_medication(
    med_id: int,
    payload: MedicationUpdate,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    med = _get_med(db, med_id, user_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if key in ("start_date", "end_date"):
            value = to_naive_utc(value)
        if key == "name" and value is None:
            continue
        setattr(med, key, value)
    db.commit()
    db.refresh(med)
    return medication_out(med)


@router.delete("/{med_id}", status_code=204, summary="Delete Medication")
def delete_medication(med_id: int, db: Session = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    db.delete(_get_med(db, med_id, user_id))
    db.commit()


@router.post("/{med_id}/doses", response_model=MedicationDoseResponse, status_code=201, summary="Record a Dose")
def record_dose(
    med_id: int,
    payload: MedicationDoseCreate,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    med = _get_med(db, med_id, user_id)
    if payload.scheduled_time and med.times and payload.scheduled_time not in med.times:
        raise HTTPException(status_code=422, detail=f"'{payload.scheduled_time}' is not one of this medication's times.")
    dose = MedicationDose(
        medication_id=med.id, user_id=user_id,
        scheduled_time=payload.scheduled_time, status=payload.status,
    )
    taken_at = to_naive_utc(payload.taken_at)
    if taken_at is not None:
        dose.taken_at = taken_at
    db.add(dose)
    db.commit()
    db.refresh(dose)
    return dose_out(dose)


@router.get("/{med_id}/doses", response_model=List[MedicationDoseResponse], summary="List Doses")
def list_doses(
    med_id: int,
    date: Optional[str] = Query(None),
    days: Optional[int] = Query(None, ge=1, le=366),
    tz_offset: int = TZ_QUERY,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    med = _get_med(db, med_id, user_id)
    q = db.query(MedicationDose).filter(MedicationDose.medication_id == med.id)
    q = in_window(q, MedicationDose.taken_at, resolve_window(date, days, tz_offset))
    return [dose_out(d) for d in q.order_by(MedicationDose.taken_at.desc()).all()]
