from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import (
    AssignmentSource,
    Brand,
    Employee,
    EmployeeAssignment,
    EmployeeWeeklyOffException,
    EmployeeWeeklyOffPattern,
    ExceptionType,
    Pod,
    Process,
    Roster,
    RosterAssignment,
    RosterChangeHistory,
    RosterVersion,
    ValidationStatus,
)
from app.services.effective_dates import (
    EffectivePeriodOverlapError,
    ensure_no_effective_period_overlap,
)


def create_core_entities(db_session):
    employee = Employee(
        employee_code="EMP-001",
        name="Asha Rao",
        email="asha@example.com",
        daily_capacity_units=8,
        weekly_capacity_units=40,
        monthly_capacity_units=160,
        max_assignments_per_day=3,
    )
    brand_a = Brand(code="BR-A", name="Brand A")
    brand_b = Brand(code="BR-B", name="Brand B")
    process_cs = Process(code="CS", name="Customer Support")
    process_acc = Process(code="ACC", name="Abandoned Cart Conversions")
    db_session.add_all([employee, brand_a, brand_b, process_cs, process_acc])
    db_session.flush()
    return employee, brand_a, brand_b, process_cs, process_acc


def test_employee_supports_multiple_brands_and_processes(db_session) -> None:
    employee, brand_a, brand_b, process_cs, process_acc = create_core_entities(
        db_session
    )
    db_session.add_all(
        [
            EmployeeAssignment(
                employee=employee,
                brand=brand_a,
                process=process_cs,
                effective_start_date=date(2026, 1, 1),
            ),
            EmployeeAssignment(
                employee=employee,
                brand=brand_b,
                process=process_acc,
                effective_start_date=date(2026, 1, 1),
            ),
        ]
    )
    db_session.commit()

    assert len(employee.assignments) == 2
    assert employee.max_assignments_per_day == 3
    assert employee.weekly_capacity_units == 40


def test_pod_lead_and_employee_relationships(db_session) -> None:
    lead = Employee(employee_code="EMP-LEAD", name="Pod Lead", email="lead@example.com")
    member = Employee(employee_code="EMP-MEMBER", name="Member", email="member@example.com")
    pod = Pod(code="POD-1", name="Operations Pod", lead=lead, employees=[member])
    db_session.add(pod)
    db_session.commit()

    assert pod.lead is lead
    assert member.pod is pod
    assert lead.led_pods == [pod]


def test_weekly_off_pattern_and_exception_are_separate(db_session) -> None:
    employee = Employee(employee_code="EMP-002", name="Meera Shah", email="meera@example.com")
    db_session.add(employee)
    db_session.flush()
    pattern = EmployeeWeeklyOffPattern(
        employee=employee,
        recurrence_rule="FREQ=WEEKLY;BYDAY=SU",
        effective_start_date=date(2026, 1, 1),
    )
    exception = EmployeeWeeklyOffException(
        employee=employee,
        date=date(2026, 2, 1),
        exception_type=ExceptionType.WORKING_DAY,
        reason="Approved peak-season coverage",
        approval_status="approved",
    )
    db_session.add_all([pattern, exception])
    db_session.commit()

    assert employee.weekly_off_patterns[0].recurrence_rule.endswith("SU")
    assert employee.weekly_off_exceptions[0].reason


def test_effective_period_overlap_is_rejected(db_session) -> None:
    employee, brand_a, _, process_cs, _ = create_core_entities(db_session)
    first = EmployeeAssignment(
        employee=employee,
        brand=brand_a,
        process=process_cs,
        effective_start_date=date(2026, 1, 1),
        effective_end_date=date(2026, 3, 31),
    )
    db_session.add(first)
    db_session.flush()

    with pytest.raises(EffectivePeriodOverlapError):
        ensure_no_effective_period_overlap(
            db_session,
            EmployeeAssignment,
            {
                "employee_id": employee.id,
                "brand_id": brand_a.id,
                "process_id": process_cs.id,
            },
            date(2026, 3, 1),
            date(2026, 4, 30),
        )


def test_roster_versions_preserve_source_and_audit_history(db_session) -> None:
    employee, brand_a, _, process_cs, _ = create_core_entities(db_session)
    roster = Roster(year=2026, month=2)
    first = RosterVersion(
        roster=roster,
        version_number=1,
        solver_status="feasible",
        validation_status="valid",
    )
    second = RosterVersion(
        roster=roster,
        version_number=2,
        source_version=first,
        solver_status="feasible",
        validation_status="pending",
    )
    db_session.flush()
    assignment = RosterAssignment(
        roster_version=second,
        date=date(2026, 2, 2),
        employee=employee,
        brand=brand_a,
        process=process_cs,
        workload_units=4,
        source=AssignmentSource.REPLACEMENT,
    )
    history = RosterChangeHistory(
        roster_version=second,
        previous_version=first,
        change_type="replacement_preview_accepted",
        changed_date=date(2026, 2, 2),
        employee=employee,
        brand=brand_a,
        process=process_cs,
        validation_status=ValidationStatus.VALID,
        reason="Original employee became unavailable",
        changed_by="operations.manager",
    )
    db_session.add_all([assignment, history])
    db_session.commit()

    assert second.source_version is first
    assert second.assignments[0].source == AssignmentSource.REPLACEMENT.value
    assert second.changes[0].previous_version is first


def test_duplicate_roster_assignment_is_rejected(db_session) -> None:
    employee, brand_a, _, process_cs, _ = create_core_entities(db_session)
    roster = Roster(year=2026, month=3)
    version = RosterVersion(roster=roster, version_number=1)
    assignment_values = {
        "roster_version": version,
        "date": date(2026, 3, 2),
        "employee": employee,
        "brand": brand_a,
        "process": process_cs,
        "workload_units": 4,
    }
    db_session.add(RosterAssignment(**assignment_values))
    db_session.commit()
    db_session.add(RosterAssignment(**assignment_values))

    with pytest.raises(IntegrityError):
        db_session.commit()
