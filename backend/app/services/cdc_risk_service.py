"""
CDC Prediabetes Risk Test
=========================
Implements the 7-question CDC / American Diabetes Association prediabetes risk test
(the "Could you have prediabetes?" screener). Maximum score is 11; a score of 5 or
higher means a high risk of prediabetes / type 2 diabetes.

  Q1 Age            <40: 0 · 40–49: 1 · 50–59: 2 · ≥60: 3
  Q2 Sex            man: 1 · woman: 0
  Q3 Gestational    women ever diagnosed with gestational diabetes: 1
  Q4 Family history parent or sibling with diabetes: 1
  Q5 High BP        ever diagnosed: 1
  Q6 Active         physically active: 0 · not active: 1
  Q7 Weight         BMI band from the CDC height/weight chart:
                    <25: 0 · 25–<30: 1 · 30–<40: 2 · ≥40: 3
                    (Asian American cut-offs: <23: 0 · 23–<27.5: 1 · 27.5–<37.5: 2 · ≥37.5: 3)
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.timeutils import as_utc, utcnow
from app.models.db_models import RiskAssessmentLog
from app.models.domain import CDCRiskFactor, CDCRiskInput, CDCRiskResult
from app.services.user_service import compute_bmi

CDC_MAX_SCORE = 11
CDC_AT_RISK_THRESHOLD = 5


def _age_points(age: int) -> Tuple[int, str]:
    if age >= 60:
        return 3, "60 or older"
    if age >= 50:
        return 2, "50–59"
    if age >= 40:
        return 1, "40–49"
    return 0, "Younger than 40"


def _bmi_points(bmi: float, asian_american: bool) -> Tuple[int, str]:
    cuts = (23.0, 27.5, 37.5) if asian_american else (25.0, 30.0, 40.0)
    if bmi >= cuts[2]:
        return 3, f"BMI {bmi} (≥{cuts[2]})"
    if bmi >= cuts[1]:
        return 2, f"BMI {bmi} ({cuts[1]}–{cuts[2]})"
    if bmi >= cuts[0]:
        return 1, f"BMI {bmi} ({cuts[0]}–{cuts[1]})"
    return 0, f"BMI {bmi} (<{cuts[0]})"


def _band(score: int) -> Tuple[str, str]:
    if score >= CDC_AT_RISK_THRESHOLD:
        return "High", (
            f"Your score of {score}/{CDC_MAX_SCORE} means you are at high risk for prediabetes "
            "and type 2 diabetes. Only a blood test can confirm it — talk to your doctor."
        )
    if score >= 3:
        return "Moderate", (
            f"Your score of {score}/{CDC_MAX_SCORE} is below the CDC high-risk threshold of 5, "
            "but several risk factors are present. Healthy habits now can keep it that way."
        )
    return "Low", (
        f"Your score of {score}/{CDC_MAX_SCORE} indicates a low risk of prediabetes. "
        "Keep up your healthy routine and retake the test yearly."
    )


def _recommendations(factors: List[CDCRiskFactor], risk_level: str) -> List[str]:
    pts = {f.key: f.points for f in factors}
    recs: List[str] = []
    if risk_level == "High":
        recs.append("Ask your doctor for an HbA1c or fasting plasma glucose test to check for prediabetes.")
        recs.append("Consider a CDC-recognized lifestyle change program (National Diabetes Prevention Program).")
    if pts.get("weight", 0) >= 1:
        recs.append("Losing 5–7% of your body weight can cut your type 2 diabetes risk by more than half.")
    if pts.get("physical_activity", 0) >= 1:
        recs.append("Aim for at least 150 minutes of moderate activity (like brisk walking) each week.")
    if pts.get("high_blood_pressure", 0) >= 1:
        recs.append("Keep your blood pressure under control and review it regularly with your doctor.")
    if pts.get("family_history", 0) >= 1 or pts.get("gestational_diabetes", 0) >= 1:
        recs.append("Because of your history, get your blood sugar checked at least every 1–3 years.")
    recs.append("Choose water over sugary drinks and fill half your plate with non-starchy vegetables.")
    return recs


def score_cdc(input_data: CDCRiskInput, bmi: Optional[float]) -> Tuple[int, List[CDCRiskFactor]]:
    factors: List[CDCRiskFactor] = []

    p, label = _age_points(input_data.age)
    factors.append(CDCRiskFactor(key="age", question="How old are you?", answer=f"{input_data.age} ({label})", points=p, max_points=3))

    p = 1 if input_data.sex == "male" else 0
    factors.append(CDCRiskFactor(key="sex", question="Are you a man or a woman?", answer=input_data.sex.capitalize(), points=p, max_points=1))

    gd = input_data.sex == "female" and input_data.gestational_diabetes
    factors.append(CDCRiskFactor(
        key="gestational_diabetes",
        question="If you are a woman, have you ever been diagnosed with gestational diabetes?",
        answer="Not applicable" if input_data.sex == "male" else ("Yes" if gd else "No"),
        points=1 if gd else 0, max_points=1,
    ))

    factors.append(CDCRiskFactor(
        key="family_history",
        question="Do you have a mother, father, sister, or brother with diabetes?",
        answer="Yes" if input_data.family_history else "No",
        points=1 if input_data.family_history else 0, max_points=1,
    ))

    factors.append(CDCRiskFactor(
        key="high_blood_pressure",
        question="Have you ever been diagnosed with high blood pressure?",
        answer="Yes" if input_data.high_blood_pressure else "No",
        points=1 if input_data.high_blood_pressure else 0, max_points=1,
    ))

    factors.append(CDCRiskFactor(
        key="physical_activity",
        question="Are you physically active?",
        answer="Yes" if input_data.physically_active else "No",
        points=0 if input_data.physically_active else 1, max_points=1,
    ))

    if bmi is not None:
        p, label = _bmi_points(bmi, input_data.asian_american)
    else:
        p, label = 0, "Unknown (no weight/height)"
    factors.append(CDCRiskFactor(key="weight", question="What is your weight category?", answer=label, points=p, max_points=3))

    return sum(f.points for f in factors), factors


class CDCRiskService:
    @staticmethod
    def assess(
        db: Session,
        input_data: CDCRiskInput,
        user_id: str,
        profile_height_cm: Optional[float] = None,
        profile_weight_kg: Optional[float] = None,
    ) -> CDCRiskResult:
        bmi = input_data.bmi
        if bmi is None:
            bmi = compute_bmi(
                input_data.height_cm or profile_height_cm,
                input_data.weight_kg or profile_weight_kg,
            )
        if bmi is not None:
            bmi = round(bmi, 1)

        score, factors = score_cdc(input_data, bmi)
        risk_level, summary = _band(score)
        recommendations = _recommendations(factors, risk_level)
        assessed_at = utcnow()

        log_id = None
        if input_data.save:
            entry = RiskAssessmentLog(
                user_id=user_id,
                assessment_type="CDC_PREDIABETES",
                risk_score=float(score),
                risk_level=risk_level,
                answers_json={**input_data.model_dump(exclude={"save"}), "bmi": bmi},
                recommendations="\n".join(recommendations),
                assessed_at=assessed_at,
            )
            db.add(entry)
            db.commit()
            db.refresh(entry)
            log_id = entry.id

        return CDCRiskResult(
            id=log_id,
            score=score,
            max_score=CDC_MAX_SCORE,
            risk_level=risk_level,
            at_risk=score >= CDC_AT_RISK_THRESHOLD,
            bmi=bmi,
            factors=factors,
            summary=summary,
            recommendations=recommendations,
            assessed_at=as_utc(assessed_at),
        )


cdc_risk_service = CDCRiskService()
