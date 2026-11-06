from datetime import date

import pytest

from app.models import (
    ApprovalStatus,
    AssignmentCompatibilityRule,
    Brand,
    BrandProcessDateOverride,
    BrandProcessOperatingRule,
    BrandProcessWorkloadRule,
    Employee,
    EmployeeAssignment,
    EmployeeAvailabilityOverride,
    EmployeeWeeklyOffException,
    EmployeeWeeklyOffPattern,
    EmployeeWorkloadRule,
    ExceptionType,
    LeaveRequest,
    LeaveStatus,
    OperatingStatus,
    Process,
    PublicHoliday,
)
from app.services.configuration import (
    ConfigurationResolutionError,
    ConfigurationResolver,
    DiagnosticSeverity,
    expanded_iso_week_horizon,
)


def configured_employee(db_session):
    employee = Employee(
        employee_code="EMP-CONFIG",
        name="Config Employee",
        email="config@example.com",
        daily_capacity_units=8,
        weekly_capacity_units=40,
        monthly_capacity_units=160,
        max_assignments_per_day=2,
    )
    brand = Brand(code="BR-CONFIG", name="Config Brand")
    process = Process(code="CS-CONFIG", name="Customer Support")
    db_session.add_all([employee, brand, process])
    db_session.flush()
    db_session.add_all([
        EmployeeAssignment(
            employee_id=employee.id, brand_id=brand.id, process_id=process.id,
            effective_start_date=date(2026, 1, 1),
        ),
        BrandProcessOperatingRule(
            brand_id=brand.id, process_id=process.id,
            effective_start_date=date(2026, 1, 1),
            operating_weekdays="MO,TU,WE,TH,FR,SA",
            sunday_working=False, public_holiday_working=False,
            required_coverage=True, minimum_daily_staffing=1,
        ),
        BrandProcessWorkloadRule(
            brand_id=brand.id, process_id=process.id,
            effective_start_date=date(2026, 1, 1), workload_units=4,
        ),
    ])
    db_session.commit()
    return employee, brand, process


def test_availability_precedence_and_approved_override(db_session):
    employee, _, _ = configured_employee(db_session)
    target = date(2026, 1, 4)
    db_session.add(EmployeeWeeklyOffPattern(
        employee_id=employee.id, recurrence_rule="FREQ=WEEKLY;BYDAY=SU",
        effective_start_date=date(2026, 1, 1),
    ))
    db_session.commit()

    snapshot = ConfigurationResolver(db_session).resolve(target, target)
    availability = next(
        item for item in snapshot.availabilities if item.target_date == target
    )
    assert not availability.available
    assert "Recurring weekly off" in availability.reason

    db_session.add(EmployeeWeeklyOffException(
        employee_id=employee.id, date=target, exception_type=ExceptionType.WORKING_DAY,
        reason="Peak coverage", approval_status=ApprovalStatus.APPROVED,
    ))
    db_session.commit()
    snapshot = ConfigurationResolver(db_session).resolve(target, target)
    availability = next(
        item for item in snapshot.availabilities if item.target_date == target
    )
    assert availability.available
    assert "exception" in availability.reason

    db_session.add(EmployeeAvailabilityOverride(
        employee_id=employee.id, date=target, status="unavailable",
        reason="Approved personal unavailability",
        approval_status=ApprovalStatus.APPROVED,
    ))
    db_session.commit()
    snapshot = ConfigurationResolver(db_session).resolve(target, target)
    availability = next(
        item for item in snapshot.availabilities if item.target_date == target
    )
    assert not availability.available
    assert "availability override" in availability.reason

    db_session.add(LeaveRequest(
        employee_id=employee.id, start_date=target, end_date=target,
        leave_type="annual", status=LeaveStatus.APPROVED,
    ))
    db_session.commit()
    snapshot = ConfigurationResolver(db_session).resolve(target, target)
    availability = next(
        item for item in snapshot.availabilities if item.target_date == target
    )
    assert "Approved leave" in availability.reason


def test_pending_and_rejected_exceptions_do_not_override_weekly_off(db_session):
    employee, _, _ = configured_employee(db_session)
    target = date(2026, 1, 4)
    db_session.add(EmployeeWeeklyOffPattern(
        employee_id=employee.id, recurrence_rule="FREQ=WEEKLY;BYDAY=SU",
        effective_start_date=date(2026, 1, 1),
    ))
    db_session.add_all([
        EmployeeWeeklyOffException(
            employee_id=employee.id, date=target, exception_type=ExceptionType.WORKING_DAY,
            reason="Pending", approval_status=ApprovalStatus.PENDING,
        ),
        EmployeeAvailabilityOverride(
            employee_id=employee.id, date=target, status="available",
            reason="Rejected override", approval_status=ApprovalStatus.REJECTED,
        ),
    ])
    db_session.commit()
    snapshot = ConfigurationResolver(db_session).resolve(target, target)
    availability = next(
        item for item in snapshot.availabilities if item.target_date == target
    )
    assert not availability.available
    assert "Recurring weekly off" in availability.reason


def test_effective_boundaries_operating_override_and_public_holiday(db_session):
    _, brand, process = configured_employee(db_session)
    target = date(2026, 1, 11)
    db_session.add(PublicHoliday(
        date=target, name="Holiday", scope="global", is_active=True,
    ))
    db_session.add(BrandProcessDateOverride(
        brand_id=brand.id, process_id=process.id, date=target,
        operating_status=OperatingStatus.OPEN, required_coverage=True,
        minimum_daily_staffing=2, reason="Special opening",
    ))
    db_session.commit()
    snapshot = ConfigurationResolver(db_session).resolve(target, target)
    rule = next(
        item for item in snapshot.operating_rules if item.target_date == target
    )
    assert rule.operating
    assert rule.minimum_daily_staffing == 2
    assert rule.is_public_holiday


def test_resolves_capacity_compatibility_workload_and_iso_boundary(db_session):
    employee, brand, process = configured_employee(db_session)
    start, end = date(2026, 1, 31), date(2026, 2, 1)
    snapshot = ConfigurationResolver(db_session).resolve(start, end)
    assert snapshot.horizon_start == date(2026, 1, 26)
    assert snapshot.horizon_end == date(2026, 2, 1)
    capacity = next(item[-1] for item in snapshot.capacities if item[3] == start)
    assert capacity.weekly_capacity_units == 40
    assert snapshot.process_workloads[0].workload_units == 4
    assert next(
        item for item in snapshot.process_workloads if item.target_date == start
    ).workload_units == 4
    assert any(item.target_date == date(2026, 1, 26) for item in snapshot.process_workloads)
    assert snapshot.compatibilities[0].is_compatible
    assert employee.id in snapshot.employees
    assert expanded_iso_week_horizon(start, end) == (
        date(2026, 1, 26), date(2026, 2, 1)
    )


def test_snapshot_exposes_date_groups_and_exact_assignment_eligibility(db_session):
    employee, brand, process = configured_employee(db_session)
    assignment = employee.assignments[0]
    assignment.effective_start_date = date(2026, 1, 30)
    assignment.effective_end_date = date(2026, 2, 1)
    db_session.commit()

    snapshot = ConfigurationResolver(db_session).resolve(
        date(2026, 1, 31), date(2026, 2, 1)
    )
    assert snapshot.requested_dates == (date(2026, 1, 31), date(2026, 2, 1))
    assert snapshot.supporting_dates == (
        date(2026, 1, 26),
        date(2026, 1, 27),
        date(2026, 1, 28),
        date(2026, 1, 29),
        date(2026, 1, 30),
    )
    assert snapshot.horizon_dates == snapshot.dates
    assert all(
        item.target_date >= date(2026, 1, 30)
        and item.target_date <= date(2026, 2, 1)
        for item in snapshot.assignment_eligibility
    )
    assert snapshot.assignments[0].effective_start_date == date(2026, 1, 30)
    assert snapshot.assignments[0].effective_end_date == date(2026, 2, 1)


def test_employee_capacity_inherits_defaults_and_detects_week_conflict(db_session):
    employee, _, _ = configured_employee(db_session)
    db_session.add_all([
        EmployeeWorkloadRule(
            employee_id=employee.id,
            effective_start_date=date(2026, 1, 26),
            effective_end_date=date(2026, 1, 28),
            weekly_capacity_units=40,
        ),
        EmployeeWorkloadRule(
            employee_id=employee.id,
            effective_start_date=date(2026, 1, 29),
            effective_end_date=date(2026, 2, 1),
            weekly_capacity_units=32,
        ),
    ])
    db_session.commit()

    with pytest.raises(ConfigurationResolutionError) as error:
        ConfigurationResolver(db_session).resolve(
            date(2026, 1, 31), date(2026, 2, 1)
        )
    assert any(
        item.code == "conflicting_weekly_capacity"
        and item.employee_id == employee.id
        for item in error.value.diagnostics
    )


def test_ambiguous_configuration_is_rejected(db_session):
    employee, brand, process = configured_employee(db_session)
    db_session.add(BrandProcessOperatingRule(
        brand_id=brand.id, process_id=process.id,
        effective_start_date=date(2026, 1, 1),
        operating_weekdays="MO,TU,WE,TH,FR,SA",
        sunday_working=False, public_holiday_working=False,
        required_coverage=True, minimum_daily_staffing=1,
    ))
    db_session.commit()
    with pytest.raises(ConfigurationResolutionError) as error:
        ConfigurationResolver(db_session).resolve(date(2026, 1, 2), date(2026, 1, 2))
    assert any(
        diagnostic.code == "ambiguous_effective_rule"
        and diagnostic.severity == DiagnosticSeverity.ERROR
        for diagnostic in error.value.diagnostics
    )


def test_invalid_period_is_rejected(db_session):
    with pytest.raises(ValueError, match="must not precede"):
        ConfigurationResolver(db_session).resolve(date(2026, 2, 1), date(2026, 1, 1))
    with pytest.raises(ValueError, match="between 1 and 12"):
        ConfigurationResolver(db_session).resolve_month(2026, 0)


def test_only_active_employees_with_effective_assignments_are_eligible(db_session):
    employee, brand, process = configured_employee(db_session)
    inactive = Employee(
        employee_code="EMP-INACTIVE",
        name="Inactive Employee",
        email="inactive@example.com",
        status="inactive",
    )
    db_session.add(inactive)
    db_session.flush()
    db_session.add(EmployeeAssignment(
        employee_id=inactive.id, brand_id=brand.id, process_id=process.id,
        effective_start_date=date(2026, 1, 1),
    ))
    db_session.commit()
    snapshot = ConfigurationResolver(db_session).resolve_month(2026, 1)
    assert snapshot.employees == (employee.id,)
    assert all(item.employee_id == employee.id for item in snapshot.assignments)


def test_employee_rules_are_isolated_by_employee_id(db_session):
    employee_a, brand, process = configured_employee(db_session)
    employee_b = Employee(
        employee_code="EMP-OTHER",
        name="Other Employee",
        email="other@example.com",
        daily_capacity_units=8,
    )
    db_session.add(employee_b)
    db_session.flush()
    db_session.add_all([
        EmployeeAssignment(
            employee_id=employee_b.id, brand_id=brand.id, process_id=process.id,
            effective_start_date=date(2026, 1, 1),
        ),
        EmployeeWorkloadRule(
            employee_id=employee_a.id,
            effective_start_date=date(2026, 1, 1),
            daily_capacity_units=2,
        ),
        EmployeeWorkloadRule(
            employee_id=employee_b.id,
            effective_start_date=date(2026, 1, 1),
            daily_capacity_units=7,
        ),
        AssignmentCompatibilityRule(
            employee_id=employee_a.id,
            brand_id=brand.id,
            process_id=process.id,
            effective_start_date=date(2026, 1, 1),
            is_compatible=False,
            reason="Employee A is unavailable for this combination",
        ),
    ])
    db_session.commit()

    snapshot = ConfigurationResolver(db_session).resolve(
        date(2026, 1, 5), date(2026, 1, 5)
    )
    capacities = {
        employee_id: capacity.daily_capacity_units
        for employee_id, _, _, target, capacity in snapshot.capacities
        if target == date(2026, 1, 5)
    }
    compatibility = {
        item.employee_id: item.is_compatible for item in snapshot.compatibilities
    }
    assert capacities[employee_a.id] == 2
    assert capacities[employee_b.id] == 7
    assert compatibility[employee_a.id] is False
    assert compatibility[employee_b.id] is True


def test_required_context_without_eligible_assignment_is_rejected(db_session):
    _, _, process = configured_employee(db_session)
    brand = Brand(code="BR-NO-ASSIGNMENT", name="Unassigned Brand")
    db_session.add(brand)
    db_session.flush()
    db_session.add_all([
        BrandProcessOperatingRule(
            brand_id=brand.id,
            process_id=process.id,
            effective_start_date=date(2026, 1, 1),
            operating_weekdays="MO,TU,WE,TH,FR,SA",
            sunday_working=False,
            public_holiday_working=False,
            required_coverage=True,
            minimum_daily_staffing=1,
        ),
        BrandProcessWorkloadRule(
            brand_id=brand.id,
            process_id=process.id,
            effective_start_date=date(2026, 1, 1),
            workload_units=4,
        ),
    ])
    db_session.commit()

    with pytest.raises(ConfigurationResolutionError) as error:
        ConfigurationResolver(db_session).resolve(
            date(2026, 1, 5), date(2026, 1, 5)
        )
    assert any(
        item.code == "missing_eligible_assignment"
        and item.brand_id == brand.id
        and item.process_id == process.id
        for item in error.value.diagnostics
    )


def test_inactive_weekly_off_pattern_does_not_block_availability(db_session):
    employee, _, _ = configured_employee(db_session)
    target = date(2026, 1, 4)
    db_session.add(EmployeeWeeklyOffPattern(
        employee_id=employee.id,
        recurrence_rule="FREQ=WEEKLY;BYDAY=SU",
        effective_start_date=date(2026, 1, 1),
        is_active=False,
    ))
    db_session.commit()

    snapshot = ConfigurationResolver(db_session).resolve(target, target)
    availability = next(
        item for item in snapshot.availabilities if item.target_date == target
    )
    assert availability.available
    assert availability.reason == "Normal availability applies"
