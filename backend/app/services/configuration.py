from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ApprovalStatus,
    AssignmentCompatibilityRule,
    AvailabilityStatus,
    Brand,
    BrandProcessDateOverride,
    BrandProcessOperatingRule,
    BrandProcessWorkloadRule,
    Employee,
    EmployeeAssignment,
    EmployeeAvailabilityOverride,
    EmployeeStatus,
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


class DiagnosticSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


class ConfigurationResolutionError(ValueError):
    def __init__(self, diagnostics: tuple["ConfigurationDiagnostic", ...]):
        self.diagnostics = diagnostics
        message = "; ".join(d.message for d in diagnostics)
        super().__init__(message)


@dataclass(frozen=True)
class ConfigurationDiagnostic:
    code: str
    severity: DiagnosticSeverity
    message: str
    employee_id: int | None = None
    brand_id: int | None = None
    process_id: int | None = None
    target_date: date | None = None


@dataclass(frozen=True)
class ResolvedAssignment:
    employee_id: int
    brand_id: int
    process_id: int
    effective_start_date: date
    effective_end_date: date | None
    skill_level: int
    is_primary: bool


@dataclass(frozen=True)
class AssignmentEligibility:
    employee_id: int
    brand_id: int
    process_id: int
    target_date: date
    skill_level: int
    is_primary: bool


@dataclass(frozen=True)
class ResolvedCapacity:
    daily_capacity_units: int | None
    weekly_capacity_units: int | None
    monthly_capacity_units: int | None
    max_assignments_per_day: int | None
    source_rule_id: int | None


@dataclass(frozen=True)
class ResolvedEmployeeCapacity:
    """Employee-wide limits inherit defaults when a rule field is unset."""

    employee_id: int
    target_date: date
    daily_capacity_units: int | None
    weekly_capacity_units: int | None
    monthly_capacity_units: int | None
    max_assignments_per_day: int | None
    source_rule_id: int | None


@dataclass(frozen=True)
class ResolvedCompatibility:
    employee_id: int
    brand_id: int
    process_id: int
    is_compatible: bool
    source_rule_id: int | None


@dataclass(frozen=True)
class ResolvedWorkload:
    brand_id: int
    process_id: int
    target_date: date
    workload_units: int
    source_rule_id: int


@dataclass(frozen=True)
class ResolvedAvailability:
    employee_id: int
    target_date: date
    available: bool
    status: AvailabilityStatus
    reason: str
    source_id: int | None


@dataclass(frozen=True)
class ResolvedOperatingRule:
    brand_id: int
    process_id: int
    target_date: date
    operating: bool
    required_coverage: bool
    minimum_daily_staffing: int
    source_id: int
    is_public_holiday: bool


@dataclass(frozen=True)
class ConfigurationSnapshot:
    requested_start: date
    requested_end: date
    horizon_start: date
    horizon_end: date
    requested_dates: tuple[date, ...]
    supporting_dates: tuple[date, ...]
    horizon_dates: tuple[date, ...]
    dates: tuple[date, ...]
    employees: tuple[int, ...]
    assignments: tuple[ResolvedAssignment, ...]
    assignment_eligibility: tuple[AssignmentEligibility, ...]
    availabilities: tuple[ResolvedAvailability, ...]
    capacities: tuple[tuple[int, int, int, date, ResolvedCapacity], ...]
    employee_capacities: tuple[ResolvedEmployeeCapacity, ...]
    compatibilities: tuple[ResolvedCompatibility, ...]
    process_workloads: tuple[ResolvedWorkload, ...]
    operating_rules: tuple[ResolvedOperatingRule, ...]
    public_holidays: tuple[date, ...]
    diagnostics: tuple[ConfigurationDiagnostic, ...]


def expanded_iso_week_horizon(start: date, end: date) -> tuple[date, date]:
    if end < start:
        raise ValueError("Scheduling end date must not precede start date")
    return start - timedelta(days=start.weekday()), end + timedelta(
        days=6 - end.weekday()
    )


def _dates(start: date, end: date) -> tuple[date, ...]:
    return tuple(start + timedelta(days=index) for index in range((end - start).days + 1))


def _in_period(record: object, target: date) -> bool:
    start = record.effective_start_date
    end = record.effective_end_date
    return start <= target and (end is None or end >= target)


def _matching_period_records(records: Iterable[object], target: date) -> list[object]:
    return [record for record in records if _in_period(record, target) and record.is_active]


def _select_specific_rule(
    records: Iterable[object],
    target: date,
    brand_id: int | None,
    process_id: int | None,
    label: str,
    employee_id: int | None = None,
) -> tuple[object | None, ConfigurationDiagnostic | None]:
    matches = [
        record
        for record in _matching_period_records(records, target)
        if (employee_id is None or record.employee_id == employee_id)
        and (record.brand_id is None or record.brand_id == brand_id)
        and (record.process_id is None or record.process_id == process_id)
    ]
    if not matches:
        return None, None
    specificity = max(
        int(record.brand_id is not None) + int(record.process_id is not None)
        for record in matches
    )
    best = [record for record in matches if
            int(record.brand_id is not None) + int(record.process_id is not None) == specificity]
    if len(best) > 1:
        return None, ConfigurationDiagnostic(
            code="ambiguous_effective_rule",
            severity=DiagnosticSeverity.ERROR,
            message=f"Multiple equally specific {label} rules apply",
            employee_id=employee_id,
            brand_id=brand_id,
            process_id=process_id,
            target_date=target,
        )
    return best[0], None


def _resolve_availability(
    employee_id: int,
    target: date,
    leaves: Iterable[LeaveRequest],
    overrides: Iterable[EmployeeAvailabilityOverride],
    exceptions: Iterable[EmployeeWeeklyOffException],
    patterns: Iterable[EmployeeWeeklyOffPattern],
) -> ResolvedAvailability:
    leave = next(
        (item for item in leaves
         if item.employee_id == employee_id
         and item.status == LeaveStatus.APPROVED
         and item.start_date <= target <= item.end_date),
        None,
    )
    if leave:
        return ResolvedAvailability(
            employee_id, target, False, AvailabilityStatus.UNAVAILABLE,
            f"Approved leave ({leave.leave_type}) blocks this date", leave.id,
        )

    approved_overrides = [
        item for item in overrides
        if item.employee_id == employee_id
        and item.date == target
        and item.approval_status == ApprovalStatus.APPROVED
    ]
    approved_override = approved_overrides[-1] if approved_overrides else None
    if approved_override:
        return ResolvedAvailability(
            employee_id, target,
            approved_override.status != AvailabilityStatus.UNAVAILABLE,
            approved_override.status,
            f"Approved date-specific availability override: {approved_override.reason}",
            approved_override.id,
        )

    approved_exceptions = [
        item for item in exceptions
        if item.employee_id == employee_id
        and item.date == target
        and item.approval_status == ApprovalStatus.APPROVED
    ]
    approved_exception = approved_exceptions[-1] if approved_exceptions else None
    if approved_exception:
        available = approved_exception.exception_type == ExceptionType.WORKING_DAY
        return ResolvedAvailability(
            employee_id, target, available,
            AvailabilityStatus.AVAILABLE if available else AvailabilityStatus.UNAVAILABLE,
            f"Approved weekly-off exception: {approved_exception.reason}",
            approved_exception.id,
        )

    for pattern in patterns:
        if (
            pattern.employee_id == employee_id
            and pattern.is_active
            and _in_period(pattern, target)
        ):
            marker = "BYDAY="
            values = pattern.recurrence_rule.upper().split(marker, 1)
            if len(values) == 2:
                weekdays = values[1].split(";", 1)[0].split(",")
                if ("MO", "TU", "WE", "TH", "FR", "SA", "SU")[target.weekday()] in weekdays:
                    return ResolvedAvailability(
                        employee_id, target, False, AvailabilityStatus.UNAVAILABLE,
                        f"Recurring weekly off applies: {pattern.recurrence_rule}",
                        pattern.id,
                    )

    return ResolvedAvailability(
        employee_id, target, True, AvailabilityStatus.AVAILABLE,
        "Normal availability applies", None,
    )


class ConfigurationResolver:
    """Loads database configuration once and builds an immutable scheduling snapshot."""

    def __init__(self, session: Session):
        self.session = session

    def resolve_month(self, year: int, month: int) -> ConfigurationSnapshot:
        if month < 1 or month > 12:
            raise ValueError("Scheduling month must be between 1 and 12")
        start = date(year, month, 1)
        end = date(
            year + (month == 12),
            1 if month == 12 else month + 1,
            1,
        ) - timedelta(days=1)
        return self.resolve(start, end)

    def resolve(self, start: date, end: date) -> ConfigurationSnapshot:
        if end < start:
            raise ValueError("Scheduling end date must not precede start date")
        horizon_start, horizon_end = expanded_iso_week_horizon(start, end)
        horizon_dates = _dates(horizon_start, horizon_end)
        requested_dates = _dates(start, end)
        supporting_dates = tuple(
            target for target in horizon_dates if target not in requested_dates
        )
        diagnostics: list[ConfigurationDiagnostic] = []

        employees = self.session.scalars(
            select(Employee).where(Employee.status == EmployeeStatus.ACTIVE)
        ).all()
        employee_ids = tuple(sorted(employee.id for employee in employees))
        employee_assignments = self.session.scalars(select(EmployeeAssignment)).all()
        workload_rules = self.session.scalars(select(EmployeeWorkloadRule)).all()
        compatibility_rules = self.session.scalars(
            select(AssignmentCompatibilityRule)
        ).all()
        leaves = self.session.scalars(select(LeaveRequest)).all()
        availability_overrides = self.session.scalars(
            select(EmployeeAvailabilityOverride)
        ).all()
        weekly_exceptions = self.session.scalars(
            select(EmployeeWeeklyOffException)
        ).all()
        weekly_patterns = self.session.scalars(
            select(EmployeeWeeklyOffPattern)
        ).all()
        operating_rules = self.session.scalars(
            select(BrandProcessOperatingRule)
        ).all()
        date_overrides = self.session.scalars(select(BrandProcessDateOverride)).all()
        process_workload_rules = self.session.scalars(
            select(BrandProcessWorkloadRule)
        ).all()
        holidays = tuple(sorted(
            item.date for item in self.session.scalars(select(PublicHoliday)).all()
            if item.is_active and horizon_start <= item.date <= horizon_end
        ))
        active_brand_ids = {
            item.id for item in self.session.scalars(
                select(Brand).where(Brand.is_active.is_(True))
            ).all()
        }
        active_process_ids = {
            item.id for item in self.session.scalars(
                select(Process).where(Process.is_active.is_(True))
            ).all()
        }

        assignments: list[ResolvedAssignment] = []
        for item in employee_assignments:
            if (
                item.employee_id in employee_ids
                and item.brand_id in active_brand_ids
                and item.process_id in active_process_ids
                and item.is_active
                and any(_in_period(item, target) for target in horizon_dates)
            ):
                assignments.append(ResolvedAssignment(
                    item.employee_id, item.brand_id, item.process_id,
                    item.effective_start_date, item.effective_end_date,
                    item.skill_level, item.is_primary,
                ))

        assignment_eligibility = tuple(
            AssignmentEligibility(
                assignment.employee_id,
                assignment.brand_id,
                assignment.process_id,
                target,
                assignment.skill_level,
                assignment.is_primary,
            )
            for assignment in assignments
            for target in horizon_dates
            if assignment.effective_start_date <= target
            and (
                assignment.effective_end_date is None
                or target <= assignment.effective_end_date
            )
        )

        availabilities = tuple(
            _resolve_availability(
                employee.id, target, leaves, availability_overrides,
                weekly_exceptions, weekly_patterns,
            )
            for employee in employees
            for target in horizon_dates
        )
        for employee_id in employee_ids:
            for target in horizon_dates:
                if sum(
                    item.employee_id == employee_id
                    and item.date == target
                    and item.approval_status == ApprovalStatus.APPROVED
                    for item in availability_overrides
                ) > 1:
                    diagnostics.append(ConfigurationDiagnostic(
                        "ambiguous_availability_override",
                        DiagnosticSeverity.ERROR,
                        "Multiple approved availability overrides apply",
                        employee_id=employee_id, target_date=target,
                    ))
                if sum(
                    item.employee_id == employee_id
                    and item.date == target
                    and item.approval_status == ApprovalStatus.APPROVED
                    for item in weekly_exceptions
                ) > 1:
                    diagnostics.append(ConfigurationDiagnostic(
                        "ambiguous_weekly_off_exception",
                        DiagnosticSeverity.ERROR,
                        "Multiple approved weekly-off exceptions apply",
                        employee_id=employee_id, target_date=target,
                    ))

        capacities: list[tuple[int, int, int, date, ResolvedCapacity]] = []
        compatibilities: list[ResolvedCompatibility] = []
        resolved_operating: list[ResolvedOperatingRule] = []
        assignment_contexts = {
            (item.brand_id, item.process_id) for item in assignments
        }
        assignment_contexts.update(
            (item.brand_id, item.process_id)
            for item in operating_rules
            if item.is_active
            and item.effective_start_date <= horizon_end
            and (
                item.effective_end_date is None
                or item.effective_end_date >= horizon_start
            )
        )
        assignment_contexts.update(
            (item.brand_id, item.process_id)
            for item in date_overrides
            if horizon_start <= item.date <= horizon_end
        )
        assignment_contexts.update(
            (item.brand_id, item.process_id)
            for item in process_workload_rules
            if item.is_active
            and item.effective_start_date <= horizon_end
            and (
                item.effective_end_date is None
                or item.effective_end_date >= horizon_start
            )
        )
        assignment_contexts = sorted(assignment_contexts)
        for employee_id, brand_id, process_id in (
            (item.employee_id, item.brand_id, item.process_id) for item in assignments
        ):
            employee = next(item for item in employees if item.id == employee_id)
            for target in horizon_dates:
                rule, diagnostic = _select_specific_rule(
                    workload_rules, target, brand_id, process_id,
                    "employee workload", employee_id,
                )
                if diagnostic:
                    diagnostics.append(diagnostic)
                capacities.append((
                    employee_id, brand_id, process_id, target,
                    ResolvedCapacity(
                        getattr(rule, "daily_capacity_units", None)
                        if rule else employee.daily_capacity_units,
                        getattr(rule, "weekly_capacity_units", None)
                        if rule else employee.weekly_capacity_units,
                        getattr(rule, "monthly_capacity_units", None)
                        if rule else employee.monthly_capacity_units,
                        getattr(rule, "max_assignments_per_day", None)
                        if rule else employee.max_assignments_per_day,
                        getattr(rule, "id", None),
                    ),
                ))
                compatibility, diagnostic = _select_specific_rule(
                    compatibility_rules, target, brand_id, process_id,
                    "assignment compatibility", employee_id,
                )
                if diagnostic:
                    diagnostics.append(diagnostic)
                compatibilities.append(ResolvedCompatibility(
                    employee_id, brand_id, process_id,
                    True if compatibility is None else compatibility.is_compatible,
                    None if compatibility is None else compatibility.id,
                ))

        employee_capacities: list[ResolvedEmployeeCapacity] = []
        for employee in employees:
            for target in horizon_dates:
                rule, diagnostic = _select_specific_rule(
                    workload_rules,
                    target,
                    None,
                    None,
                    "employee-wide workload",
                    employee.id,
                )
                if diagnostic:
                    diagnostics.append(diagnostic)
                employee_capacities.append(ResolvedEmployeeCapacity(
                    employee_id=employee.id,
                    target_date=target,
                    daily_capacity_units=(
                        rule.daily_capacity_units
                        if rule and rule.daily_capacity_units is not None
                        else employee.daily_capacity_units
                    ),
                    weekly_capacity_units=(
                        rule.weekly_capacity_units
                        if rule and rule.weekly_capacity_units is not None
                        else employee.weekly_capacity_units
                    ),
                    monthly_capacity_units=(
                        rule.monthly_capacity_units
                        if rule and rule.monthly_capacity_units is not None
                        else employee.monthly_capacity_units
                    ),
                    max_assignments_per_day=(
                        rule.max_assignments_per_day
                        if rule and rule.max_assignments_per_day is not None
                        else employee.max_assignments_per_day
                    ),
                    source_rule_id=rule.id if rule else None,
                ))

        weekly_capacity_values: dict[tuple[int, tuple[int, int]], set[int]] = {}
        for capacity in employee_capacities:
            if capacity.weekly_capacity_units is None:
                continue
            iso = capacity.target_date.isocalendar()
            key = (capacity.employee_id, (iso.year, iso.week))
            weekly_capacity_values.setdefault(key, set()).add(
                capacity.weekly_capacity_units
            )
        for (employee_id, iso_week), values in weekly_capacity_values.items():
            if len(values) > 1:
                diagnostics.append(ConfigurationDiagnostic(
                    code="conflicting_weekly_capacity",
                    severity=DiagnosticSeverity.ERROR,
                    message=(
                        f"Employee {employee_id} has conflicting weekly capacities "
                        f"{sorted(values)} in ISO week {iso_week[0]}-{iso_week[1]}"
                    ),
                    employee_id=employee_id,
                ))

        for brand_id, process_id in assignment_contexts:
            for target in horizon_dates:
                override = next(
                    (item for item in date_overrides
                     if item.brand_id == brand_id
                     and item.process_id == process_id
                     and item.date == target),
                    None,
                )
                if sum(
                    item.brand_id == brand_id and item.process_id == process_id
                    and item.date == target for item in date_overrides
                ) > 1:
                    diagnostics.append(ConfigurationDiagnostic(
                        "ambiguous_date_override", DiagnosticSeverity.ERROR,
                        "Multiple operating date overrides apply",
                        brand_id=brand_id, process_id=process_id, target_date=target,
                    ))
                base_rule, diagnostic = _select_specific_rule(
                    operating_rules, target, brand_id, process_id,
                    "operating", None,
                )
                if diagnostic:
                    diagnostics.append(diagnostic)
                if override:
                    operating, required, staffing, source_id = (
                        override.operating_status == OperatingStatus.OPEN,
                        override.required_coverage,
                        override.minimum_daily_staffing,
                        override.id,
                    )
                elif base_rule:
                    weekday = target.weekday()
                    weekday_codes = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
                    configured_days = base_rule.operating_weekdays.upper()
                    operating = (
                        str(weekday) in configured_days
                        or weekday_codes[weekday] in configured_days.split(",")
                    )
                    if weekday == 6:
                        operating = base_rule.sunday_working
                    if target in holidays:
                        operating = base_rule.public_holiday_working
                    required, staffing, source_id = (
                        base_rule.required_coverage,
                        base_rule.minimum_daily_staffing,
                        base_rule.id,
                    )
                else:
                    if target in requested_dates:
                        diagnostics.append(ConfigurationDiagnostic(
                            "missing_operating_rule", DiagnosticSeverity.ERROR,
                            "No effective operating rule or date override exists",
                            brand_id=brand_id,
                            process_id=process_id,
                            target_date=target,
                        ))
                    continue
                resolved_operating.append(ResolvedOperatingRule(
                    brand_id, process_id, target, operating, required, staffing,
                    source_id, target in holidays,
                ))
                if (
                    target in requested_dates
                    and operating
                    and required
                    and staffing > 0
                    and not any(
                    item.brand_id == brand_id
                    and item.process_id == process_id
                    and item.employee_id in employee_ids
                    and item.brand_id in active_brand_ids
                    and item.process_id in active_process_ids
                    and item.is_active
                    and _in_period(item, target)
                    for item in employee_assignments
                    )
                ):
                    diagnostics.append(ConfigurationDiagnostic(
                        "missing_eligible_assignment",
                        DiagnosticSeverity.ERROR,
                        "Required operating context has no eligible employee assignment",
                        brand_id=brand_id,
                        process_id=process_id,
                        target_date=target,
                    ))

        process_workloads: list[ResolvedWorkload] = []
        for brand_id, process_id in assignment_contexts:
            for target in horizon_dates:
                rule, diagnostic = _select_specific_rule(
                    process_workload_rules, target, brand_id, process_id,
                    "brand/process workload", None,
                )
                if diagnostic:
                    diagnostics.append(diagnostic)
                if rule:
                    process_workloads.append(ResolvedWorkload(
                        brand_id, process_id, target, rule.workload_units, rule.id,
                    ))
                else:
                    if target in requested_dates:
                        diagnostics.append(ConfigurationDiagnostic(
                            "missing_workload_rule", DiagnosticSeverity.ERROR,
                            "No effective brand/process workload rule exists",
                            brand_id=brand_id,
                            process_id=process_id,
                            target_date=target,
                        ))

        snapshot = ConfigurationSnapshot(
            start,
            end,
            horizon_start,
            horizon_end,
            requested_dates,
            supporting_dates,
            horizon_dates,
            horizon_dates,
            employee_ids,
            tuple(sorted(assignments, key=lambda item: (
                item.employee_id, item.brand_id, item.process_id,
            ))),
            assignment_eligibility,
            availabilities,
            tuple(capacities),
            tuple(employee_capacities),
            tuple(compatibilities),
            tuple(process_workloads),
            tuple(resolved_operating),
            holidays,
            tuple(diagnostics),
        )
        errors = tuple(
            item for item in diagnostics if item.severity == DiagnosticSeverity.ERROR
        )
        if errors:
            raise ConfigurationResolutionError(errors)
        return snapshot
