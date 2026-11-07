from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import (
    ApprovalStatus,
    AvailabilityStatus,
    Employee,
    EmployeeAvailabilityOverride,
    EmployeeWeeklyOffException,
    EmployeeWeeklyOffPattern,
    ExceptionType,
    LeaveRequest,
    LeaveStatus,
)
from app.services.effective_dates import (
    EffectivePeriodOverlapError,
    ensure_no_effective_period_overlap,
)


def not_found(entity: str, entity_id: int) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{entity} {entity_id} was not found")


def conflict(message: str) -> HTTPException:
    return HTTPException(status_code=409, detail=message)


def get_or_404(session: Session, model: Any, entity_id: int, entity: str | None = None):
    result = session.get(model, entity_id)
    if result is None:
        raise not_found(entity or model.__name__, entity_id)
    return result


def require_related(session: Session, model: Any, entity_id: int, entity: str):
    return get_or_404(session, model, entity_id, entity)


def commit_or_conflict(session: Session, message: str = "The record conflicts with existing data"):
    try:
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        raise conflict(message) from exc


def page_query(
    session: Session,
    model: Any,
    offset: int,
    limit: int,
    order_by: tuple[Any, ...] | None = None,
):
    total = session.scalar(select(func.count()).select_from(model)) or 0
    items = session.scalars(
        select(model)
        .order_by(*(order_by or (model.id,)))
        .offset(offset)
        .limit(limit)
    ).all()
    return items, total


def apply_updates(record: Any, values: dict[str, Any]) -> Any:
    for key, value in values.items():
        setattr(record, key, value)
    return record


def validate_period(
    session: Session,
    model: Any,
    context: dict[str, Any],
    start: date,
    end: date | None,
    record_id: int | None = None,
) -> None:
    try:
        ensure_no_effective_period_overlap(
            session, model, context, start, end, exclude_id=record_id
        )
    except (EffectivePeriodOverlapError, ValueError) as exc:
        raise conflict(str(exc)) from exc


def ensure_entity_exists(session: Session, model: Any, entity_id: int, label: str) -> None:
    if session.get(model, entity_id) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{label} {entity_id} does not exist",
        )


def ensure_no_dependents(
    session: Session, record: Any, relationships: Iterable[str], label: str
) -> None:
    for relationship_name in relationships:
        if getattr(record, relationship_name):
            raise conflict(f"Cannot delete {label}; it has dependent {relationship_name}")


def _approved_leave(session: Session, employee_id: int, target: date):
    return session.scalar(
        select(LeaveRequest)
        .where(
            LeaveRequest.employee_id == employee_id,
            LeaveRequest.status == LeaveStatus.APPROVED,
            LeaveRequest.start_date <= target,
            LeaveRequest.end_date >= target,
        )
        .limit(1)
    )


def _weekday_in_pattern(recurrence_rule: str, target: date) -> bool:
    day_codes = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
    marker = "BYDAY="
    if marker not in recurrence_rule.upper():
        return False
    values = recurrence_rule.upper().split(marker, 1)[1].split(";", 1)[0].split(",")
    return day_codes[target.weekday()] in values


def resolve_availability(session: Session, employee_id: int, target: date) -> dict[str, Any]:
    employee = get_or_404(session, Employee, employee_id, "Employee")
    leave = _approved_leave(session, employee.id, target)
    if leave:
        return {
            "employee_id": employee.id,
            "date": target,
            "available": False,
            "status": AvailabilityStatus.UNAVAILABLE,
            "reason": f"Approved leave ({leave.leave_type}) blocks this date",
            "source_id": leave.id,
        }

    override = session.scalar(
        select(EmployeeAvailabilityOverride)
        .where(
            EmployeeAvailabilityOverride.employee_id == employee.id,
            EmployeeAvailabilityOverride.date == target,
            EmployeeAvailabilityOverride.approval_status == ApprovalStatus.APPROVED,
        )
        .order_by(EmployeeAvailabilityOverride.id.desc())
        .limit(1)
    )
    if override:
        return {
            "employee_id": employee.id,
            "date": target,
            "available": override.status != AvailabilityStatus.UNAVAILABLE,
            "status": override.status,
            "reason": f"Approved date-specific availability override: {override.reason}",
            "source_id": override.id,
        }

    exception = session.scalar(
        select(EmployeeWeeklyOffException)
        .where(
            EmployeeWeeklyOffException.employee_id == employee.id,
            EmployeeWeeklyOffException.date == target,
            EmployeeWeeklyOffException.approval_status == ApprovalStatus.APPROVED,
        )
        .order_by(EmployeeWeeklyOffException.id.desc())
        .limit(1)
    )
    if exception:
        available = exception.exception_type == ExceptionType.WORKING_DAY
        return {
            "employee_id": employee.id,
            "date": target,
            "available": available,
            "status": AvailabilityStatus.AVAILABLE if available else AvailabilityStatus.UNAVAILABLE,
            "reason": f"Approved weekly-off exception: {exception.reason}",
            "source_id": exception.id,
        }

    patterns = session.scalars(
        select(EmployeeWeeklyOffPattern).where(
            EmployeeWeeklyOffPattern.employee_id == employee.id,
            EmployeeWeeklyOffPattern.is_active.is_(True),
            EmployeeWeeklyOffPattern.effective_start_date <= target,
            (EmployeeWeeklyOffPattern.effective_end_date.is_(None))
            | (EmployeeWeeklyOffPattern.effective_end_date >= target),
        )
    ).all()
    for pattern in patterns:
        if _weekday_in_pattern(pattern.recurrence_rule, target):
            return {
                "employee_id": employee.id,
                "date": target,
                "available": False,
                "status": AvailabilityStatus.UNAVAILABLE,
                "reason": f"Recurring weekly off applies: {pattern.recurrence_rule}",
                "source_id": pattern.id,
            }

    return {
        "employee_id": employee.id,
        "date": target,
        "available": True,
        "status": AvailabilityStatus.AVAILABLE,
        "reason": "Normal availability applies",
        "source_id": None,
    }
