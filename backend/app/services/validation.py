from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Iterable

from app.services.configuration import ConfigurationSnapshot


class ValidationSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class RosterAssignmentInput:
    employee_id: int
    target_date: date
    brand_id: int
    process_id: int
    workload_units: int | None = None


@dataclass(frozen=True)
class ValidationDiagnostic:
    code: str
    severity: ValidationSeverity
    message: str
    employee_id: int | None = None
    target_date: date | None = None
    brand_id: int | None = None
    process_id: int | None = None


@dataclass(frozen=True)
class RosterValidationResult:
    is_valid: bool
    error_count: int
    warning_count: int
    diagnostics: tuple[ValidationDiagnostic, ...]
    affected_employee_ids: tuple[int, ...]
    affected_dates: tuple[date, ...]


def _diagnostic(
    code: str,
    message: str,
    *,
    severity: ValidationSeverity = ValidationSeverity.ERROR,
    assignment: RosterAssignmentInput | None = None,
) -> ValidationDiagnostic:
    return ValidationDiagnostic(
        code,
        severity,
        message,
        assignment.employee_id if assignment else None,
        assignment.target_date if assignment else None,
        assignment.brand_id if assignment else None,
        assignment.process_id if assignment else None,
    )


def _coerce_assignment(
    value: object,
) -> tuple[RosterAssignmentInput | None, ValidationDiagnostic | None]:
    fields = ("employee_id", "target_date", "brand_id", "process_id")
    try:
        values = {field: getattr(value, field) for field in fields}
        workload_units = getattr(value, "workload_units", None)
    except (AttributeError, TypeError):
        return None, _diagnostic(
            "malformed_roster_assignment",
            "Roster assignment is missing required fields",
        )
    if (
        type(values["employee_id"]) is not int
        or type(values["brand_id"]) is not int
        or type(values["process_id"]) is not int
        or not isinstance(values["target_date"], date)
        or (
            workload_units is not None
            and type(workload_units) is not int
        )
    ):
        return None, _diagnostic(
            "malformed_roster_assignment",
            "Roster assignment contains invalid field types",
        )
    return RosterAssignmentInput(
        values["employee_id"],
        values["target_date"],
        values["brand_id"],
        values["process_id"],
        workload_units,
    ), None


class RosterValidator:
    """Validates roster rows independently from the CP-SAT model."""

    def validate(
        self,
        snapshot: ConfigurationSnapshot,
        assignments: Iterable[object] | None,
    ) -> RosterValidationResult:
        diagnostics: list[ValidationDiagnostic] = []
        rows: list[RosterAssignmentInput] = []
        if assignments is None:
            diagnostics.append(_diagnostic(
                "malformed_roster_input",
                "Roster assignments must be an iterable",
            ))
        else:
            try:
                iterator = iter(assignments)
            except TypeError:
                diagnostics.append(_diagnostic(
                    "malformed_roster_input",
                    "Roster assignments must be an iterable",
                ))
            else:
                for value in iterator:
                    row, diagnostic = _coerce_assignment(value)
                    if diagnostic is not None:
                        diagnostics.append(diagnostic)
                    elif row is not None:
                        rows.append(row)

        eligibility = {
            (item.employee_id, item.target_date, item.brand_id, item.process_id)
            for item in snapshot.assignment_eligibility
        }
        availability = {
            (item.employee_id, item.target_date): item
            for item in snapshot.availabilities
        }
        operating = {
            (item.brand_id, item.process_id, item.target_date): item
            for item in snapshot.operating_rules
        }
        workload = {
            (item.brand_id, item.process_id, item.target_date): item.workload_units
            for item in snapshot.process_workloads
        }
        capacities = {
            (item.employee_id, item.target_date): item
            for item in snapshot.employee_capacities
        }

        seen: set[tuple[int, date, int, int]] = set()
        daily: dict[tuple[int, date], int] = {}
        weekly: dict[tuple[int, int, int], int] = {}
        monthly: dict[tuple[int, int, int], int] = {}
        context_counts: dict[tuple[int, int, date], int] = {}

        for row in rows:
            key = (row.employee_id, row.target_date, row.brand_id, row.process_id)
            if key in seen:
                diagnostics.append(_diagnostic(
                    "duplicate_assignment",
                    "Roster contains a duplicate assignment",
                    assignment=row,
                ))
            seen.add(key)

            if row.employee_id not in snapshot.employees:
                diagnostics.append(_diagnostic(
                    "unknown_employee",
                    "Employee is not active in the configuration snapshot",
                    assignment=row,
                ))
            if row.target_date not in snapshot.horizon_dates:
                diagnostics.append(_diagnostic(
                    "invalid_assignment_date",
                    "Assignment date is outside the resolved scheduling horizon",
                    assignment=row,
                ))
            elif row.target_date in snapshot.supporting_dates:
                diagnostics.append(_diagnostic(
                    "supporting_date_assignment",
                    "Assignment is on an ISO-week supporting date",
                    severity=ValidationSeverity.WARNING,
                    assignment=row,
                ))
            if key not in eligibility:
                diagnostics.append(_diagnostic(
                    "ineligible_assignment",
                    "Employee is not eligible for this brand/process on this date",
                    assignment=row,
                ))

            availability_item = availability.get((row.employee_id, row.target_date))
            if availability_item is None:
                diagnostics.append(_diagnostic(
                    "missing_availability",
                    "No resolved availability exists for this employee and date",
                    assignment=row,
                ))
            elif not availability_item.available:
                diagnostics.append(_diagnostic(
                    "employee_unavailable",
                    "Employee is unavailable on the assignment date",
                    assignment=row,
                ))

            operating_item = operating.get(
                (row.brand_id, row.process_id, row.target_date)
            )
            if operating_item is None:
                diagnostics.append(_diagnostic(
                    "invalid_assignment_context",
                    "No operating rule exists for this brand/process/date",
                    assignment=row,
                ))
            elif not operating_item.operating:
                diagnostics.append(_diagnostic(
                    "non_operating_day",
                    "Assignment is on a non-operating day",
                    assignment=row,
                ))

            expected_workload = workload.get(
                (row.brand_id, row.process_id, row.target_date)
            )
            if expected_workload is None:
                diagnostics.append(_diagnostic(
                    "missing_workload",
                    "No resolved workload exists for this brand/process/date",
                    assignment=row,
                ))
                units = 0
            else:
                units = expected_workload
                if row.workload_units is not None and row.workload_units != units:
                    diagnostics.append(_diagnostic(
                        "workload_mismatch",
                        "Assignment workload does not match resolved configuration",
                        assignment=row,
                    ))

            daily[(row.employee_id, row.target_date)] = (
                daily.get((row.employee_id, row.target_date), 0) + units
            )
            iso = row.target_date.isocalendar()
            weekly_key = (row.employee_id, iso.year, iso.week)
            weekly[weekly_key] = weekly.get(weekly_key, 0) + units
            month_key = (row.employee_id, row.target_date.year, row.target_date.month)
            monthly[month_key] = monthly.get(month_key, 0) + units
            context_key = (row.brand_id, row.process_id, row.target_date)
            context_counts[context_key] = context_counts.get(context_key, 0) + 1

        for (employee_id, target), units in daily.items():
            capacity = capacities.get((employee_id, target))
            if capacity is None:
                continue
            if (
                capacity.daily_capacity_units is not None
                and units > capacity.daily_capacity_units
            ):
                diagnostics.append(ValidationDiagnostic(
                    "daily_capacity_exceeded",
                    ValidationSeverity.ERROR,
                    "Employee daily workload exceeds capacity",
                    employee_id=employee_id,
                    target_date=target,
                ))
            if (
                capacity.max_assignments_per_day is not None
                and sum(
                    row.employee_id == employee_id and row.target_date == target
                    for row in rows
                ) > capacity.max_assignments_per_day
            ):
                diagnostics.append(ValidationDiagnostic(
                    "daily_assignment_limit_exceeded",
                    ValidationSeverity.ERROR,
                    "Employee daily assignment count exceeds capacity",
                    employee_id=employee_id,
                    target_date=target,
                ))

        for (employee_id, year, week), units in weekly.items():
            limits = [
                item.weekly_capacity_units
                for item in snapshot.employee_capacities
                if item.employee_id == employee_id
                and item.target_date.isocalendar().year == year
                and item.target_date.isocalendar().week == week
                and item.weekly_capacity_units is not None
            ]
            if limits and units > min(limits):
                diagnostics.append(ValidationDiagnostic(
                    "weekly_capacity_exceeded",
                    ValidationSeverity.ERROR,
                    "Employee weekly workload exceeds capacity",
                    employee_id=employee_id,
                ))

        for (employee_id, year, month), units in monthly.items():
            limits = [
                item.monthly_capacity_units
                for item in snapshot.employee_capacities
                if item.employee_id == employee_id
                and item.target_date.year == year
                and item.target_date.month == month
                and item.monthly_capacity_units is not None
            ]
            if limits and units > min(limits):
                diagnostics.append(ValidationDiagnostic(
                    "monthly_capacity_exceeded",
                    ValidationSeverity.ERROR,
                    "Employee monthly workload exceeds capacity",
                    employee_id=employee_id,
                ))

        for rule in snapshot.operating_rules:
            if (
                rule.target_date not in snapshot.requested_dates
                or not rule.operating
                or not rule.required_coverage
                or rule.minimum_daily_staffing <= 0
            ):
                continue
            actual = context_counts.get(
                (rule.brand_id, rule.process_id, rule.target_date), 0
            )
            if actual < rule.minimum_daily_staffing:
                diagnostics.append(ValidationDiagnostic(
                    "insufficient_staffing",
                    ValidationSeverity.ERROR,
                    "Required daily staffing is not met",
                    target_date=rule.target_date,
                    brand_id=rule.brand_id,
                    process_id=rule.process_id,
                ))

        errors = tuple(
            item for item in diagnostics
            if item.severity == ValidationSeverity.ERROR
        )
        warnings = tuple(
            item for item in diagnostics
            if item.severity == ValidationSeverity.WARNING
        )
        return RosterValidationResult(
            is_valid=not errors,
            error_count=len(errors),
            warning_count=len(warnings),
            diagnostics=tuple(diagnostics),
            affected_employee_ids=tuple(sorted({
                item.employee_id for item in diagnostics
                if item.employee_id is not None
            })),
            affected_dates=tuple(sorted({
                item.target_date for item in diagnostics
                if item.target_date is not None
            })),
        )


def validate_roster(
    snapshot: ConfigurationSnapshot,
    assignments: Iterable[object] | None,
) -> RosterValidationResult:
    return RosterValidator().validate(snapshot, assignments)
