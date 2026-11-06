from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Dict, Iterable, Mapping, Tuple

from ortools.sat.python import cp_model

from app.services.configuration import ConfigurationSnapshot, DiagnosticSeverity


class SchedulingStatus(str, Enum):
    OPTIMAL = "optimal"
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"
    UNKNOWN = "unknown"
    MODEL_INVALID = "model_invalid"


@dataclass(frozen=True)
class SchedulingOptions:
    time_limit_seconds: float = 30.0
    num_workers: int = 1
    random_seed: int = 0


@dataclass(frozen=True)
class SchedulingDiagnostic:
    code: str
    message: str
    target_date: date | None = None
    employee_id: int | None = None
    brand_id: int | None = None
    process_id: int | None = None
    required_staffing: int | None = None
    candidate_employee_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class SchedulingAssignment:
    employee_id: int
    target_date: date
    brand_id: int
    process_id: int
    workload_units: int


@dataclass(frozen=True)
class SchedulingResult:
    status: SchedulingStatus
    assignments: tuple[SchedulingAssignment, ...]
    diagnostics: tuple[SchedulingDiagnostic, ...]
    objective_value: int | None = None
    wall_time_seconds: float | None = None


@dataclass(frozen=True)
class SchedulingVariableKey:
    employee_id: int
    target_date: date
    brand_id: int
    process_id: int


@dataclass
class SchedulingModel:
    model: cp_model.CpModel
    variables: Mapping[SchedulingVariableKey, cp_model.IntVar]
    workload_by_context: Mapping[Tuple[int, int, date], int]


def _capacity_index(snapshot: ConfigurationSnapshot):
    return {
        (item.employee_id, item.target_date): item
        for item in snapshot.employee_capacities
    }


def _availability_index(snapshot: ConfigurationSnapshot):
    return {
        (item.employee_id, item.target_date): item
        for item in snapshot.availabilities
    }


def _compatibility_index(snapshot: ConfigurationSnapshot):
    return {
        (item.employee_id, item.brand_id, item.process_id): item
        for item in snapshot.compatibilities
    }


def _workload_index(snapshot: ConfigurationSnapshot):
    return {
        (item.brand_id, item.process_id, item.target_date): item.workload_units
        for item in snapshot.process_workloads
    }


def _candidate_keys(snapshot: ConfigurationSnapshot) -> tuple[SchedulingVariableKey, ...]:
    availability = _availability_index(snapshot)
    compatibility = _compatibility_index(snapshot)
    keys = []
    for item in snapshot.assignment_eligibility:
        available = availability.get((item.employee_id, item.target_date))
        compatible = compatibility.get(
            (item.employee_id, item.brand_id, item.process_id)
        )
        if available is not None and not available.available:
            continue
        if compatible is not None and not compatible.is_compatible:
            continue
        keys.append(SchedulingVariableKey(
            item.employee_id,
            item.target_date,
            item.brand_id,
            item.process_id,
        ))
    return tuple(sorted(set(keys), key=lambda item: (
        item.target_date, item.brand_id, item.process_id, item.employee_id,
    )))


def _required_contexts(snapshot: ConfigurationSnapshot):
    return (
        item for item in snapshot.operating_rules
        if item.target_date in snapshot.horizon_dates
        and item.operating
        and item.required_coverage
        and item.minimum_daily_staffing > 0
    )


def _diagnose_missing_candidates(
    snapshot: ConfigurationSnapshot,
    candidate_keys: Iterable[SchedulingVariableKey],
) -> tuple[SchedulingDiagnostic, ...]:
    candidates_by_context: Dict[Tuple[int, int, date], set[int]] = {}
    for key in candidate_keys:
        candidates_by_context.setdefault(
            (key.brand_id, key.process_id, key.target_date), set()
        ).add(key.employee_id)

    diagnostics = []
    for rule in _required_contexts(snapshot):
        candidate_ids = tuple(sorted(candidates_by_context.get(
            (rule.brand_id, rule.process_id, rule.target_date), set()
        )))
        if len(candidate_ids) < rule.minimum_daily_staffing:
            diagnostics.append(SchedulingDiagnostic(
                code="insufficient_eligible_staff",
                message=(
                    "Required staffing exceeds eligible available employees"
                ),
                target_date=rule.target_date,
                brand_id=rule.brand_id,
                process_id=rule.process_id,
                required_staffing=rule.minimum_daily_staffing,
                candidate_employee_ids=candidate_ids,
            ))
    return tuple(diagnostics)


def _diagnose_snapshot(snapshot: ConfigurationSnapshot) -> tuple[SchedulingDiagnostic, ...]:
    return tuple(
        SchedulingDiagnostic(
            code=diagnostic.code,
            message=diagnostic.message,
            target_date=diagnostic.target_date,
            employee_id=diagnostic.employee_id,
            brand_id=diagnostic.brand_id,
            process_id=diagnostic.process_id,
        )
        for diagnostic in snapshot.diagnostics
    )


def build_scheduling_model(
    snapshot: ConfigurationSnapshot,
    options: SchedulingOptions | None = None,
) -> SchedulingModel:
    del options
    model = cp_model.CpModel()
    workload_by_context = _workload_index(snapshot)
    variables: Dict[SchedulingVariableKey, cp_model.IntVar] = {}
    for key in _candidate_keys(snapshot):
        variables[key] = model.NewBoolVar(
            f"assign_e{key.employee_id}_d{key.target_date.isoformat()}"
            f"_b{key.brand_id}_p{key.process_id}"
        )

    by_context: Dict[Tuple[int, int, date], list[cp_model.IntVar]] = {}
    by_employee_date: Dict[Tuple[int, date], list[cp_model.IntVar]] = {}
    by_employee_week: Dict[Tuple[int, tuple[int, int]], list[cp_model.IntVar]] = {}
    by_employee_month: Dict[Tuple[int, int, int], list[cp_model.IntVar]] = {}
    for key, variable in variables.items():
        by_context.setdefault(
            (key.brand_id, key.process_id, key.target_date), []
        ).append(variable)
        by_employee_date.setdefault((key.employee_id, key.target_date), []).append(
            variable
        )
        iso = key.target_date.isocalendar()
        by_employee_week.setdefault(
            (key.employee_id, (iso.year, iso.week)), []
        ).append(variable)
        by_employee_month.setdefault(
            (key.employee_id, key.target_date.year, key.target_date.month), []
        ).append(variable)

    for rule in _required_contexts(snapshot):
        model.Add(
            sum(by_context.get(
                (rule.brand_id, rule.process_id, rule.target_date), []
            )) >= rule.minimum_daily_staffing
        )

    operating_contexts = {
        (item.brand_id, item.process_id, item.target_date): item
        for item in snapshot.operating_rules
    }
    for context, context_variables in by_context.items():
        rule = operating_contexts.get(context)
        if rule is not None and not rule.operating:
            model.Add(sum(context_variables) == 0)

    capacity_by_employee_date = _capacity_index(snapshot)
    for key, variables_for_day in by_employee_date.items():
        capacity = capacity_by_employee_date.get(key)
        if capacity is None:
            continue
        if capacity.max_assignments_per_day is not None:
            model.Add(sum(variables_for_day) <= capacity.max_assignments_per_day)
        if capacity.daily_capacity_units is not None:
            terms = [
                variable * workload_by_context.get(
                    (candidate.brand_id, candidate.process_id, candidate.target_date),
                    0,
                )
                for candidate, variable in variables.items()
                if candidate.employee_id == key[0]
                and candidate.target_date == key[1]
            ]
            model.Add(sum(terms) <= capacity.daily_capacity_units)

    for (employee_id, iso_week), variables_for_week in by_employee_week.items():
        capacities = [
            item.weekly_capacity_units
            for item in snapshot.employee_capacities
            if item.employee_id == employee_id
            and (item.target_date.isocalendar().year,
                 item.target_date.isocalendar().week) == iso_week
            and item.weekly_capacity_units is not None
        ]
        if capacities:
            model.Add(
                sum(
                    variable * workload_by_context.get(
                        (key.brand_id, key.process_id, key.target_date), 0
                    )
                    for key, variable in variables.items()
                    if key.employee_id == employee_id
                    and (key.target_date.isocalendar().year,
                         key.target_date.isocalendar().week) == iso_week
                ) <= min(capacities)
            )

    for (employee_id, year, month), _ in by_employee_month.items():
        capacities = [
            item.monthly_capacity_units
            for item in snapshot.employee_capacities
            if item.employee_id == employee_id
            and item.target_date.year == year
            and item.target_date.month == month
            and item.monthly_capacity_units is not None
        ]
        if capacities:
            model.Add(
                sum(
                    variable * workload_by_context.get(
                        (key.brand_id, key.process_id, key.target_date), 0
                    )
                    for key, variable in variables.items()
                    if key.employee_id == employee_id
                    and key.target_date.year == year
                    and key.target_date.month == month
                ) <= min(capacities)
            )

    workload_totals = []
    for employee_id in snapshot.employees:
        total = model.NewIntVar(0, sum(workload_by_context.values()), f"load_{employee_id}")
        model.Add(
            total == sum(
                variable * workload_by_context.get(
                    (key.brand_id, key.process_id, key.target_date), 0
                )
                for key, variable in variables.items()
                if key.employee_id == employee_id
            )
        )
        workload_totals.append(total)
    if workload_totals:
        maximum = model.NewIntVar(0, sum(workload_by_context.values()), "max_load")
        minimum = model.NewIntVar(0, sum(workload_by_context.values()), "min_load")
        model.AddMaxEquality(maximum, workload_totals)
        model.AddMinEquality(minimum, workload_totals)
        primary_variables = [
            variable for key, variable in variables.items()
            if any(
                assignment.employee_id == key.employee_id
                and assignment.target_date == key.target_date
                and assignment.brand_id == key.brand_id
                and assignment.process_id == key.process_id
                and assignment.is_primary
                for assignment in snapshot.assignment_eligibility
            )
        ]
        model.Minimize(
            (maximum - minimum) * 1000
            + sum(variables.values()) * 10
            - sum(primary_variables)
        )

    return SchedulingModel(model, variables, workload_by_context)


def solve_schedule(
    snapshot: ConfigurationSnapshot,
    options: SchedulingOptions | None = None,
) -> SchedulingResult:
    options = options or SchedulingOptions()
    if options.time_limit_seconds <= 0 or options.num_workers <= 0:
        return SchedulingResult(
            SchedulingStatus.MODEL_INVALID,
            (),
            (SchedulingDiagnostic(
                "invalid_solver_options",
                "Solver time limit and worker count must be positive",
            ),),
        )
    snapshot_diagnostics = _diagnose_snapshot(snapshot)
    error_diagnostics = tuple(
        diagnostic for diagnostic, source in zip(
            snapshot_diagnostics, snapshot.diagnostics
        )
        if source.severity == DiagnosticSeverity.ERROR
    )
    if error_diagnostics:
        return SchedulingResult(
            SchedulingStatus.MODEL_INVALID,
            (),
            error_diagnostics,
        )
    candidate_keys = _candidate_keys(snapshot)
    diagnostics = _diagnose_missing_candidates(snapshot, candidate_keys)
    model = build_scheduling_model(snapshot, options)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = options.time_limit_seconds
    solver.parameters.num_search_workers = options.num_workers
    solver.parameters.random_seed = options.random_seed
    status = solver.Solve(model.model)
    status_map = {
        cp_model.OPTIMAL: SchedulingStatus.OPTIMAL,
        cp_model.FEASIBLE: SchedulingStatus.FEASIBLE,
        cp_model.INFEASIBLE: SchedulingStatus.INFEASIBLE,
        cp_model.UNKNOWN: SchedulingStatus.UNKNOWN,
        cp_model.MODEL_INVALID: SchedulingStatus.MODEL_INVALID,
    }
    result_status = status_map.get(status, SchedulingStatus.UNKNOWN)
    if result_status in (
        SchedulingStatus.INFEASIBLE,
        SchedulingStatus.UNKNOWN,
        SchedulingStatus.MODEL_INVALID,
    ):
        if not diagnostics:
            diagnostics = (
                SchedulingDiagnostic(
                    code="solver_no_solution",
                    message=f"CP-SAT returned {result_status.value}",
                ),
            )
        return SchedulingResult(
            result_status,
            (),
            snapshot_diagnostics + diagnostics,
            wall_time_seconds=solver.WallTime(),
        )
    assignments = tuple(
        SchedulingAssignment(
            key.employee_id,
            key.target_date,
            key.brand_id,
            key.process_id,
            model.workload_by_context.get(
                (key.brand_id, key.process_id, key.target_date), 0
            ),
        )
        for key, variable in model.variables.items()
        if solver.Value(variable)
    )
    return SchedulingResult(
        result_status,
        tuple(sorted(assignments, key=lambda item: (
            item.target_date, item.brand_id, item.process_id, item.employee_id,
        ))),
        snapshot_diagnostics + diagnostics,
        objective_value=int(solver.ObjectiveValue()),
        wall_time_seconds=solver.WallTime(),
    )
