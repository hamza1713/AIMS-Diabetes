"""
Notifications, home dashboard and monthly analytics.
"""

from datetime import datetime, timezone


def test_notifications_list_and_mark_read(api, register_user):
    headers, _ = register_user()
    data = api.get("/api/v1/notifications", headers=headers).json()
    assert data["unread_count"] == 1  # welcome
    assert data["items"][0]["title"].startswith("Welcome")

    # out-of-range reading -> glucose alert
    api.post("/api/v1/health-logs/glucose", headers=headers, json={"glucose_value": 250, "when": "after_meal"})
    data = api.get("/api/v1/notifications", headers=headers).json()
    assert data["unread_count"] == 2
    assert data["items"][0]["type"] == "alert"

    one = api.post(f"/api/v1/notifications/{data['items'][0]['id']}/read", headers=headers).json()
    assert one["read"] is True
    assert api.post("/api/v1/notifications/mark-all-read", headers=headers).json()["updated"] == 1
    assert api.get("/api/v1/notifications", headers=headers, params={"unread_only": True}).json() == {"items": [], "unread_count": 0}


def test_glucose_alert_respects_preference(api, register_user):
    headers, _ = register_user()
    api.put("/api/v1/users/me/preferences", headers=headers, json={"glucose_alerts": False})
    api.post("/api/v1/health-logs/glucose", headers=headers, json={"glucose_value": 300})
    types = [n["type"] for n in api.get("/api/v1/notifications", headers=headers).json()["items"]]
    assert "alert" not in types


def test_dashboard_aggregate(api, register_user):
    headers, body = register_user(name="Sara")
    empty = api.get("/api/v1/dashboard", headers=headers).json()
    assert empty["user"]["name"] == "Sara"
    assert empty["glucose"]["latest"] is None
    assert len(empty["glucose"]["sparkline"]) == 7
    assert empty["last_risk_assessment"] is None

    api.post("/api/v1/health-logs/glucose", headers=headers, json={"glucose_value": 120, "when": "fasting"})
    api.post("/api/v1/health-logs/water", headers=headers, json={"amount_ml": 400})
    api.post("/api/v1/health-logs/exercise", headers=headers, json={"activity": "Walk", "duration_min": 20})
    api.post("/api/v1/health-logs/meals", headers=headers, json={"meal_type": "Lunch", "name": "Salad", "carbs_grams": 15, "calories": 200})
    api.post("/api/v1/medications", headers=headers, json={"name": "Metformin", "dosage": "500 mg", "times": ["08:00"]})
    api.post("/api/v1/risk-assessment/cdc", headers=headers, json={
        "age": 30, "sex": "female", "family_history": False, "high_blood_pressure": False,
        "physically_active": True, "bmi": 22,
    })

    d = api.get("/api/v1/dashboard", headers=headers).json()
    assert d["glucose"]["latest"]["glucose_value"] == 120
    assert d["glucose"]["sparkline"][-1]["average"] == 120
    assert d["glucose"]["last_7_days"]["readings"] == 1
    assert d["water"]["total_ml"] == 400
    assert d["exercise"]["today_minutes"] == 20
    assert d["meals"]["calories"] == 200
    assert d["medications"] == {"scheduled_today": 1, "taken_today": 0,
                                "next_dose": d["medications"]["next_dose"]}
    assert d["medications"]["next_dose"]["name"] == "Metformin"
    assert d["reminders"][0]["type"] == "medication"
    assert d["last_risk_assessment"]["assessment_type"] == "CDC_PREDIABETES"
    assert d["unread_notifications"] >= 1


def test_analytics_summary(api, register_user):
    headers, _ = register_user()
    for v in (100, 150, 200):
        api.post("/api/v1/health-logs/glucose", headers=headers, json={"glucose_value": v})
    api.post("/api/v1/health-logs/meals", headers=headers, json={"meal_type": "Dinner", "carbs_grams": 60, "calories": 600})
    api.post("/api/v1/health-logs/exercise", headers=headers, json={"activity": "Run", "duration_min": 30})

    month = datetime.now(timezone.utc).strftime("%Y-%m")
    s = api.get("/api/v1/analytics/summary", headers=headers, params={"month": month}).json()
    assert s["month"] == month
    g = s["glucose"]
    assert g["readings"] == 3
    assert g["average"] == 150.0
    assert g["time_in_range_percent"] == 66.7
    assert g["hyper_readings"] == 1
    assert g["trend"] == "insufficient_data"
    assert len(g["daily"]) == s["days_in_month"]
    assert s["nutrition"]["avg_carbs_per_day"] == 60
    assert s["exercise"]["active_days"] == 1
    assert api.get("/api/v1/analytics/summary", headers=headers, params={"month": "2026/11"}).status_code == 422

    # a past month with no data
    past = api.get("/api/v1/analytics/summary", headers=headers, params={"month": "2020-02"}).json()
    assert past["days_in_month"] == 29
    assert past["glucose"]["readings"] == 0
