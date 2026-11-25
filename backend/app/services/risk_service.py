from sqlalchemy.orm import Session
from typing import Dict, Any, List
from app.models.db_models import RiskAssessmentLog
from app.models.domain import RiskAssessmentInput, RiskAssessmentResult

class DiabetesRiskService:
    @staticmethod
    def calculate_risk(db: Session, input_data: RiskAssessmentInput, user_id: str = "default_user") -> RiskAssessmentResult:
        """
        Calculates combined ADA & FINDRISC Diabetes Risk Score.
        Evaluates Age, BMI, Family History, High Blood Pressure, Physical Activity, and Ethnicity risk factors.
        """
        score = 0.0
        factors_flagged = []

        # 1. Age Factor
        if input_data.age >= 65:
            score += 4.0
            factors_flagged.append("Age >= 65 (+4 pts)")
        elif input_data.age >= 50:
            score += 3.0
            factors_flagged.append("Age 50-64 (+3 pts)")
        elif input_data.age >= 40:
            score += 2.0
            factors_flagged.append("Age 40-49 (+2 pts)")

        # 2. BMI Factor
        if input_data.bmi >= 30:
            score += 3.0
            factors_flagged.append("Obesity (BMI >= 30) (+3 pts)")
        elif input_data.bmi >= 25:
            score += 1.0
            factors_flagged.append("Overweight (BMI 25-29.9) (+1 pt)")

        # 3. Family History
        if input_data.family_history:
            score += 5.0
            factors_flagged.append("First-degree relative with Type 2 Diabetes (+5 pts)")

        # 4. Hypertension (High Blood Pressure)
        if input_data.high_blood_pressure:
            score += 2.0
            factors_flagged.append("Diagnosed High Blood Pressure (+2 pts)")

        # 5. Physical Activity
        if input_data.physical_activity.lower() in ["sedentary", "low"]:
            score += 2.0
            factors_flagged.append("Physical Inactivity / Sedentary Lifestyle (+2 pts)")

        # Determine Clinical Risk Category
        if score >= 12:
            risk_level = "Very High"
            summary = "Very High probability of Type 2 Diabetes or Prediabetes. Immediate medical consultation recommended."
            recommendations = [
                "Schedule a Diagnostic Fasting Plasma Glucose & HbA1c blood test with your healthcare provider.",
                "Initiate structured low-carbohydrate nutritional guidance (supported by clinical literature).",
                "Aim for 150+ minutes of weekly moderate aerobic and resistance exercise.",
                "Discuss preventive pharmacological interventions (e.g. Metformin / SGLT2 inhibitors) with an endocrinologist."
            ]
        elif score >= 8:
            risk_level = "High"
            summary = "High risk of developing Type 2 Diabetes within 10 years."
            recommendations = [
                "Schedule a screening HbA1c test with a clinical provider.",
                "Adopt dietary carbohydrate restriction to reduce postprandial glycemic spikes.",
                "Increase daily physical activity to improve insulin sensitivity."
            ]
        elif score >= 5:
            risk_level = "Moderate"
            summary = "Slightly elevated risk. Lifestyle modifications can prevent progression."
            recommendations = [
                "Monitor fasting glucose periodically.",
                "Incorporate balanced whole-food meals with adequate dietary fiber."
            ]
        else:
            risk_level = "Low"
            summary = "Low immediate risk. Current health factors are within normal reference ranges."
            recommendations = [
                "Maintain healthy body weight, active routine, and balanced nutrition."
            ]

        # Log assessment result in database
        log_entry = RiskAssessmentLog(
            user_id=user_id,
            assessment_type="ADA_FINDRISC_COMBINED_CLINICAL",
            risk_score=score,
            risk_level=risk_level,
            answers_json=input_data.model_dump() if hasattr(input_data, "model_dump") else input_data.dict(),
            recommendations="\n".join(recommendations)
        )
        db.add(log_entry)
        db.commit()

        return RiskAssessmentResult(
            assessment_type="ADA & FINDRISC Combined Standardized Score",
            risk_score=score,
            risk_level=risk_level,
            summary=summary,
            recommendations=recommendations
        )

risk_service = DiabetesRiskService()
