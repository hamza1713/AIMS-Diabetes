"""
Medications router: CRUD, doses, today's schedule and weekly adherence.
"""

M = "/api/v1/medications"


def test_medication_crud(api, register_user):
    headers, _ = register_user()
    r = api.post(M, headers=headers, json={
        "name": "Metformin", "dosage": "500 mg", "form": "tablet", "frequency": "twice_daily",
        "times": ["20:00", "08:00"], "instructions": "with food",
    })
    assert r.status_code == 201, r.text
    med = r.json()
    assert med["times"] == ["08:00", "20:00"]
    assert api.post(M, headers=headers, json={"name": "Bad", "times": ["25:00"]}).status_code == 422

    assert [m["name"] for m in api.get(M, headers=headers).json()] == ["Metformin"]
    upd = api.put(f"{M}/{med['id']}", headers=headers, json={"dosage": "1000 mg", "active": False})
    assert upd.json()["dosage"] == "1000 mg"
    assert api.get(M, headers=headers, params={"active_only": True}).json() == []

    other, _ = register_user()
    assert api.get(f"{M}/{med['id']}", headers=other).status_code == 404

    assert api.delete(f"{M}/{med['id']}", headers=headers).status_code == 204
    assert api.get(f"{M}/{med['id']}", headers=headers).status_code == 404


def test_doses_schedule_and_adherence(api, register_user):
    headers, _ = register_user()
    met = api.post(M, headers=headers, json={"name": "Metformin", "dosage": "500 mg", "times": ["08:00", "20:00"]}).json()
    ins = api.post(M, headers=headers, json={"name": "Insulin", "dosage": "10 units"}).json()  # 1 unscheduled slot

    today = api.get(f"{M}/today", headers=headers).json()
    assert today["scheduled"] == 3
    assert today["taken"] == 0

    d = api.post(f"{M}/{met['id']}/doses", headers=headers, json={"scheduled_time": "08:00"})
    assert d.status_code == 201, d.text
    assert d.json()["status"] == "taken"
    assert api.post(f"{M}/{met['id']}/doses", headers=headers, json={"scheduled_time": "13:00"}).status_code == 422
    api.post(f"{M}/{ins['id']}/doses", headers=headers, json={})

    today = api.get(f"{M}/today", headers=headers).json()
    assert today["taken"] == 2
    statuses = {(i["name"], i["time"]): i["status"] for i in today["items"]}
    assert statuses[("Metformin", "08:00")] == "taken"
    assert statuses[("Metformin", "20:00")] == "pending"
    assert statuses[("Insulin", None)] == "taken"

    assert len(api.get(f"{M}/{met['id']}/doses", headers=headers, params={"days": 1}).json()) == 1

    adh = api.get(f"{M}/adherence", headers=headers).json()
    assert len(adh["by_day"]) == 7
    assert adh["taken"] == 2
    # every day of the week is scheduled (no start_date), 3 slots/day
    assert adh["scheduled"] == 21
    assert adh["adherence_percent"] == round(2 / 21 * 100, 1)
    assert {m["name"] for m in adh["by_medication"]} == {"Metformin", "Insulin"}
