"""
Tracking routers: glucose (when/time/date filters), meals (macros, daily totals),
exercise (weekly summary), water (daily total).
"""

from datetime import datetime, timedelta, timezone

H = "/api/v1/health-logs"


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def test_glucose_when_time_and_filters(api, register_user):
    headers, _ = register_user()
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)

    r = api.post(f"{H}/glucose", headers=headers, json={"glucose_value": 145, "when": "after_meal", "recorded_at": _iso(now)})
    assert r.status_code == 200, r.text
    g = r.json()
    assert g["when"] == "after_meal"
    assert g["measurement_type"] == "Postprandial"
    assert g["status"] == "normal"
    assert g["recorded_at"].endswith(("Z", "+00:00"))

    api.post(f"{H}/glucose", headers=headers, json={"glucose_value": 95, "when": "fasting", "recorded_at": _iso(yesterday)})
    # legacy body still works and derives "when"
    legacy = api.post(f"{H}/glucose", headers=headers, json={"measurement_type": "Fasting", "glucose_value": 60}).json()
    assert legacy["when"] == "fasting"
    assert legacy["status"] == "low"

    all_logs = api.get(f"{H}/glucose", headers=headers).json()
    assert len(all_logs) == 3
    today = api.get(f"{H}/glucose", headers=headers, params={"date": now.date().isoformat()}).json()
    assert {x["glucose_value"] for x in today} == {145, 60}
    last2 = api.get(f"{H}/glucose", headers=headers, params={"days": 2}).json()
    assert len(last2) == 3
    assert api.get(f"{H}/glucose", headers=headers, params={"date": "25-11-2026"}).status_code == 422

    # delete
    assert api.delete(f"{H}/glucose/{legacy['id']}", headers=headers).status_code == 204
    assert api.delete(f"{H}/glucose/{legacy['id']}", headers=headers).status_code == 404


def test_glucose_isolated_between_users(api, register_user):
    h1, _ = register_user()
    h2, _ = register_user()
    api.post(f"{H}/glucose", headers=h1, json={"glucose_value": 110, "when": "random"})
    assert api.get(f"{H}/glucose", headers=h2).json() == []


def test_meals_macros_and_daily_totals(api, register_user):
    headers, _ = register_user()
    day = datetime.now(timezone.utc).date().isoformat()
    m1 = api.post(f"{H}/meals", headers=headers, json={
        "meal_type": "Breakfast", "name": "Oatmeal", "carbs_grams": 40, "calories": 300, "protein_g": 10, "fat_g": 6,
    })
    assert m1.status_code == 200, m1.text
    body = m1.json()
    assert body["name"] == "Oatmeal"
    assert body["description"] == "Oatmeal"
    assert "logged_at" in body
    api.post(f"{H}/meals", headers=headers, json={"meal_type": "Lunch", "description": "Rice & dal", "carbs_grams": 70, "calories": 550})
    # yesterday's meal must not count today
    api.post(f"{H}/meals", headers=headers, json={
        "meal_type": "Dinner", "name": "Old", "carbs_grams": 99, "calories": 999,
        "logged_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
    })

    meals = api.get(f"{H}/meals", headers=headers, params={"date": day}).json()
    assert len(meals) == 2
    totals = api.get(f"{H}/meals/daily-totals", headers=headers, params={"date": day}).json()
    assert totals["totals"] == {"calories": 850, "carbs_g": 110, "protein_g": 10, "fat_g": 6, "meal_count": 2}
    assert totals["goals"]["calories"] == 2000
    assert set(totals["by_meal_type"]) == {"Breakfast", "Lunch"}


def test_exercise_and_weekly_summary(api, register_user):
    headers, _ = register_user()
    r = api.post(f"{H}/exercise", headers=headers, json={"activity": "Walking", "duration_min": 30, "calories": 120, "intensity": "moderate"})
    assert r.status_code == 200, r.text
    api.post(f"{H}/exercise", headers=headers, json={"activity": "Cycling", "duration_min": 45, "intensity": "high"})
    assert api.post(f"{H}/exercise", headers=headers, json={"activity": "Yoga", "duration_min": 0}).status_code == 422

    assert len(api.get(f"{H}/exercise", headers=headers, params={"days": 1}).json()) == 2
    s = api.get(f"{H}/exercise/weekly-summary", headers=headers).json()
    assert s["total_minutes"] == 75
    assert s["goal_minutes"] == 150
    assert s["goal_percent"] == 50.0
    assert s["active_days"] == 1
    assert len(s["by_day"]) == 7
    assert api.delete(f"{H}/exercise/{r.json()['id']}", headers=headers).status_code == 204


def test_water_daily_total_and_goal_notification(api, register_user):
    headers, _ = register_user()
    api.put("/api/v1/users/me/preferences", headers=headers, json={"water_goal_ml": 500})
    api.post(f"{H}/water", headers=headers, json={"amount_ml": 250})
    api.post(f"{H}/water", headers=headers, json={"amount_ml": 300})
    assert api.post(f"{H}/water", headers=headers, json={"amount_ml": -5}).status_code == 422

    d = api.get(f"{H}/water/daily", headers=headers).json()
    assert d["total_ml"] == 550
    assert d["goal_ml"] == 500
    assert d["percent"] == 110.0
    assert d["remaining_ml"] == 0
    assert len(d["entries"]) == 2

    titles = [n["title"] for n in api.get("/api/v1/notifications", headers=headers).json()["items"]]
    assert "Hydration goal reached!" in titles
