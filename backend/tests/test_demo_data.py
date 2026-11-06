from datetime import date

from app.models import (
    Brand,
    Employee,
    EmployeeAvailabilityOverride,
    EmployeeAssignment,
    LeaveRequest,
    Process,
    Roster,
    RosterAssignment,
    RosterStatus,
    AvailabilityStatus,
    ApprovalStatus,
    LeaveStatus,
)
from app.services.configuration import ConfigurationResolver
from app.services.demo_data import seed_demo_data
from app.services.roster import (
    ManualChange,
    apply_manual_change,
    run_roster_pipeline,
)
from app.services.scheduling import SchedulingStatus, SchedulingAssignment
from app.services.validation import validate_roster


def test_demo_seed_is_reproducible_and_has_required_shape(db_session):
    first = seed_demo_data(db_session)
    second = seed_demo_data(db_session)

    assert first.employees == 30
    assert first.brands == 8
    assert first.processes == 4
    assert first.pods == 4
    assert second == type(first)(0, 0, 0, 0, 0, 0, 0, 0, 0)
    assert db_session.query(Employee).count() == 30
    assert db_session.query(Brand).count() == 8
    assert db_session.query(Process).count() == 4
    assert db_session.query(EmployeeAssignment).count() == 48


def test_demo_roster_generation_and_coverage(db_session):
    seed_demo_data(db_session)
    pipeline = run_roster_pipeline(db_session, 2026, 2)

    assert pipeline.solver_result.status in (
        SchedulingStatus.OPTIMAL,
        SchedulingStatus.FEASIBLE,
    )
    assert pipeline.validation_result.is_valid
    assert len(pipeline.assignments) > 0


def test_demo_unavailability_creates_validation_failure(db_session):
    seed_demo_data(db_session)
    pipeline = run_roster_pipeline(db_session, 2026, 2)
    assert pipeline.validation_result.is_valid
    target = pipeline.assignments[0]
    db_session.add(EmployeeAvailabilityOverride(
        employee_id=target.employee_id,
        date=target.target_date,
        status=AvailabilityStatus.UNAVAILABLE,
        reason="Demo unavailability scenario",
        approval_status=ApprovalStatus.APPROVED,
    ))
    db_session.commit()
    snapshot = ConfigurationResolver(db_session).resolve_month(2026, 2)
    result = validate_roster(snapshot, pipeline.assignments)
    assert not result.is_valid
    assert any(item.code == "employee_unavailable" for item in result.diagnostics)


def test_demo_manual_change_and_insufficient_coverage(db_session):
    seed_demo_data(db_session)
    pipeline = run_roster_pipeline(db_session, 2026, 2)
    assert pipeline.validation_result.is_valid
    original = pipeline.assignments[0]
    replacement = SchedulingAssignment(
        original.employee_id + 100000,
        original.target_date,
        original.brand_id,
        original.process_id,
        original.workload_units,
    )
    proposed = apply_manual_change(
        pipeline.assignments,
        ManualChange("replace", replacement, original),
    )
    snapshot = ConfigurationResolver(db_session).resolve_month(2026, 2)
    invalid_manual = validate_roster(snapshot, proposed)
    assert not invalid_manual.is_valid
    assert any(
        item.code in {"unknown_employee", "ineligible_assignment"}
        for item in invalid_manual.diagnostics
    )

    dedicated = db_session.scalar(
        __import__("sqlalchemy").select(Employee).where(Employee.employee_code == "DEMO-E01")
    )
    db_session.add(LeaveRequest(
        employee_id=dedicated.id,
        start_date=date(2026, 2, 1),
        end_date=date(2026, 2, 28),
        leave_type="planned",
        status=LeaveStatus.APPROVED,
        reason="Demo coverage gap",
    ))
    db_session.commit()
    failed = run_roster_pipeline(db_session, 2026, 2)
    assert failed.solver_result.status == SchedulingStatus.INFEASIBLE
