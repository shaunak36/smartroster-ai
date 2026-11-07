from datetime import date

import pytest

from app.models import (
    Employee,
    EmployeeAssignment,
    Organization,
    Roster,
    RosterAssignment,
)
from app.services.roster import (
    ManualChange,
    RosterConcurrencyError,
    RosterPersistenceError,
    accept_manual_change,
    apply_manual_change,
    persist_roster,
    preview_manual_change,
    run_roster_pipeline,
    valid_manual_replacement_employee_ids,
)
from app.services.scheduling import SchedulingAssignment, SchedulingStatus
from app.services.validation import RosterValidationResult
from tests.test_configuration import configured_employee


def test_pipeline_generates_and_persists_valid_roster(db_session):
    employee, brand, process = configured_employee(db_session)

    pipeline = run_roster_pipeline(db_session, 2026, 1)

    assert pipeline.solver_result.status in (
        SchedulingStatus.OPTIMAL,
        SchedulingStatus.FEASIBLE,
    )
    assert pipeline.validation_result.is_valid
    version = persist_roster(db_session, pipeline)

    roster = db_session.get(Roster, version.roster_id)
    assert roster is not None
    assert roster.current_version_id == version.id
    assert roster.month == 1
    assert all(
        row.employee_id == employee.id
        and row.brand_id == brand.id
        and row.process_id == process.id
        for row in version.assignments
    )


def test_generated_roster_save_persists_employee_organization(db_session):
    employee, brand, process = configured_employee(db_session)
    organization = Organization(name="Roster Save Org", is_active=True)
    db_session.add(organization)
    db_session.flush()
    employee.organization_id = organization.id
    brand.organization_id = organization.id
    process.organization_id = organization.id
    db_session.commit()

    pipeline = run_roster_pipeline(db_session, 2026, 1)
    version = persist_roster(db_session, pipeline)

    roster = db_session.get(Roster, version.roster_id)
    assert roster is not None
    assert roster.organization_id == organization.id
    assert roster.current_version_id == version.id


def test_invalid_roster_is_rejected_without_persistence(db_session):
    employee, brand, process = configured_employee(db_session)
    assignment = SchedulingAssignment(
        employee.id, date(2026, 1, 5), brand.id + 100, process.id, 4
    )
    pipeline = run_roster_pipeline(db_session, 2026, 1, (assignment,))

    assert not pipeline.validation_result.is_valid
    with pytest.raises(RosterPersistenceError):
        persist_roster(db_session, pipeline)
    assert db_session.query(Roster).count() == 0


def test_duplicate_period_and_duplicate_assignment_roll_back(db_session):
    employee, brand, process = configured_employee(db_session)
    first = run_roster_pipeline(db_session, 2026, 1)
    persist_roster(db_session, first)

    with pytest.raises(RosterPersistenceError):
        persist_roster(db_session, first)
    assert db_session.query(Roster).count() == 1

    duplicate = SchedulingAssignment(
        employee.id, date(2026, 1, 5), brand.id, process.id, 4
    )
    invalid_result = first.validation_result
    duplicate_pipeline = first.__class__(
        2026,
        2,
        first.solver_result,
        invalid_result,
        (duplicate, duplicate),
    )
    with pytest.raises(RosterPersistenceError):
        persist_roster(db_session, duplicate_pipeline)
    assert db_session.query(Roster).count() == 1


def test_roster_api_preview_save_and_retrieve(api_client):
    employee = api_client.post(
        "/api/employees",
        json={
            "employee_code": "EMP-API-ROSTER",
            "name": "API Roster Employee",
            "email": "api-roster@example.com",
            "daily_capacity_units": 8,
            "weekly_capacity_units": 40,
            "monthly_capacity_units": 160,
            "max_assignments_per_day": 2,
        },
    ).json()
    brand = api_client.post(
        "/api/brands", json={"code": "BR-API-ROSTER", "name": "API Roster Brand"}
    ).json()
    process = api_client.post(
        "/api/processes",
        json={"code": "PR-API-ROSTER", "name": "API Roster Process"},
    ).json()
    period = {
        "effective_start_date": "2026-01-01",
        "employee_id": employee["id"],
        "brand_id": brand["id"],
        "process_id": process["id"],
    }
    assert api_client.post("/api/assignments", json=period).status_code == 201
    rule = {
        "brand_id": brand["id"],
        "process_id": process["id"],
        "effective_start_date": "2026-01-01",
        "operating_weekdays": "MO,TU,WE",
        "sunday_working": False,
        "public_holiday_working": False,
        "required_coverage": True,
        "minimum_daily_staffing": 1,
    }
    assert api_client.post("/api/operating-rules", json=rule).status_code == 201
    workload = {
        "brand_id": brand["id"],
        "process_id": process["id"],
        "effective_start_date": "2026-01-01",
        "workload_units": 4,
    }
    assert api_client.post(
        "/api/brand-process-workload-rules", json=workload
    ).status_code == 201

    preview = api_client.post("/api/rosters/preview", json={"year": 2026, "month": 1})
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["validation"]["is_valid"] is True
    assert preview_body["assignments"]

    saved = api_client.post(
        "/api/rosters/save",
        json={
            "year": 2026,
            "month": 1,
            "solver_status": preview_body["solver_status"],
            "assignments": preview_body["assignments"],
        },
    )
    assert saved.status_code == 201
    roster_id = saved.json()["id"]
    retrieved = api_client.get(f"/api/rosters/{roster_id}/assignments")
    assert retrieved.status_code == 200
    assert retrieved.json()


def _persist_two_employee_roster(db_session):
    employee, brand, process = configured_employee(db_session)
    organization = Organization(name="Manual roster organization", is_active=True)
    db_session.add(organization)
    db_session.flush()
    employee.organization_id = organization.id
    brand.organization_id = organization.id
    process.organization_id = organization.id
    db_session.flush()
    pipeline = run_roster_pipeline(db_session, 2026, 1)
    version = persist_roster(db_session, pipeline)
    second = Employee(
        employee_code="EMP-MANUAL-2",
        name="Manual Replacement",
        email="manual-2@example.com",
        organization_id=organization.id,
        daily_capacity_units=8,
        weekly_capacity_units=40,
        monthly_capacity_units=160,
        max_assignments_per_day=2,
    )
    db_session.add(second)
    db_session.flush()
    db_session.add(EmployeeAssignment(
        employee_id=second.id,
        brand_id=brand.id,
        process_id=process.id,
        effective_start_date=date(2026, 1, 1),
    ))
    db_session.commit()
    return version, employee, second, brand, process


def test_valid_manual_replacements_only_returns_employees_passing_roster_rules(
    db_session,
):
    version, employee, eligible, brand, process = _persist_two_employee_roster(
        db_session
    )
    ineligible = Employee(
        organization_id=version.roster.organization_id,
        employee_code="EMP-MANUAL-INELIGIBLE",
        name="Not Assigned",
        email="not-assigned@example.com",
    )
    db_session.add(ineligible)
    db_session.flush()
    existing = version.assignments[0]
    previous = SchedulingAssignment(
        existing.employee_id,
        existing.date,
        existing.brand_id,
        existing.process_id,
        existing.workload_units,
    )

    candidate_ids = valid_manual_replacement_employee_ids(
        db_session,
        version.roster_id,
        version.id,
        previous,
        version.roster.organization_id,
    )

    assert eligible.id in candidate_ids
    assert employee.id not in candidate_ids
    assert ineligible.id not in candidate_ids


def test_manual_preview_does_not_mutate_saved_version(db_session):
    version, _, second, brand, process = _persist_two_employee_roster(db_session)
    existing = version.assignments[0]
    proposed = SchedulingAssignment(
        second.id, existing.date, brand.id, process.id, 4
    )
    _, preview = preview_manual_change(
        db_session,
        version.roster_id,
        version.id,
        ManualChange("replace", proposed, SchedulingAssignment(
            existing.employee_id, existing.date, existing.brand_id,
            existing.process_id, existing.workload_units,
        )),
    )

    assert preview.validation_result.is_valid
    db_session.expire_all()
    current = db_session.get(Roster, version.roster_id).current_version
    assert current.id == version.id
    assert {
        (row.employee_id, row.date, row.brand_id, row.process_id)
        for row in current.assignments
    } == {
        (row.employee_id, row.date, row.brand_id, row.process_id)
        for row in version.assignments
    }


def test_manual_accept_creates_history_and_supports_operations(db_session):
    version, employee, second, brand, process = _persist_two_employee_roster(db_session)
    existing = version.assignments[0]
    previous = SchedulingAssignment(
        existing.employee_id, existing.date, existing.brand_id,
        existing.process_id, existing.workload_units,
    )
    replacement = SchedulingAssignment(
        second.id, existing.date, brand.id, process.id, 4
    )
    changed = accept_manual_change(
        db_session,
        version.roster_id,
        version.id,
        ManualChange("replace", replacement, previous),
        "test.operator",
    )

    assert changed.source_version_id == version.id
    assert changed.version_number == version.version_number + 1
    assert changed.changes[0].changed_by == "test.operator"
    assert changed.changes[0].change_type == "replace"
    assert any(row.employee_id == second.id for row in changed.assignments)

    added = apply_manual_change(
        (replacement,),
        ManualChange("add", SchedulingAssignment(
            employee.id, existing.date, brand.id, process.id, 4
        )),
    )
    assert len(added) == 2
    removed = apply_manual_change(
        added,
        ManualChange("remove", previous_assignment=replacement),
    )
    assert len(removed) == 1


def test_manual_accept_rejects_stale_version(db_session):
    version, _, second, brand, process = _persist_two_employee_roster(db_session)
    existing = version.assignments[0]
    change = ManualChange("replace", SchedulingAssignment(
        second.id, existing.date, brand.id, process.id, 4
    ), SchedulingAssignment(
        existing.employee_id, existing.date, existing.brand_id,
        existing.process_id, existing.workload_units,
    ))
    accept_manual_change(
        db_session, version.roster_id, version.id, change, "test.operator"
    )
    with pytest.raises(RosterConcurrencyError):
        accept_manual_change(
            db_session, version.roster_id, version.id, change, "test.operator"
        )
