from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Roster, RosterAssignment, SolverStatus
from app.schemas.api import (
    ManualRosterPreviewResponse,
    ManualRosterRequest,
    RosterAssignmentPayload,
    RosterPeriodRequest,
    RosterPreviewResponse,
    RosterRead,
    RosterSaveRequest,
    RosterValidationResponse,
    RosterVersionComparisonResponse,
    RosterVersionRead,
)
from app.services.roster import (
    ManualChange,
    ManualRosterChangeError,
    RosterConcurrencyError,
    RosterPersistenceError,
    accept_manual_change,
    compare_versions,
    get_roster,
    period_dates,
    persist_roster,
    preview_manual_change,
    run_roster_pipeline,
    roster_versions,
)
from app.services.configuration import ConfigurationResolutionError
from app.services.scheduling import SchedulingAssignment
from app.services.auth import get_current_user

router = APIRouter(
    prefix="/api/rosters",
    tags=["rosters"],
    dependencies=[Depends(get_current_user)],
)
logger = logging.getLogger(__name__)


def _diagnostic_payload(item):
    return {
        "code": item.code,
        "severity": item.severity.value,
        "message": item.message,
        "employee_id": item.employee_id,
        "target_date": item.target_date.isoformat()
        if item.target_date is not None else None,
        "brand_id": item.brand_id,
        "process_id": item.process_id,
    }


def _validation_response(result) -> RosterValidationResponse:
    return RosterValidationResponse(
        is_valid=result.is_valid,
        error_count=result.error_count,
        warning_count=result.warning_count,
        diagnostics=[_diagnostic_payload(item) for item in result.diagnostics],
        affected_employee_ids=list(result.affected_employee_ids),
        affected_dates=list(result.affected_dates),
    )


def _assignment_key(item: SchedulingAssignment):
    return item.employee_id, item.target_date, item.brand_id, item.process_id


def _assignment_payload(item: SchedulingAssignment) -> RosterAssignmentPayload:
    return RosterAssignmentPayload(
        employee_id=item.employee_id,
        date=item.target_date,
        brand_id=item.brand_id,
        process_id=item.process_id,
        workload_units=item.workload_units,
    )


def _preview_response(pipeline) -> RosterPreviewResponse:
    return RosterPreviewResponse(
        year=pipeline.year,
        month=pipeline.month,
        solver_status=pipeline.solver_result.status.value,
        assignments=[
            RosterAssignmentPayload(
                employee_id=item.employee_id,
                date=item.target_date,
                brand_id=item.brand_id,
                process_id=item.process_id,
                workload_units=item.workload_units,
            )
            for item in pipeline.assignments
        ],
        validation=_validation_response(pipeline.validation_result),
    )


def _manual_change(payload: ManualRosterRequest) -> ManualChange:
    def convert(item):
        if item is None:
            return None
        return SchedulingAssignment(
            item.employee_id, item.date, item.brand_id, item.process_id,
            item.workload_units or 0,
        )
    return ManualChange(
        payload.operation,
        convert(payload.assignment),
        convert(payload.previous_assignment),
    )


def _manual_preview_response(roster_id, version_id, pipeline):
    return ManualRosterPreviewResponse(
        roster_id=roster_id,
        source_version_id=version_id,
        proposed_assignments=[
            RosterAssignmentPayload(
                employee_id=item.employee_id,
                date=item.target_date,
                brand_id=item.brand_id,
                process_id=item.process_id,
                workload_units=item.workload_units,
            )
            for item in pipeline.assignments
        ],
        validation=_validation_response(pipeline.validation_result),
    )


def _manual_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ConfigurationResolutionError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_configuration",
                "diagnostics": [
                    _diagnostic_payload(item) for item in exc.diagnostics
                ],
            },
        )
    if isinstance(exc, RosterConcurrencyError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "roster_version_conflict", "message": str(exc)},
        )
    if isinstance(exc, ManualRosterChangeError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_manual_change", "message": str(exc)},
        )
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": "manual_change_rejected", "message": str(exc)},
    )


def _run_or_http(db: Session, year: int, month: int, assignments=None):
    try:
        return run_roster_pipeline(db, year, month, assignments)
    except ConfigurationResolutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_configuration",
                "diagnostics": [
                    _diagnostic_payload(item) for item in exc.diagnostics
                ],
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_period", "message": str(exc)},
        ) from exc


@router.post("/preview", response_model=RosterPreviewResponse)
def preview_roster(payload: RosterPeriodRequest, db: Session = Depends(get_db)):
    return _preview_response(_run_or_http(db, payload.year, payload.month))


@router.post("/generate", response_model=RosterPreviewResponse)
def generate_roster(payload: RosterPeriodRequest, db: Session = Depends(get_db)):
    return _preview_response(_run_or_http(db, payload.year, payload.month))


@router.post("/validate", response_model=RosterValidationResponse)
def validate_roster_endpoint(
    payload: RosterSaveRequest, db: Session = Depends(get_db)
):
    assignments = tuple(SchedulingAssignment(
        item.employee_id, item.date, item.brand_id, item.process_id,
        item.workload_units or 0,
    ) for item in payload.assignments)
    pipeline = _run_or_http(db, payload.year, payload.month, assignments)
    return _validation_response(pipeline.validation_result)


@router.post("/save", response_model=RosterRead, status_code=status.HTTP_201_CREATED)
def save_roster(payload: RosterSaveRequest, db: Session = Depends(get_db)):
    if payload.solver_status not in (
        SolverStatus.OPTIMAL,
        SolverStatus.FEASIBLE,
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_solver_status",
                "message": "Only feasible or optimal rosters can be saved",
            },
        )
    assignments = tuple(SchedulingAssignment(
        item.employee_id, item.date, item.brand_id, item.process_id,
        item.workload_units or 0,
    ) for item in payload.assignments)
    pipeline = _run_or_http(db, payload.year, payload.month, assignments)
    if not pipeline.validation_result.is_valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "validation_failed",
                "validation": _validation_response(pipeline.validation_result).model_dump(),
            },
        )
    try:
        version = persist_roster(db, pipeline)
    except RosterPersistenceError as exc:
        logger.exception(
            "Roster persistence failed for %04d-%02d",
            payload.year,
            payload.month,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "roster_persistence_failed", "message": str(exc)},
        ) from exc
    return version.roster


@router.post(
    "/{roster_id}/manual/preview",
    response_model=ManualRosterPreviewResponse,
)
def preview_manual_roster(
    roster_id: int,
    payload: ManualRosterRequest,
    db: Session = Depends(get_db),
):
    try:
        version, pipeline = preview_manual_change(
            db, roster_id, payload.expected_version_id, _manual_change(payload)
        )
    except (
        ConfigurationResolutionError,
        RosterPersistenceError,
        ManualRosterChangeError,
    ) as exc:
        raise _manual_error(exc) from exc
    return _manual_preview_response(roster_id, version.id, pipeline)


@router.post("/{roster_id}/manual/accept", response_model=RosterVersionRead)
def accept_manual_roster(
    roster_id: int,
    payload: ManualRosterRequest,
    db: Session = Depends(get_db),
):
    try:
        version = accept_manual_change(
            db,
            roster_id,
            payload.expected_version_id,
            _manual_change(payload),
            payload.changed_by,
        )
    except (
        ConfigurationResolutionError,
        RosterPersistenceError,
        ManualRosterChangeError,
    ) as exc:
        raise _manual_error(exc) from exc
    return version


@router.get("/{roster_id}/versions", response_model=list[RosterVersionRead])
def retrieve_roster_versions(roster_id: int, db: Session = Depends(get_db)):
    if db.get(Roster, roster_id) is None:
        raise HTTPException(status_code=404, detail="Roster was not found")
    return roster_versions(db, roster_id)


@router.get(
    "/{roster_id}/versions/{first_version_id}/compare/{second_version_id}",
    response_model=RosterVersionComparisonResponse,
)
def compare_roster_versions(
    roster_id: int,
    first_version_id: int,
    second_version_id: int,
    db: Session = Depends(get_db),
):
    try:
        first, second = compare_versions(
            db, roster_id, first_version_id, second_version_id
        )
    except RosterPersistenceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    first_by_key = {_assignment_key(item): item for item in first}
    second_by_key = {_assignment_key(item): item for item in second}
    return RosterVersionComparisonResponse(
        first_version_id=first_version_id,
        second_version_id=second_version_id,
        added=[
            _assignment_payload(second_by_key[key])
            for key in sorted(second_by_key.keys() - first_by_key.keys())
        ],
        removed=[
            _assignment_payload(first_by_key[key])
            for key in sorted(first_by_key.keys() - second_by_key.keys())
        ],
    )


@router.get("/{roster_id}", response_model=RosterRead)
def retrieve_roster(roster_id: int, db: Session = Depends(get_db)):
    roster = get_roster(db, roster_id)
    if roster is None:
        raise HTTPException(status_code=404, detail="Roster was not found")
    return roster


@router.get("/{roster_id}/assignments", response_model=list[RosterAssignmentPayload])
def retrieve_roster_assignments(
    roster_id: int, db: Session = Depends(get_db)
):
    roster = db.get(Roster, roster_id)
    if roster is None:
        raise HTTPException(status_code=404, detail="Roster was not found")
    if roster.current_version_id is None:
        return []
    rows = db.scalars(
        select(RosterAssignment)
        .where(RosterAssignment.roster_version_id == roster.current_version_id)
        .order_by(RosterAssignment.date, RosterAssignment.id)
    ).all()
    return [
        RosterAssignmentPayload(
            employee_id=row.employee_id,
            date=row.date,
            brand_id=row.brand_id,
            process_id=row.process_id,
            workload_units=row.workload_units,
        )
        for row in rows
    ]
