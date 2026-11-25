"""
Test Patient Longitudinal Tracking & Risk Screening Endpoints
"""

def test_glucose_logging_and_summary(client):
    # Log a fasting glucose measurement
    payload = {
        "measurement_type": "Fasting",
        "glucose_value": 115.0,
        "notes": "Automated test reading",
    }
    log_res = client.post("/api/v1/health-logs/glucose", json=payload)
    assert log_res.status_code == 200
    log_data = log_res.json()
    assert log_data["glucose_value"] == 115.0
    assert "id" in log_data

    # Fetch 30-day summary
    sum_res = client.get("/api/v1/health-logs/glucose/summary")
    assert sum_res.status_code == 200
    summary = sum_res.json()
    assert "average_glucose" in summary
    assert "estimated_hba1c" in summary
    assert "time_in_range_percent" in summary


def test_diabetes_risk_calculator(client):
    payload = {
        "age": 45,
        "gender": "male",
        "bmi": 28.5,
        "family_history": True,
        "high_blood_pressure": True,
        "physical_activity": "sedentary",
    }
    response = client.post("/api/v1/risk-assessment", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "risk_score" in data
    assert "risk_level" in data
    assert "recommendations" in data
    assert len(data["recommendations"]) > 0
