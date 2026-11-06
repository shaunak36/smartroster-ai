from dataclasses import replace
from datetime import date, timedelta

from app.models import AvailabilityStatus
from app.services.configuration import (
    AssignmentEligibility,
    ResolvedAvailability,
    ResolvedOperatingRule,
)
from app.services.scheduling import SchedulingAssignment
from app.services.validation import (
    RosterAssignmentInput,
    ValidationSeverity,
    validate_roster,
)
from tests.test_scheduling import make_snapshot


def assignment(target=date(2026, 1, 5), **values):
    return SchedulingAssignment(
        values.get("employee_id", 1),
        target,
        values.get("brand_id", 10),
        values.get("process_id", 20),
        values.get("workload_units", 4),
    )


def test_valid_roster_is_valid():
    result = validate_roster(make_snapshot(), [assignment()])

    assert result.is_valid
    assert result.error_count == 0
    assert result.warning_count == 0


def test_invalid_employee_date_and_position_are_reported():
    snapshot = make_snapshot()
    rows = [
        assignment(employee_id=99),
        assignment(target=date(2026, 2, 1)),
        assignment(brand_id=99),
    ]

    result = validate_roster(snapshot, rows)

    codes = {item.code for item in result.diagnostics}
    assert {"unknown_employee", "invalid_assignment_date",
            "ineligible_assignment", "invalid_assignment_context"} <= codes


def test_unavailable_employee_and_duplicate_assignment_are_reported():
    target = date(2026, 1, 5)
    snapshot = replace(
        make_snapshot(),
        availabilities=(ResolvedAvailability(
            1, target, False, AvailabilityStatus.UNAVAILABLE, "leave", 1,
        ),),
    )

    result = validate_roster(snapshot, [assignment(), assignment()])

    codes = {item.code for item in result.diagnostics}
    assert "employee_unavailable" in codes
    assert "duplicate_assignment" in codes


def test_non_operating_day_and_insufficient_staffing_are_reported():
    target = date(2026, 1, 5)
    snapshot = replace(
        make_snapshot(),
        operating_rules=(ResolvedOperatingRule(
            10, 20, target, False, True, 1, 1, False,
        ),),
    )

    result = validate_roster(snapshot, [])

    codes = {item.code for item in result.diagnostics}
    assert "non_operating_day" not in codes
    assert "insufficient_staffing" not in codes

    operating_snapshot = replace(
        snapshot,
        operating_rules=(ResolvedOperatingRule(
            10, 20, target, True, True, 1, 1, False,
        ),),
    )
    result = validate_roster(operating_snapshot, [])
    assert any(item.code == "insufficient_staffing" for item in result.diagnostics)


def test_capacity_violations_include_daily_weekly_and_monthly():
    first = date(2026, 1, 5)
    second = first + timedelta(days=1)
    snapshot = make_snapshot(
        dates=(first, second),
        daily_capacity=3,
        weekly_capacity=4,
        monthly_capacity=4,
    )
    result = validate_roster(snapshot, [assignment(first), assignment(second)])

    codes = {item.code for item in result.diagnostics}
    assert {"daily_capacity_exceeded", "weekly_capacity_exceeded",
            "monthly_capacity_exceeded"} <= codes


def test_assignment_count_limit_is_validated():
    snapshot = make_snapshot(max_assignments=1)
    rows = [assignment(), assignment(brand_id=11, process_id=21)]

    result = validate_roster(snapshot, rows)

    assert any(
        item.code == "daily_assignment_limit_exceeded"
        for item in result.diagnostics
    )


def test_malformed_input_is_safe_and_warnings_are_separate():
    snapshot = make_snapshot(
        dates=(date(2026, 1, 4), date(2026, 1, 5)),
    )
    result = validate_roster(snapshot, [object()])

    assert not result.is_valid
    assert result.error_count >= 1
    assert any(item.code == "malformed_roster_assignment"
               for item in result.diagnostics)
    assert result.warning_count == 0

    warning_snapshot = replace(
        snapshot,
        requested_start=date(2026, 1, 5),
        requested_end=date(2026, 1, 5),
        requested_dates=(date(2026, 1, 5),),
        supporting_dates=(date(2026, 1, 4),),
        operating_rules=(snapshot.operating_rules[0],),
        process_workloads=(snapshot.process_workloads[0],),
    )
    warning_result = validate_roster(
        warning_snapshot, [assignment(date(2026, 1, 4))]
    )
    assert warning_result.is_valid
    assert warning_result.warning_count == 1
    assert warning_result.diagnostics[0].severity == ValidationSeverity.WARNING


def test_workload_mismatch_and_missing_context_are_reported():
    snapshot = make_snapshot()
    mismatch = validate_roster(
        snapshot,
        [RosterAssignmentInput(1, date(2026, 1, 5), 10, 20, 99)],
    )
    assert any(item.code == "workload_mismatch" for item in mismatch.diagnostics)

    incomplete = replace(
        snapshot,
        assignment_eligibility=(
            AssignmentEligibility(1, 10, 20, date(2026, 1, 5), 1, True),
        ),
        process_workloads=(),
    )
    result = validate_roster(incomplete, [assignment()])
    assert any(item.code == "missing_workload" for item in result.diagnostics)
