from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from app.core.timeutils import to_naive_utc
from app.models.db_models import GlucoseLog, MealLog
from app.models.domain import GlucoseLogCreate

class HealthDataService:
    @staticmethod
    def add_glucose_log(db: Session, entry: GlucoseLogCreate, user_id: str = "default_user") -> GlucoseLog:
        """Adds a new blood glucose reading to patient history."""
        log = GlucoseLog(
            user_id=user_id,
            measurement_type=entry.measurement_type,
            glucose_value=entry.glucose_value,
            notes=entry.notes,
            context=getattr(entry, "when", None),
        )
        recorded_at = to_naive_utc(getattr(entry, "recorded_at", None))
        if recorded_at is not None:
            log.recorded_at = recorded_at
        db.add(log)
        db.commit()
        db.refresh(log)
        return log

    @staticmethod
    def get_glucose_summary(db: Session, user_id: str = "default_user", days: int = 30) -> Dict[str, Any]:
        """Calculates clinical glucose statistics: Average, Time-in-Range (TIR 70-180 mg/dL), and HbA1c estimate."""
        since_date = datetime.utcnow() - timedelta(days=days)
        logs = db.query(GlucoseLog).filter(
            GlucoseLog.user_id == user_id,
            GlucoseLog.recorded_at >= since_date
        ).all()

        if not logs:
            return {
                "total_readings": 0,
                "average_glucose": 0.0,
                "time_in_range_percent": 0.0,
                "estimated_hba1c": 0.0,
                "hyperglycemia_readings": 0,
                "hypoglycemia_readings": 0,
                "status": "No glucose readings recorded in this timeframe."
            }

        values = [l.glucose_value for l in logs if l.measurement_type != "HbA1c"]
        if not values:
            return {
                "total_readings": len(logs),
                "average_glucose": 0.0,
                "time_in_range_percent": 0.0,
                "estimated_hba1c": 0.0,
                "status": "Only HbA1c records found."
            }

        avg_glucose = sum(values) / len(values)
        in_range = len([v for v in values if 70 <= v <= 180])
        hyper = len([v for v in values if v > 180])
        hypo = len([v for v in values if v < 70])
        tir_percent = (in_range / len(values)) * 100

        # ADAG formula for estimated HbA1c (%): (Average Glucose mg/dL + 46.7) / 28.7
        eA1c = round((avg_glucose + 46.7) / 28.7, 1)

        return {
            "total_readings": len(values),
            "average_glucose": round(avg_glucose, 1),
            "time_in_range_percent": round(tir_percent, 1),
            "estimated_hba1c": eA1c,
            "hyperglycemia_readings": hyper,
            "hypoglycemia_readings": hypo,
            "status": "Optimal Glycemic Control" if tir_percent >= 70 else "Suboptimal Glycemic Control"
        }

    @staticmethod
    def add_meal_log(
        db: Session,
        meal_type: str,
        description: str,
        carbs_grams: Optional[float],
        user_id: str = "default_user",
        name: Optional[str] = None,
        calories: Optional[float] = None,
        protein_g: Optional[float] = None,
        fat_g: Optional[float] = None,
        logged_at: Optional[datetime] = None,
    ) -> MealLog:
        """Adds a new meal entry with carbohydrate content and optional macros."""
        meal = MealLog(
            user_id=user_id,
            meal_type=meal_type,
            description=description or "",
            carbs_grams=carbs_grams,
            name=name,
            calories=calories,
            protein_g=protein_g,
            fat_g=fat_g,
        )
        logged_at = to_naive_utc(logged_at)
        if logged_at is not None:
            meal.recorded_at = logged_at
        db.add(meal)
        db.commit()
        db.refresh(meal)
        return meal

health_service = HealthDataService()
