from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from calendar import monthrange
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.models import (
    AssignmentSource,
    Employee,
    EmployeeStatus,
    Roster,
    RosterAssignment,
    RosterVersion,
    RosterChangeHistory,
    SolverStatus,
    ValidationStatus,
)
from app.services.configuration import ConfigurationResolutionError, ConfigurationResolver
from app.services.scheduling import (
    SchedulingAssignment,
    SchedulingResult,
    SchedulingStatus,
    solve_schedule,
)
from app.services.validation import (
    ValidationDiagnostic,
    ValidationSeverity,
    RosterValidationResult,
    validate_roster,
)


class RosterPersistenceError(RuntimeError):
    pass


class RosterConcurrencyError(RosterPersistenceError):
    pass


class ManualRosterChangeError(ValueError):
    pass


@dataclass(frozen=True)
class RosterPipelineResult:
    year: int
    month: int
    solver_result: SchedulingResult
    validation_result: RosterValidationResult
    assignments: tuple[SchedulingAssignment, ...]


@dataclass(frozen=True)
class ManualChange:
    operation: Literal["add", "remove", "reassign", "replace"]
    assignment: SchedulingAssignment | None = None
    previous_assignment: SchedulingAssignment | None = None


def _assignment_key(item: SchedulingAssignment) -> tuple[int, date, int, int]:
    return item.employee_id, item.target_date, item.brand_id, item.process_id


def apply_manual_change(
    current: tuple[SchedulingAssignment, ...],
    change: ManualChange,
) -> tuple[SchedulingAssignment, ...]:
    rows = list(current)
    if change.operation == "add":
        if change.assignment is None:
            raise ManualRosterChangeError("An assignment is required for add")
        if _assignment_key(change.assignment) in {_assignment_key(row) for row in rows}:
            raise ManualRosterChangeError("The assignment already exists")
        rows.append(change.assignment)
    elif change.operation == "remove":
        if change.previous_assignment is None:
            raise ManualRosterChangeError("An assignment is required for remove")
        key = _assignment_key(change.previous_assignment)
        if not any(_assignment_key(row) == key for row in rows):
            raise ManualRosterChangeError("The assignment to remove was not found")
        rows = [row for row in rows if _assignment_key(row) != key]
    elif change.operation in ("reassign", "replace"):
        if change.previous_assignment is None or change.assignment is None:
            raise ManualRosterChangeError(
                "Both previous_assignment and assignment are required"
            )
        previous_key = _assignment_key(change.previous_assignment)
        if not any(_assignment_key(row) == previous_key for row in rows):
            raise ManualRosterChangeError("The assignment to replace was not found")
        rows = [row for row in rows if _assignment_key(row) != previous_key]
        if _assignment_key(change.assignment) in {_assignment_key(row) for row in rows}:
            raise ManualRosterChangeError("The replacement assignment already exists")
        rows.append(change.assignment)
    else:
        raise ManualRosterChangeError("Unsupported manual operation")
    return tuple(sorted(rows, key=lambda row: (
        row.target_date, row.brand_id, row.process_id, row.employee_id,
    )))


def _current_version(session: Session, roster_id: int) -> RosterVersion:
    roster = session.scalar(
        select(Roster)
        .options(selectinload(Roster.current_version).selectinload(
            RosterVersion.assignments
        ))
        .where(Roster.id == roster_id)
    )
    if roster is None:
        raise RosterPersistenceError("Roster was not found")
    if roster.current_version is None:
        raise RosterPersistenceError("Roster has no current version")
    return roster.current_version


def _rows_from_version(version: RosterVersion) -> tuple[SchedulingAssignment, ...]:
    return tuple(
        SchedulingAssignment(
            item.employee_id, item.date, item.brand_id, item.process_id,
            item.workload_units,
        )
        for item in version.assignments
    )


def preview_manual_change(
    session: Session,
    roster_id: int,
    expected_version_id: int,
    change: ManualChange,
) -> tuple[RosterVersion, RosterPipelineResult]:
    version = _current_version(session, roster_id)
    if version.id != expected_version_id:
        raise RosterConcurrencyError("Roster version is newer than expected")
    assignments = apply_manual_change(_rows_from_version(version), change)
    pipeline = run_roster_pipeline(
        session, version.roster.year, version.roster.month, assignments
    )
    return version, pipeline


def valid_manual_replacement_employee_ids(
    session: Session,
    roster_id: int,
    expected_version_id: int,
    previous_assignment: SchedulingAssignment,
    organization_id: int,
) -> tuple[int, ...]:
    version = _current_version(session, roster_id)
    if version.id != expected_version_id:
        raise RosterConcurrencyError("Roster version is newer than expected")
    if version.roster.organization_id != organization_id:
        raise RosterPersistenceError("Roster was not found")

    current = _rows_from_version(version)
    if not any(
        _assignment_key(item) == _assignment_key(previous_assignment)
        for item in current
    ):
        raise ManualRosterChangeError("The assignment to replace was not found")

    start, end = period_dates(version.roster.year, version.roster.month)
    snapshot = ConfigurationResolver(session).resolve(start, end)
    employee_ids = session.scalars(
        select(Employee.id).where(
            Employee.organization_id == organization_id,
            Employee.status == EmployeeStatus.ACTIVE,
            Employee.id.in_(snapshot.employees),
        )
    ).all()
    valid_ids = []
    for employee_id in employee_ids:
        if employee_id == previous_assignment.employee_id:
            continue
        replacement = SchedulingAssignment(
            employee_id=employee_id,
            target_date=previous_assignment.target_date,
            brand_id=previous_assignment.brand_id,
            process_id=previous_assignment.process_id,
            workload_units=previous_assignment.workload_units,
        )
        proposed = apply_manual_change(
            current,
            ManualChange(
                operation="replace",
                assignment=replacement,
                previous_assignment=previous_assignment,
            ),
        )
        if validate_roster(snapshot, proposed).is_valid:
            valid_ids.append(employee_id)
    return tuple(sorted(valid_ids))


def accept_manual_change(
    session: Session,
    roster_id: int,
    expected_version_id: int,
    change: ManualChange,
    changed_by: str,
) -> RosterVersion:
    version, pipeline = preview_manual_change(
        session, roster_id, expected_version_id, change
    )
    if not pipeline.validation_result.is_valid:
        raise RosterPersistenceError(
            "Manual roster change failed independent validation"
        )
    roster = version.roster
    next_version_number = (session.scalar(
        select(RosterVersion.version_number)
        .where(RosterVersion.roster_id == roster.id)
        .order_by(RosterVersion.version_number.desc())
        .limit(1)
    ) or 0) + 1
    new_version = RosterVersion(
        roster_id=roster.id,
        version_number=next_version_number,
        source_version_id=version.id,
        solver_status=version.solver_status,
        validation_status=ValidationStatus.VALID,
        objective_value=version.objective_value,
    )
    session.add(new_version)
    for item in pipeline.assignments:
        session.add(RosterAssignment(
            roster_version=new_version,
            date=item.target_date,
            employee_id=item.employee_id,
            brand_id=item.brand_id,
            process_id=item.process_id,
            workload_units=item.workload_units,
            source=AssignmentSource.MANUAL,
        ))
    changed = change.assignment or change.previous_assignment
    if changed is not None:
        session.add(RosterChangeHistory(
            roster_version=new_version,
            previous_version_id=version.id,
            change_type=change.operation,
            changed_date=changed.target_date,
            employee_id=changed.employee_id,
            brand_id=changed.brand_id,
            process_id=changed.process_id,
            previous_value=(
                repr(_assignment_key(change.previous_assignment))
                if change.previous_assignment else None
            ),
            proposed_value=repr(_assignment_key(change.assignment))
            if change.assignment else None,
            validation_status=ValidationStatus.VALID,
            reason=f"Manual roster {change.operation}",
            changed_by=changed_by,
        ))
    try:
        session.flush()
        current = session.scalar(
            select(Roster.current_version_id).where(
                Roster.id == roster.id,
                Roster.current_version_id == expected_version_id,
            )
        )
        if current != expected_version_id:
            session.rollback()
            raise RosterConcurrencyError("Roster version changed during acceptance")
        roster.current_version_id = new_version.id
        session.commit()
        session.refresh(new_version)
        return new_version
    except RosterConcurrencyError:
        raise
    except SQLAlchemyError as exc:
        session.rollback()
        raise RosterPersistenceError(
            "Manual roster change failed and was rolled back"
        ) from exc


def roster_versions(session: Session, roster_id: int) -> list[RosterVersion]:
    return session.scalars(
        select(RosterVersion)
        .where(RosterVersion.roster_id == roster_id)
        .order_by(RosterVersion.version_number)
    ).all()


def compare_versions(
    session: Session,
    roster_id: int,
    first_version_id: int,
    second_version_id: int,
) -> tuple[tuple[SchedulingAssignment, ...], tuple[SchedulingAssignment, ...]]:
    versions = session.scalars(
        select(RosterVersion).where(
            RosterVersion.roster_id == roster_id,
            RosterVersion.id.in_((first_version_id, second_version_id)),
        ).options(selectinload(RosterVersion.assignments))
    ).all()
    by_id = {version.id: version for version in versions}
    if first_version_id not in by_id or second_version_id not in by_id:
        raise RosterPersistenceError("Roster version was not found")
    return _rows_from_version(by_id[first_version_id]), _rows_from_version(
        by_id[second_version_id]
    )


def period_dates(year: int, month: int) -> tuple[date, date]:
    if month < 1 or month > 12:
        raise ValueError("Scheduling month must be between 1 and 12")
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def run_roster_pipeline(
    session: Session,
    year: int,
    month: int,
    assignments: tuple[SchedulingAssignment, ...] | None = None,
) -> RosterPipelineResult:
    start, end = period_dates(year, month)
    snapshot = ConfigurationResolver(session).resolve(start, end)
    solver_result = (
        solve_schedule(snapshot)
        if assignments is None
        else SchedulingResult(
            SchedulingStatus.FEASIBLE,
            assignments,
            (),
        )
    )
    if solver_result.status not in (
        SchedulingStatus.OPTIMAL,
        SchedulingStatus.FEASIBLE,
    ):
        diagnostics = tuple(
            ValidationDiagnostic(
                item.code,
                ValidationSeverity.ERROR,
                item.message,
                item.employee_id,
                item.target_date,
                item.brand_id,
                item.process_id,
            )
            for item in solver_result.diagnostics
        )
        return RosterPipelineResult(
            year, month, solver_result,
            RosterValidationResult(
                False, len(diagnostics), 0, diagnostics,
                tuple(sorted({
                    item.employee_id for item in diagnostics
                    if item.employee_id is not None
                })),
                tuple(sorted({
                    item.target_date for item in diagnostics
                    if item.target_date is not None
                })),
            ),
            (),
        )
    validation_result = validate_roster(snapshot, solver_result.assignments)
    return RosterPipelineResult(
        year,
        month,
        solver_result,
        validation_result,
        tuple(
            assignment for assignment in solver_result.assignments
            if assignment.target_date in snapshot.requested_dates
        ),
    )


def persist_roster(
    session: Session,
    pipeline: RosterPipelineResult,
) -> RosterVersion:
    if not pipeline.validation_result.is_valid:
        raise RosterPersistenceError(
            "Roster validation failed; invalid rosters cannot be persisted"
        )
    if pipeline.solver_result.status not in (
        SchedulingStatus.OPTIMAL,
        SchedulingStatus.FEASIBLE,
    ):
        raise RosterPersistenceError("Only feasible rosters can be persisted")
    if session.scalar(
        select(Roster).where(
            Roster.year == pipeline.year,
            Roster.month == pipeline.month,
        )
    ) is not None:
        raise RosterPersistenceError("A roster already exists for this period")

    employee_ids = {item.employee_id for item in pipeline.assignments}
    organization_ids = session.scalars(
        select(Employee.organization_id)
        .where(Employee.id.in_(employee_ids))
        .distinct()
    ).all() if employee_ids else []
    if len(organization_ids) > 1:
        raise RosterPersistenceError(
            "A roster cannot include employees from multiple organizations"
        )
    organization_id = organization_ids[0] if organization_ids else None
    roster = Roster(
        organization_id=organization_id,
        year=pipeline.year,
        month=pipeline.month,
    )
    version = RosterVersion(
        roster=roster,
        version_number=1,
        solver_status=SolverStatus(pipeline.solver_result.status.value),
        validation_status=ValidationStatus.VALID,
        objective_value=pipeline.solver_result.objective_value,
    )
    session.add(version)
    for item in pipeline.assignments:
        session.add(RosterAssignment(
            roster_version=version,
            date=item.target_date,
            employee_id=item.employee_id,
            brand_id=item.brand_id,
            process_id=item.process_id,
            workload_units=item.workload_units,
            source=AssignmentSource.GENERATED,
        ))
    try:
        session.flush()
        roster.current_version_id = version.id
        session.commit()
        session.refresh(version)
        return version
    except SQLAlchemyError as exc:
        session.rollback()
        raise RosterPersistenceError(
            "Roster persistence failed and the transaction was rolled back"
        ) from exc


def get_roster(session: Session, roster_id: int) -> Roster | None:
    return session.scalar(
        select(Roster)
        .options(
            selectinload(Roster.current_version).selectinload(
                RosterVersion.assignments
            )
        )
        .where(Roster.id == roster_id)
    )
