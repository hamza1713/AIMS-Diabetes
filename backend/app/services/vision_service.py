"""
Vision AI — Meal Photo Analysis
===============================
Sends a meal photo to Gemini (multimodal) and returns the recognised food,
estimated carbohydrates / calories / macros, and the glycemic load.

GL = GI × available carbs (g) / 100 — low ≤ 10, medium 11–19, high ≥ 20.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from app.core.config import settings
from app.core.logger import get_logger
from app.models.domain import VisionFoodItem, VisionMealAnalysis

log = get_logger(__name__)


class VisionUnavailableError(RuntimeError):
    """Raised when no Gemini API key is configured."""


class VisionAnalysisError(RuntimeError):
    """Raised when the model call fails or returns unusable output."""


VISION_PROMPT = """You are a clinical nutrition assistant for people with diabetes.
Identify the food in this photo and estimate its nutrition for the portion shown.
Respond with ONLY a JSON object, no markdown, using exactly these keys:
{
  "food": "short name of the whole meal",
  "confidence": 0.0-1.0 (how sure you are about the identification),
  "is_food": true/false,
  "items": [{"name": "...", "portion": "e.g. 1 cup", "carbs_g": number, "calories": number}],
  "carbs_g": number (total available carbohydrate in grams),
  "calories": number (total kcal),
  "protein_g": number,
  "fat_g": number,
  "glycemic_index": number (weighted average GI of the meal, 0-100),
  "advice": "one short sentence of diabetes-friendly advice about this meal"
}"""


def glycemic_load_category(gl: float) -> str:
    if gl <= 10:
        return "low"
    if gl < 20:
        return "medium"
    return "high"


def _num(v: Any) -> Optional[float]:
    try:
        return None if v is None else round(float(v), 1)
    except (TypeError, ValueError):
        return None


def _extract_json(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            raise VisionAnalysisError("Model did not return JSON.")
        return json.loads(m.group(0))


def build_analysis(raw: Dict[str, Any], model: Optional[str] = None) -> VisionMealAnalysis:
    """Normalises the model's JSON into the API response (also used by tests)."""
    if raw.get("is_food") is False:
        raise VisionAnalysisError("No food was recognised in the image.")
    items = []
    for it in raw.get("items") or []:
        if isinstance(it, dict) and it.get("name"):
            items.append(VisionFoodItem(
                name=str(it["name"]),
                portion=it.get("portion"),
                carbs_g=_num(it.get("carbs_g")),
                calories=_num(it.get("calories")),
            ))
    carbs = _num(raw.get("carbs_g"))
    if carbs is None:
        carbs = round(sum(i.carbs_g or 0 for i in items), 1)
    calories = _num(raw.get("calories"))
    if calories is None:
        calories = round(sum(i.calories or 0 for i in items), 1)
    gi = _num(raw.get("glycemic_index"))
    gl = _num(raw.get("glycemic_load"))
    if gl is None:
        gl = round((gi if gi is not None else 55.0) * carbs / 100.0, 1)
    try:
        conf = float(raw.get("confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf / 100.0 if conf > 1 else conf))
    return VisionMealAnalysis(
        food=str(raw.get("food") or (items[0].name if items else "Unknown meal")),
        confidence=round(conf, 2),
        items=items,
        carbs_g=carbs,
        calories=calories,
        protein_g=_num(raw.get("protein_g")),
        fat_g=_num(raw.get("fat_g")),
        glycemic_index=gi,
        glycemic_load=gl,
        glycemic_load_category=glycemic_load_category(gl),
        advice=raw.get("advice"),
        model=model,
    )


def analyze_meal_image(image_bytes: bytes, mime_type: str) -> VisionMealAnalysis:
    """Calls Gemini vision. Raises VisionUnavailableError / VisionAnalysisError."""
    if not settings.GEMINI_API_KEY:
        raise VisionUnavailableError("GEMINI_API_KEY is not configured.")
    model = settings.GEMINI_VISION_MODEL
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        resp = client.models.generate_content(
            model=model,
            contents=[types.Part.from_bytes(data=image_bytes, mime_type=mime_type), VISION_PROMPT],
            config=types.GenerateContentConfig(temperature=0.1, response_mime_type="application/json"),
        )
        raw = _extract_json(resp.text or "")
    except (VisionAnalysisError, VisionUnavailableError):
        raise
    except Exception as exc:
        log.error("Gemini vision meal analysis failed: %s", exc)
        raise VisionAnalysisError("Meal analysis failed. Please try again.") from exc
    return build_analysis(raw, model=model)
