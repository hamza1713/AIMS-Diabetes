"""
Vision AI Endpoint
==================
  POST /vision/meal-analysis   multipart/form-data
       image      (file, required)  JPEG / PNG / WEBP / HEIC, <= VISION_MAX_UPLOAD_MB
       save       (bool, optional)  also log the result as a meal
       meal_type  (str, optional)   meal type used when save=true (default "Snack")
"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id
from app.core.config import settings
from app.core.database import get_db
from app.core.limiter import limiter
from app.models.domain import VisionMealAnalysis
from app.services import vision_service
from app.services.health_service import health_service

router = APIRouter(prefix="/vision")

ALLOWED_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/heic", "image/heif"}


@router.post("/meal-analysis", response_model=VisionMealAnalysis, summary="Analyse a Meal Photo")
@limiter.limit("15/minute")
async def meal_analysis(
    request: Request,
    image: UploadFile = File(..., description="Meal photo"),
    save: bool = Form(False),
    meal_type: str = Form("Snack"),
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    mime = (image.content_type or "").lower()
    if mime not in ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail="Upload a JPEG, PNG, WEBP or HEIC image.")
    max_bytes = settings.VISION_MAX_UPLOAD_MB * 1024 * 1024
    data = await image.read(max_bytes + 1)
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded image is empty.")
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=f"Image must be at most {settings.VISION_MAX_UPLOAD_MB} MB.")

    try:
        result = await run_in_threadpool(vision_service.analyze_meal_image, data, "image/jpeg" if mime == "image/jpg" else mime)
    except vision_service.VisionUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except vision_service.VisionAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if save:
        meal = health_service.add_meal_log(
            db=db,
            meal_type=meal_type or "Snack",
            description=", ".join(i.name for i in result.items) or result.food,
            carbs_grams=result.carbs_g,
            user_id=user_id,
            name=result.food,
            calories=result.calories,
            protein_g=result.protein_g,
            fat_g=result.fat_g,
        )
        result.saved_meal_id = meal.id
    return result
