"""
Clinical Risk Assessment Endpoints
==================================
Implements standardized ADA and FINDRISC Diabetes Risk Score calculation
and longitudinal historical risk assessment records.
"""

from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id
from app.core.database import get_db
from app.models.db_models import RiskAssessmentLog
from app.models.domain import CDCRiskInput, CDCRiskResult, RiskAssessmentInput, RiskAssessmentResult
from app.services.cdc_risk_service import cdc_risk_service
from app.services.risk_service import risk_service
from app.services.user_service import get_user_by_uid, notify

router = APIRouter()


@router.post("/risk-assessment", response_model=RiskAssessmentResult, summary="Calculate Diabetes Risk Score")
def calculate_diabetes_risk(
    input_data: RiskAssessmentInput,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """Calculates standardized ADA & FINDRISC Diabetes Risk Score with actionable clinical recommendations."""
    return risk_service.calculate_risk(db=db, input_data=input_data, user_id=current_user_id)


@router.post("/risk-assessment/cdc", response_model=CDCRiskResult, summary="CDC Prediabetes Risk Test (7 questions)")
def calculate_cdc_risk(
    input_data: CDCRiskInput,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    CDC / ADA prediabetes risk test: age, sex, gestational diabetes, family history,
    high blood pressure, physical activity and weight (BMI band). Score out of 11;
    5 or more = high risk. Missing weight/height fall back to the saved profile.
    """
    user = get_user_by_uid(db, current_user_id)
    result = cdc_risk_service.assess(
        db=db,
        input_data=input_data,
        user_id=current_user_id,
        profile_height_cm=user.height_cm if user else None,
        profile_weight_kg=user.weight_kg if user else None,
    )
    if input_data.save:
        notify(db, current_user_id, "Risk assessment complete",
               f"Your CDC prediabetes score is {result.score}/{result.max_score} ({result.risk_level} risk).",
               type_="info")
    return result


@router.get("/risk-assessment/history", summary="Get Historical Risk Assessment Logs")
def get_risk_assessment_history(
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """Retrieves past risk score calculation history ordered newest first."""
    return (
        db.query(RiskAssessmentLog)
        .filter(RiskAssessmentLog.user_id == current_user_id)
        .order_by(RiskAssessmentLog.assessed_at.desc())
        .all()
    )
