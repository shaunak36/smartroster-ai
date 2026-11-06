from datetime import date


def _create_roster_configuration(client):
    employees = []
    for suffix in ("A", "B"):
        response = client.post(
            "/api/employees",
            json={
                "employee_code": f"EMP-E2E-{suffix}",
                "name": f"E2E Employee {suffix}",
                "email": f"e2e-{suffix.lower()}@example.com",
                "daily_capacity_units": 8,
                "weekly_capacity_units": 40,
                "monthly_capacity_units": 160,
                "max_assignments_per_day": 2,
            },
        )
        assert response.status_code == 201
        employees.append(response.json())
    brand = client.post(
        "/api/brands", json={"code": "BR-E2E", "name": "E2E Brand"}
    )
    process = client.post(
        "/api/processes", json={"code": "PR-E2E", "name": "E2E Process"}
    )
    assert brand.status_code == process.status_code == 201
    brand = brand.json()
    process = process.json()
    for employee in employees:
        response = client.post(
            "/api/assignments",
            json={
                "employee_id": employee["id"],
                "brand_id": brand["id"],
                "process_id": process["id"],
                "effective_start_date": "2026-01-01",
            },
        )
        assert response.status_code == 201
    operating = client.post(
        "/api/operating-rules",
        json={
            "brand_id": brand["id"],
            "process_id": process["id"],
            "effective_start_date": "2026-01-01",
            "operating_weekdays": "MO,TU,WE",
            "sunday_working": False,
            "public_holiday_working": False,
            "required_coverage": True,
            "minimum_daily_staffing": 1,
        },
    )
    workload = client.post(
        "/api/brand-process-workload-rules",
        json={
            "brand_id": brand["id"],
            "process_id": process["id"],
            "effective_start_date": "2026-01-01",
            "workload_units": 4,
        },
    )
    assert operating.status_code == workload.status_code == 201
    return employees, brand, process


def test_stage4g_complete_http_workflow_and_failures(api_client):
    employees, brand, process = _create_roster_configuration(api_client)

    generated = api_client.post(
        "/api/rosters/generate", json={"year": 2026, "month": 1}
    )
    assert generated.status_code == 200
    generated_body = generated.json()
    assert generated_body["validation"]["is_valid"] is True
    assert generated_body["assignments"]

    saved = api_client.post(
        "/api/rosters/save",
        json={
            "year": 2026,
            "month": 1,
            "solver_status": generated_body["solver_status"],
            "assignments": generated_body["assignments"],
        },
    )
    assert saved.status_code == 201
    roster = saved.json()
    roster_id = roster["id"]
    first_version_id = roster["current_version_id"]

    retrieved = api_client.get(f"/api/rosters/{roster_id}")
    assert retrieved.status_code == 200
    assert retrieved.json()["current_version_id"] == first_version_id
    assignments = api_client.get(f"/api/rosters/{roster_id}/assignments")
    assert assignments.status_code == 200
    current_assignment = next(
        item for item in assignments.json() if item["date"] == "2026-01-05"
    )

    invalid_preview = api_client.post(
        f"/api/rosters/{roster_id}/manual/preview",
        json={
            "operation": "replace",
            "expected_version_id": first_version_id,
            "changed_by": "e2e.operator",
            "previous_assignment": current_assignment,
            "assignment": {
                "employee_id": 99999,
                "date": "2026-01-05",
                "brand_id": brand["id"],
                "process_id": process["id"],
                "workload_units": 4,
            },
        },
    )
    assert invalid_preview.status_code == 200
    assert invalid_preview.json()["validation"]["is_valid"] is False
    assert api_client.get(
        f"/api/rosters/{roster_id}"
    ).json()["current_version_id"] == first_version_id

    valid_replacement = {
        "employee_id": (
            employees[0]["id"]
            if current_assignment["employee_id"] == employees[1]["id"]
            else employees[1]["id"]
        ),
        "date": "2026-01-05",
        "brand_id": brand["id"],
        "process_id": process["id"],
        "workload_units": 4,
    }
    valid_preview = api_client.post(
        f"/api/rosters/{roster_id}/manual/preview",
        json={
            "operation": "replace",
            "expected_version_id": first_version_id,
            "changed_by": "e2e.operator",
            "previous_assignment": current_assignment,
            "assignment": valid_replacement,
        },
    )
    assert valid_preview.status_code == 200
    assert valid_preview.json()["validation"]["is_valid"] is True

    accepted = api_client.post(
        f"/api/rosters/{roster_id}/manual/accept",
        json={
            "operation": "replace",
            "expected_version_id": first_version_id,
            "changed_by": "e2e.operator",
            "previous_assignment": current_assignment,
            "assignment": valid_replacement,
        },
    )
    assert accepted.status_code == 200
    second_version_id = accepted.json()["id"]
    assert accepted.json()["source_version_id"] == first_version_id

    stale = api_client.post(
        f"/api/rosters/{roster_id}/manual/accept",
        json={
            "operation": "remove",
            "expected_version_id": first_version_id,
            "changed_by": "e2e.operator",
            "previous_assignment": valid_replacement,
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "roster_version_conflict"

    history = api_client.get(f"/api/rosters/{roster_id}/versions")
    assert history.status_code == 200
    assert [item["id"] for item in history.json()] == [
        first_version_id, second_version_id
    ]
    comparison = api_client.get(
        f"/api/rosters/{roster_id}/versions/"
        f"{first_version_id}/compare/{second_version_id}"
    )
    assert comparison.status_code == 200
    assert comparison.json()["added"] == [valid_replacement]


def test_stage4g_invalid_solver_status_and_missing_roster(api_client):
    invalid_status = api_client.post(
        "/api/rosters/save",
        json={
            "year": 2026,
            "month": 1,
            "solver_status": "infeasible",
            "assignments": [],
        },
    )
    assert invalid_status.status_code == 422

    missing = api_client.get("/api/rosters/99999/assignments")
    assert missing.status_code == 404


def test_stage4g_invalid_configuration_is_reported(api_client):
    employee = api_client.post(
        "/api/employees",
        json={
            "employee_code": "EMP-BAD-CONFIG",
            "name": "Bad Config Employee",
            "email": "bad-config@example.com",
        },
    )
    assert employee.status_code == 201
    brand = api_client.post(
        "/api/brands", json={"code": "BR-BAD-CONFIG", "name": "Bad Config Brand"}
    )
    process = api_client.post(
        "/api/processes", json={"code": "PR-BAD-CONFIG", "name": "Bad Config Process"}
    )
    assert brand.status_code == process.status_code == 201
    brand = brand.json()
    process = process.json()
    assert api_client.post(
        "/api/operating-rules",
        json={
            "brand_id": brand["id"],
            "process_id": process["id"],
            "effective_start_date": "2026-01-01",
            "operating_weekdays": "MO,TU,WE",
            "sunday_working": False,
            "public_holiday_working": False,
            "required_coverage": True,
            "minimum_daily_staffing": 1,
        },
    ).status_code == 201
    assert api_client.post(
        "/api/brand-process-workload-rules",
        json={
            "brand_id": brand["id"],
            "process_id": process["id"],
            "effective_start_date": "2026-01-01",
            "workload_units": 4,
        },
    ).status_code == 201
    response = api_client.post(
        "/api/rosters/preview", json={"year": 2026, "month": 1}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_configuration"
