"""
Vision AI meal analysis — Gemini call is mocked; tests cover upload validation,
response normalisation (glycemic load) and optional meal saving.
"""

import pytest

from app.core.config import settings
from app.services import vision_service
from app.services.vision_service import build_analysis, glycemic_load_category

URL = "/api/v1/vision/meal-analysis"
FAKE_JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64

RAW = {
    "food": "Chicken biryani", "confidence": 0.87, "is_food": True,
    "items": [{"name": "Rice", "portion": "1.5 cups", "carbs_g": 60, "calories": 300},
              {"name": "Chicken", "portion": "120 g", "carbs_g": 0, "calories": 250}],
    "carbs_g": 62, "calories": 610, "protein_g": 32, "fat_g": 22, "glycemic_index": 65,
    "advice": "Pair with salad.",
}


def test_build_analysis_computes_glycemic_load():
    a = build_analysis(RAW, model="m")
    assert a.food == "Chicken biryani"
    assert a.glycemic_load == round(65 * 62 / 100, 1)  # 40.3
    assert a.glycemic_load_category == "high"
    assert len(a.items) == 2


def test_build_analysis_fills_gaps_and_rejects_non_food():
    a = build_analysis({"items": [{"name": "Apple", "carbs_g": 15, "calories": 80}], "confidence": 92})
    assert a.food == "Apple"
    assert a.carbs_g == 15 and a.calories == 80
    assert a.confidence == 0.92
    assert a.glycemic_load == round(55 * 15 / 100, 1)
    with pytest.raises(vision_service.VisionAnalysisError):
        build_analysis({"is_food": False})


@pytest.mark.parametrize("gl,cat", [(5, "low"), (10, "low"), (15, "medium"), (20, "high")])
def test_gl_categories(gl, cat):
    assert glycemic_load_category(gl) == cat


def test_endpoint_with_mocked_gemini_and_save(api, register_user, monkeypatch):
    headers, _ = register_user()
    seen = {}

    def fake(data, mime):
        seen["mime"], seen["n"] = mime, len(data)
        return build_analysis(RAW, model="fake")

    monkeypatch.setattr(vision_service, "analyze_meal_image", fake)
    r = api.post(URL, headers=headers, files={"image": ("meal.jpg", FAKE_JPEG, "image/jpeg")},
                 data={"save": "true", "meal_type": "Lunch"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["food"] == "Chicken biryani"
    assert body["confidence"] == 0.87
    assert body["saved_meal_id"] is not None
    assert seen == {"mime": "image/jpeg", "n": len(FAKE_JPEG)}

    meals = api.get("/api/v1/health-logs/meals", headers=headers).json()
    assert meals[0]["name"] == "Chicken biryani"
    assert meals[0]["meal_type"] == "Lunch"
    assert meals[0]["carbs_grams"] == 62


def test_endpoint_rejects_bad_uploads(api, register_user, monkeypatch):
    headers, _ = register_user()
    monkeypatch.setattr(vision_service, "analyze_meal_image", lambda d, m: build_analysis(RAW))
    assert api.post(URL, headers=headers, files={"image": ("a.txt", b"hello", "text/plain")}).status_code == 415
    assert api.post(URL, headers=headers, files={"image": ("a.jpg", b"", "image/jpeg")}).status_code == 400
    monkeypatch.setattr(settings, "VISION_MAX_UPLOAD_MB", 0)
    assert api.post(URL, headers=headers, files={"image": ("a.jpg", FAKE_JPEG, "image/jpeg")}).status_code == 413


def test_endpoint_without_api_key_returns_503(api, register_user, monkeypatch):
    headers, _ = register_user()
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    r = api.post(URL, headers=headers, files={"image": ("a.jpg", FAKE_JPEG, "image/jpeg")})
    assert r.status_code == 503
