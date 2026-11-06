from datetime import date, timedelta

from app.services.configuration import (
    AssignmentEligibility,
    ConfigurationDiagnostic,
    ConfigurationSnapshot,
    DiagnosticSeverity,
    ResolvedAvailability,
    ResolvedCapacity,
    ResolvedCompatibility,
    ResolvedEmployeeCapacity,
    ResolvedOperatingRule,
    ResolvedWorkload,
)
from app.services.scheduling import (
    SchedulingOptions,
    SchedulingStatus,
    solve_schedule,
)
from app.models import AvailabilityStatus


def make_snapshot(
    *,
    employee_ids=(1,),
    dates=(date(2026, 1, 5),),
    eligibility=None,
    available=None,
    daily_capacity=8,
    weekly_capacity=100,
    monthly_capacity=100,
    max_assignments=10,
    minimum_staffing=1,
    diagnostics=(),
):
    eligibility = eligibility or tuple(
        AssignmentEligibility(employee_id, 10, 20, target, 1, True)
        for employee_id in employee_ids
        for target in dates
    )
    available = available or tuple(
        ResolvedAvailability(
            employee_id, target, True, AvailabilityStatus.AVAILABLE,
            "test", None,
        )
        for employee_id in employee_ids
        for target in dates
    )
    operating = tuple(
        ResolvedOperatingRule(
            10, 20, target, True, True, minimum_staffing, 1, False,
        )
        for target in dates
    )
    workloads = tuple(
        ResolvedWorkload(10, 20, target, 4, 1)
        for target in dates
    )
    capacities = tuple(
        ResolvedEmployeeCapacity(
            employee_id, target, daily_capacity, weekly_capacity,
            monthly_capacity, max_assignments, None,
        )
        for employee_id in employee_ids
        for target in dates
    )
    compatibilities = tuple(
        ResolvedCompatibility(employee_id, 10, 20, True, None)
        for employee_id in employee_ids
    )
    return ConfigurationSnapshot(
        requested_start=dates[0],
        requested_end=dates[-1],
        horizon_start=dates[0],
        horizon_end=dates[-1],
        requested_dates=dates,
        supporting_dates=(),
        horizon_dates=dates,
        dates=dates,
        employees=employee_ids,
        assignments=(),
        assignment_eligibility=eligibility,
        availabilities=available,
        capacities=tuple(
            (employee_id, 10, 20, target, ResolvedCapacity(
                daily_capacity, weekly_capacity, monthly_capacity,
                max_assignments, None,
            ))
            for employee_id in employee_ids
            for target in dates
        ),
        employee_capacities=capacities,
        compatibilities=compatibilities,
        process_workloads=workloads,
        operating_rules=operating,
        public_holidays=(),
        diagnostics=diagnostics,
    )


def test_generates_required_assignments():
    result = solve_schedule(make_snapshot())

    assert result.status == SchedulingStatus.OPTIMAL
    assert len(result.assignments) == 1
    assert result.assignments[0].employee_id == 1
    assert result.assignments[0].workload_units == 4


def test_assignment_eligibility_is_date_specific():
    first = date(2026, 1, 5)
    second = first + timedelta(days=1)
    snapshot = make_snapshot(
        dates=(first, second),
        eligibility=(AssignmentEligibility(1, 10, 20, first, 1, True),),
    )

    result = solve_schedule(snapshot)

    assert result.status == SchedulingStatus.INFEASIBLE
    assert any(
        diagnostic.code == "insufficient_eligible_staff"
        and diagnostic.target_date == second
        for diagnostic in result.diagnostics
    )


def test_unavailable_employee_is_not_a_candidate():
    target = date(2026, 1, 5)
    snapshot = make_snapshot(
        available=(ResolvedAvailability(
            1, target, False, AvailabilityStatus.UNAVAILABLE, "leave", 1,
        ),),
    )

    result = solve_schedule(snapshot)

    assert result.status == SchedulingStatus.INFEASIBLE
    assert result.diagnostics[0].code == "insufficient_eligible_staff"


def test_daily_capacity_limits_workload():
    snapshot = make_snapshot(daily_capacity=3)

    result = solve_schedule(snapshot)

    assert result.status == SchedulingStatus.INFEASIBLE
    assert any(
        diagnostic.code == "solver_no_solution"
        for diagnostic in result.diagnostics
    )


def test_insufficient_staffing_reports_required_context():
    snapshot = make_snapshot(employee_ids=(1,), minimum_staffing=2)

    result = solve_schedule(snapshot)

    assert result.status == SchedulingStatus.INFEASIBLE
    assert result.diagnostics[0].required_staffing == 2
    assert result.diagnostics[0].candidate_employee_ids == (1,)


def test_multiple_dates_and_employees_are_scheduled_deterministically():
    first = date(2026, 1, 5)
    snapshot = make_snapshot(
        employee_ids=(1, 2),
        dates=(first, first + timedelta(days=1)),
        daily_capacity=4,
        max_assignments=1,
    )

    first_result = solve_schedule(snapshot, SchedulingOptions(num_workers=1))
    second_result = solve_schedule(snapshot, SchedulingOptions(num_workers=1))

    assert first_result.status == SchedulingStatus.OPTIMAL
    assert first_result.assignments == second_result.assignments
    assert len(first_result.assignments) == 2


def test_snapshot_configuration_errors_are_not_silently_solved():
    snapshot = make_snapshot(diagnostics=(ConfigurationDiagnostic(
        "ambiguous_effective_rule",
        DiagnosticSeverity.ERROR,
        "ambiguous",
    ),))

    result = solve_schedule(snapshot)

    assert result.status == SchedulingStatus.MODEL_INVALID
    assert result.diagnostics[0].code == "ambiguous_effective_rule"
