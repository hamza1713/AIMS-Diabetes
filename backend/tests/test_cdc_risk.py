"""
CDC 7-question prediabetes risk test scoring.
"""

import pytest

from app.models.domain import CDCRiskInput
from app.services.cdc_risk_service import score_cdc

URL = "/api/v1/risk-assessment/cdc"


def _inp(**kw):
    base = dict(age=30, sex="female", gestational_diabetes=False, family_history=False,
                high_blood_pressure=False, physically_active=True)
    base.update(kw)
    return CDCRiskInput(**base)


@pytest.mark.parametrize("age,pts", [(39, 0), (40, 1), (49, 1), (50, 2), (59, 2), (60, 3), (85, 3)])
def test_age_points(age, pts):
    score, factors = score_cdc(_inp(age=age), bmi=22)
    assert factors[0].key == "age" and factors[0].points == pts
    assert score == pts


@pytest.mark.parametrize("bmi,asian,pts", [
    (24.9, False, 0), (25, False, 1), (29.9, False, 1), (30, False, 2), (39.9, False, 2), (40, False, 3),
    (22.9, True, 0), (23, True, 1), (27.5, True, 2), (37.5, True, 3),
])
def test_bmi_band_points(bmi, asian, pts):
    _, factors = score_cdc(_inp(asian_american=asian), bmi=bmi)
    assert factors[-1].key == "weight" and factors[-1].points == pts


def test_gestational_only_counts_for_women():
    s_f, _ = score_cdc(_inp(sex="female", gestational_diabetes=True), bmi=22)
    s_m, f_m = score_cdc(_inp(sex="male", gestational_diabetes=True), bmi=22)
    assert s_f == 1
    assert s_m == 1  # male +1, gestational ignored
    assert next(f for f in f_m if f.key == "gestational_diabetes").answer == "Not applicable"


def test_scale_is_out_of_11():
    # The paper test sums to 11, but the sex (+1 man) and gestational (+1 woman) points
    # are mutually exclusive, so the highest achievable score for one person is 10.
    worst = dict(age=65, family_history=True, high_blood_pressure=True, physically_active=False)
    score_m, factors = score_cdc(_inp(sex="male", **worst), bmi=41)
    score_f, _ = score_cdc(_inp(sex="female", gestational_diabetes=True, **worst), bmi=41)
    assert score_m == score_f == 10
    assert sum(f.max_points for f in factors) == 11
    assert len(factors) == 7


def test_cdc_endpoint_high_risk_and_history(api, register_user):
    headers, _ = register_user()
    res = api.post(URL, headers=headers, json={
        "age": 52, "sex": "male", "family_history": True, "high_blood_pressure": False,
        "physically_active": False, "weight_kg": 95, "height_cm": 175,
    })
    assert res.status_code == 200, res.text
    r = res.json()
    # age 2 + male 1 + family 1 + inactive 1 + BMI 31.0 -> 2 = 7
    assert r["bmi"] == 31.0
    assert r["score"] == 7
    assert r["max_score"] == 11
    assert r["risk_level"] == "High"
    assert r["at_risk"] is True
    assert len(r["factors"]) == 7
    assert r["recommendations"]
    assert r["id"] is not None

    hist = api.get("/api/v1/risk-assessment/history", headers=headers).json()
    assert hist[0]["assessment_type"] == "CDC_PREDIABETES"
    assert hist[0]["risk_score"] == 7


def test_cdc_endpoint_uses_profile_bmi_and_low_band(api, register_user):
    headers, _ = register_user()
    api.put("/api/v1/users/me", headers=headers, json={"height_cm": 165, "weight_kg": 55})
    r = api.post(URL, headers=headers, json={
        "age": 25, "sex": "female", "family_history": False, "high_blood_pressure": False,
        "physically_active": True, "save": False,
    }).json()
    assert r["bmi"] == 20.2
    assert r["score"] == 0
    assert r["risk_level"] == "Low"
    assert r["id"] is None
    assert api.get("/api/v1/risk-assessment/history", headers=headers).json() == []


def test_cdc_moderate_band(api, register_user):
    headers, _ = register_user()
    r = api.post(URL, headers=headers, json={
        "age": 45, "sex": "male", "family_history": True, "high_blood_pressure": False,
        "physically_active": True, "bmi": 23, "save": False,
    }).json()
    assert r["score"] == 3
    assert r["risk_level"] == "Moderate"
    assert r["at_risk"] is False
