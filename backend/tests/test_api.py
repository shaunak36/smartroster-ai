from datetime import date

from app.api.routes.organization import create_employee
from app.models import Organization, UserRole
from app.schemas.api import EmployeeCreate
from app.services.auth import OrganizationContext


def test_create_employee_sets_authenticated_organization(db_session):
    organization = Organization(name="Employee API Organization", is_active=True)
    db_session.add(organization)
    db_session.commit()

    employee = create_employee(
        EmployeeCreate(
            employee_code="EMP-ORG-API",
            name="Organization Employee",
            email="employee-org-api@example.com",
        ),
        db_session,
        OrganizationContext(
            user=None,
            organization_id=organization.id,
            role=UserRole.ADMIN,
        ),
    )

    assert employee.organization_id == organization.id


def employee_payload(code: str = "EMP-API"):
    return {
        "employee_code": code,
        "name": "API Employee",
        "email": f"{code.lower()}@example.com",
        "daily_capacity_units": 8,
        "weekly_capacity_units": 40,
        "monthly_capacity_units": 160,
        "max_assignments_per_day": 3,
    }


def test_employee_brand_process_crud_and_safe_delete(api_client):
    employee_response = api_client.post("/api/employees", json=employee_payload())
    assert employee_response.status_code == 201
    employee_id = employee_response.json()["id"]

    brand = api_client.post("/api/brands", json={"code": "BR-API", "name": "API Brand"})
    process = api_client.post("/api/processes", json={"code": "CS-API", "name": "Support"})
    assert brand.status_code == 201
    assert process.status_code == 201

    assignment = api_client.post(
        "/api/assignments",
        json={
            "employee_id": employee_id,
            "brand_id": brand.json()["id"],
            "process_id": process.json()["id"],
            "effective_start_date": "2026-01-01",
        },
    )
    assert assignment.status_code == 201

    blocked = api_client.delete(f"/api/employees/{employee_id}")
    assert blocked.status_code == 409
    assert api_client.get(f"/api/employees/{employee_id}").status_code == 200


def test_missing_and_invalid_relationships_are_rejected(api_client):
    missing = api_client.get("/api/employees/9999")
    assert missing.status_code == 404

    invalid = api_client.post(
        "/api/assignments",
        json={
            "employee_id": 9999,
            "brand_id": 9999,
            "process_id": 9999,
            "effective_start_date": "2026-01-01",
        },
    )
    assert invalid.status_code == 422


def test_duplicate_assignment_and_effective_overlap_are_rejected(api_client):
    employee_id = api_client.post("/api/employees", json=employee_payload()).json()["id"]
    brand_id = api_client.post("/api/brands", json={"code": "BR-DUP", "name": "Duplicate"}).json()["id"]
    process_id = api_client.post("/api/processes", json={"code": "CS-DUP", "name": "Support"}).json()["id"]
    payload = {
        "employee_id": employee_id,
        "brand_id": brand_id,
        "process_id": process_id,
        "effective_start_date": "2026-01-01",
        "effective_end_date": "2026-03-31",
    }
    assert api_client.post("/api/assignments", json=payload).status_code == 201

    overlap = {**payload, "effective_start_date": "2026-03-01"}
    assert api_client.post("/api/assignments", json=overlap).status_code == 409

    duplicate = {**payload, "effective_end_date": None}
    assert api_client.post("/api/assignments", json=duplicate).status_code == 409


def test_assignment_update_cannot_extend_into_another_effective_period(api_client):
    employee_id = api_client.post("/api/employees", json=employee_payload("EMP-UPD")).json()["id"]
    brand_id = api_client.post("/api/brands", json={"code": "BR-UPD", "name": "Update"}).json()["id"]
    process_id = api_client.post("/api/processes", json={"code": "CS-UPD", "name": "Support"}).json()["id"]
    first = {
        "employee_id": employee_id,
        "brand_id": brand_id,
        "process_id": process_id,
        "effective_start_date": "2026-01-01",
        "effective_end_date": "2026-03-31",
    }
    second = {
        **first,
        "effective_start_date": "2026-04-01",
        "effective_end_date": "2026-06-30",
    }
    first_id = api_client.post("/api/assignments", json=first).json()["id"]
    assert api_client.post("/api/assignments", json=second).status_code == 201
    assert api_client.patch(
        f"/api/assignments/{first_id}",
        json={"effective_end_date": "2026-04-15"},
    ).status_code == 409


def test_availability_precedence_leave_exception_and_pending_exception(api_client):
    employee_id = api_client.post("/api/employees", json=employee_payload("EMP-AVAIL")).json()["id"]
    pattern = api_client.post(
        "/api/weekly-off-patterns",
        json={
            "employee_id": employee_id,
            "recurrence_rule": "FREQ=WEEKLY;BYDAY=SU",
            "effective_start_date": "2026-01-01",
        },
    )
    assert pattern.status_code == 201

    sunday = "2026-02-01"
    resolved = api_client.get(f"/api/employees/{employee_id}/availability/{sunday}")
    assert resolved.status_code == 200
    assert resolved.json()["available"] is False
    assert "Recurring weekly off" in resolved.json()["reason"]

    pending = api_client.post(
        "/api/weekly-off-exceptions",
        json={
            "employee_id": employee_id,
            "date": sunday,
            "exception_type": "working_day",
            "reason": "Awaiting approval",
            "approval_status": "pending",
        },
    )
    assert pending.status_code == 201
    assert api_client.get(f"/api/employees/{employee_id}/availability/{sunday}").json()["available"] is False

    approved = api_client.post(
        "/api/weekly-off-exceptions",
        json={
            "employee_id": employee_id,
            "date": sunday,
            "exception_type": "working_day",
            "reason": "Approved coverage",
            "approval_status": "approved",
        },
    )
    assert approved.status_code == 201
    assert api_client.get(f"/api/employees/{employee_id}/availability/{sunday}").json()["available"] is True

    leave = api_client.post(
        "/api/leave-requests",
        json={
            "employee_id": employee_id,
            "start_date": sunday,
            "end_date": sunday,
            "leave_type": "planned",
            "status": "approved",
        },
    )
    assert leave.status_code == 201
    blocked = api_client.get(f"/api/employees/{employee_id}/availability/{sunday}")
    assert blocked.json()["available"] is False
    assert "Approved leave" in blocked.json()["reason"]


def test_rejected_exception_and_pending_leave_do_not_block(api_client):
    employee_id = api_client.post("/api/employees", json=employee_payload("EMP-REJECTED")).json()["id"]
    sunday = "2026-02-01"
    assert api_client.post(
        "/api/weekly-off-patterns",
        json={
            "employee_id": employee_id,
            "recurrence_rule": "FREQ=WEEKLY;BYDAY=SU",
            "effective_start_date": "2026-01-01",
        },
    ).status_code == 201
    assert api_client.post(
        "/api/weekly-off-exceptions",
        json={
            "employee_id": employee_id,
            "date": sunday,
            "exception_type": "working_day",
            "reason": "Rejected request",
            "approval_status": "rejected",
        },
    ).status_code == 201
    assert api_client.post(
        "/api/leave-requests",
        json={
            "employee_id": employee_id,
            "start_date": sunday,
            "end_date": sunday,
            "leave_type": "planned",
            "status": "pending",
        },
    ).status_code == 201

    resolved = api_client.get(f"/api/employees/{employee_id}/availability/{sunday}")
    assert resolved.json()["available"] is False
    assert "Recurring weekly off" in resolved.json()["reason"]


def test_approved_availability_override_is_blocked_by_approved_leave(api_client):
    employee_id = api_client.post("/api/employees", json=employee_payload("EMP-OVERRIDE")).json()["id"]
    target = "2026-02-01"
    assert api_client.post(
        "/api/availability-overrides",
        json={
            "employee_id": employee_id,
            "date": target,
            "status": "available",
            "reason": "Approved override",
            "approval_status": "approved",
        },
    ).status_code == 201
    leave = api_client.post(
        "/api/leave-requests",
        json={
            "employee_id": employee_id,
            "start_date": target,
            "end_date": target,
            "leave_type": "planned",
            "status": "approved",
        },
    )
    assert leave.status_code == 201

    resolved = api_client.get(f"/api/employees/{employee_id}/availability/{target}")
    assert resolved.json()["available"] is False
    assert "Approved leave" in resolved.json()["reason"]


def test_availability_override_list_returns_saved_records(api_client):
    employee_id = api_client.post("/api/employees", json=employee_payload("EMP-OVERRIDE-LIST")).json()["id"]
    created = api_client.post(
        "/api/availability-overrides",
        json={
            "employee_id": employee_id,
            "date": "2026-11-18",
            "status": "unavailable",
            "reason": "Testing availability list",
            "approval_status": "approved",
        },
    )
    assert created.status_code == 201

    response = api_client.get("/api/availability-overrides?limit=200")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["id"] == created.json()["id"]


def test_capacity_and_calendar_validation(api_client):
    employee = api_client.post("/api/employees", json=employee_payload("EMP-CAP"))
    assert employee.status_code == 201
    invalid_capacity = api_client.patch(
        f"/api/employees/{employee.json()['id']}",
        json={"daily_capacity_units": -1},
    )
    assert invalid_capacity.status_code == 422

    brand_id = api_client.post("/api/brands", json={"code": "BR-RULE", "name": "Rule Brand"}).json()["id"]
    process_id = api_client.post("/api/processes", json={"code": "CS-RULE", "name": "Support"}).json()["id"]
    invalid_rule = api_client.post(
        "/api/operating-rules",
        json={
            "brand_id": brand_id,
            "process_id": process_id,
            "operating_weekdays": "MTW",
            "sunday_working": False,
            "public_holiday_working": False,
            "required_coverage": True,
            "minimum_daily_staffing": -1,
            "effective_start_date": "2026-03-01",
        },
    )
    assert invalid_rule.status_code == 422


def test_reactivating_overlapping_effective_rules_is_rejected(api_client):
    employee_id = api_client.post("/api/employees", json=employee_payload("EMP-RULE-UPD")).json()["id"]
    brand_id = api_client.post("/api/brands", json={"code": "BR-RULE-UPD", "name": "Rule Update"}).json()["id"]
    process_id = api_client.post("/api/processes", json={"code": "CS-RULE-UPD", "name": "Support"}).json()["id"]
    period = {"effective_start_date": "2026-01-01", "effective_end_date": "2026-03-31"}

    workload_two = api_client.post(
        "/api/employee-workload-rules",
        json={"employee_id": employee_id, "brand_id": brand_id, "process_id": process_id,
              "daily_capacity_units": 5, "is_active": False, **period},
    )
    assert workload_two.status_code == 201
    workload_one = api_client.post(
        "/api/employee-workload-rules",
        json={"employee_id": employee_id, "brand_id": brand_id, "process_id": process_id,
              "daily_capacity_units": 4, "is_active": True, **period},
    )
    assert workload_one.status_code == 201
    assert api_client.patch(
        f"/api/employee-workload-rules/{workload_two.json()['id']}",
        json={"is_active": True},
    ).status_code == 409

    operating_two = api_client.post(
        "/api/operating-rules",
        json={"brand_id": brand_id, "process_id": process_id, "operating_weekdays": "MTW",
              "sunday_working": False, "public_holiday_working": False,
              "required_coverage": True, "minimum_daily_staffing": 1,
              "is_active": False, **period},
    )
    assert operating_two.status_code == 201
    operating_one = api_client.post(
        "/api/operating-rules",
        json={"brand_id": brand_id, "process_id": process_id, "operating_weekdays": "MTW",
              "sunday_working": False, "public_holiday_working": False,
              "required_coverage": True, "minimum_daily_staffing": 1, **period},
    )
    assert operating_one.status_code == 201
    assert api_client.patch(
        f"/api/operating-rules/{operating_two.json()['id']}",
        json={"is_active": True},
    ).status_code == 409

    brand_rule_two = api_client.post(
        "/api/brand-process-workload-rules",
        json={"brand_id": brand_id, "process_id": process_id, "workload_units": 3,
              "is_active": False, **period},
    )
    assert brand_rule_two.status_code == 201
    brand_rule_one = api_client.post(
        "/api/brand-process-workload-rules",
        json={"brand_id": brand_id, "process_id": process_id, "workload_units": 2, **period},
    )
    assert brand_rule_one.status_code == 201
    assert api_client.patch(
        f"/api/brand-process-workload-rules/{brand_rule_two.json()['id']}",
        json={"is_active": True},
    ).status_code == 409

    pattern_two = api_client.post(
        "/api/weekly-off-patterns",
        json={"employee_id": employee_id, "recurrence_rule": "FREQ=WEEKLY;BYDAY=SA",
              "is_active": False, **period},
    )
    assert pattern_two.status_code == 201
    pattern_one = api_client.post(
        "/api/weekly-off-patterns",
        json={"employee_id": employee_id, "recurrence_rule": "FREQ=WEEKLY;BYDAY=SU", **period},
    )
    assert pattern_one.status_code == 201
    assert api_client.patch(
        f"/api/weekly-off-patterns/{pattern_two.json()['id']}",
        json={"is_active": True},
    ).status_code == 409

    compatibility_two = api_client.post(
        "/api/assignment-compatibility-rules",
        json={"employee_id": employee_id, "brand_id": brand_id, "process_id": process_id,
              "is_compatible": False, "reason": "Backup", "is_active": False, **period},
    )
    assert compatibility_two.status_code == 201
    compatibility_one = api_client.post(
        "/api/assignment-compatibility-rules",
        json={"employee_id": employee_id, "brand_id": brand_id, "process_id": process_id,
              "is_compatible": True, "reason": "Primary", **period},
    )
    assert compatibility_one.status_code == 201
    assert api_client.patch(
        f"/api/assignment-compatibility-rules/{compatibility_two.json()['id']}",
        json={"is_active": True},
    ).status_code == 409


def test_nullable_patch_and_database_conflict_are_safe(api_client):
    employee = api_client.post("/api/employees", json=employee_payload("EMP-PATCH"))
    assert employee.status_code == 201
    pod = api_client.post("/api/pods", json={"code": "POD-PATCH", "name": "Patch Pod"})
    assert pod.status_code == 201
    updated = api_client.patch(
        f"/api/employees/{employee.json()['id']}",
        json={"pod_id": pod.json()["id"]},
    )
    assert updated.status_code == 200
    cleared = api_client.patch(
        f"/api/employees/{employee.json()['id']}",
        json={"pod_id": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["pod_id"] is None

    duplicate = api_client.post("/api/employees", json=employee_payload("EMP-PATCH"))
    assert duplicate.status_code == 409
    assert "sqlite" not in duplicate.text.lower()
    assert "integrityerror" not in duplicate.text.lower()
