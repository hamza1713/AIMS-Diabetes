"""
Users router: /users/me profile (BMI) and /users/me/preferences.
"""

U = "/api/v1/users"


def test_profile_requires_token(api):
    assert api.get(f"{U}/me").status_code == 401
    assert api.get(f"{U}/me", headers={"X-User-Id": "alice"}).status_code == 401


def test_get_and_update_profile_with_bmi(api, register_user):
    headers, body = register_user(name="Bilal")
    me = api.get(f"{U}/me", headers=headers).json()
    assert me["name"] == "Bilal"
    assert me["bmi"] is None

    res = api.put(f"{U}/me", headers=headers, json={
        "age": 45, "gender": "male", "height_cm": 175, "weight_kg": 80,
        "diabetes_type": "type2", "photo_url": "https://example.com/p.png",
    })
    assert res.status_code == 200, res.text
    me = res.json()
    assert me["bmi"] == 26.1
    assert me["bmi_category"] == "Overweight"
    assert me["diabetes_type"] == "type2"
    assert me["name"] == "Bilal"  # untouched


def test_profile_validation_and_email_clash(api, register_user):
    h1, b1 = register_user()
    _, b2 = register_user()
    assert api.put(f"{U}/me", headers=h1, json={"gender": "robot"}).status_code == 422
    assert api.put(f"{U}/me", headers=h1, json={"email": b2["_email"]}).status_code == 409
    ok = api.put(f"{U}/me", headers=h1, json={"email": "NEW_" + b1["_email"]})
    assert ok.status_code == 200
    assert ok.json()["email"] == ("new_" + b1["_email"]).lower()


def test_preferences_defaults_and_update(api, register_user):
    headers, _ = register_user()
    prefs = api.get(f"{U}/me/preferences", headers=headers).json()
    assert prefs["glucose_unit"] == "mg/dL"
    assert prefs["medication_reminders"] is True
    assert prefs["glucose_alerts"] is True
    assert prefs["daily_tips"] is True
    assert prefs["water_goal_ml"] == 2000

    res = api.put(f"{U}/me/preferences", headers=headers, json={
        "glucose_unit": "mmol/L", "language": "ur", "theme": "dark", "daily_tips": False, "water_goal_ml": 2500,
    })
    assert res.status_code == 200
    p = res.json()
    assert (p["glucose_unit"], p["language"], p["theme"], p["daily_tips"], p["water_goal_ml"]) == ("mmol/L", "ur", "dark", False, 2500)
    assert p["glucose_alerts"] is True

    assert api.put(f"{U}/me/preferences", headers=headers, json={"glucose_unit": "bananas"}).status_code == 422
    assert api.put(f"{U}/me/preferences", headers=headers,
                   json={"target_glucose_min": 150, "target_glucose_max": 120}).status_code == 422
