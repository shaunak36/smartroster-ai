from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import (
    ApprovalStatus,
    Employee,
    EmployeeAvailabilityOverride,
    EmployeeWeeklyOffException,
    EmployeeWeeklyOffPattern,
    LeaveRequest,
)
from app.schemas.api import (
    AvailabilityOverrideCreate,
    AvailabilityOverrideRead,
    AvailabilityResolution,
    LeaveCreate,
    LeaveRead,
    LeaveUpdate,
    WeeklyOffExceptionCreate,
    WeeklyOffExceptionRead,
    WeeklyOffPatternCreate,
    WeeklyOffPatternRead,
    WeeklyOffPatternUpdate,
)
from app.services.api import (
    apply_updates,
    commit_or_conflict,
    ensure_entity_exists,
    get_or_404,
    resolve_availability,
    validate_period,
)
from app.services.auth import get_current_user

router = APIRouter(
    prefix="/api", tags=["availability"], dependencies=[Depends(get_current_user)]
)


def paged(db, query, model, offset, limit):
    items = db.scalars(query.order_by(model.id).offset(offset).limit(limit)).all()
    total = len(db.scalars(query).all())
    return {"items": items, "total": total, "offset": offset, "limit": limit}


@router.get("/weekly-off-patterns", response_model=dict)
def list_weekly_off_patterns(employee_id: int | None = None, offset: int = Query(0, ge=0),
                              limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    query = select(EmployeeWeeklyOffPattern)
    if employee_id is not None:
        query = query.where(EmployeeWeeklyOffPattern.employee_id == employee_id)
    return paged(db, query, EmployeeWeeklyOffPattern, offset, limit)


@router.post("/weekly-off-patterns", response_model=WeeklyOffPatternRead, status_code=201)
def create_weekly_off_pattern(payload: WeeklyOffPatternCreate, db: Session = Depends(get_db)):
    ensure_entity_exists(db, Employee, payload.employee_id, "Employee")
    validate_period(db, EmployeeWeeklyOffPattern, {"employee_id": payload.employee_id},
                    payload.effective_start_date, payload.effective_end_date)
    record = EmployeeWeeklyOffPattern(**payload.model_dump())
    db.add(record)
    commit_or_conflict(db, "An overlapping weekly-off pattern exists")
    db.refresh(record)
    return record


@router.get("/weekly-off-patterns/{pattern_id}", response_model=WeeklyOffPatternRead)
def get_weekly_off_pattern(pattern_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, EmployeeWeeklyOffPattern, pattern_id, "Weekly-off pattern")


@router.patch("/weekly-off-patterns/{pattern_id}", response_model=WeeklyOffPatternRead)
def update_weekly_off_pattern(pattern_id: int, payload: WeeklyOffPatternUpdate, db: Session = Depends(get_db)):
    record = get_or_404(db, EmployeeWeeklyOffPattern, pattern_id, "Weekly-off pattern")
    values = payload.model_dump(exclude_unset=True)
    if "effective_end_date" in values or values.get("is_active") is True:
        validate_period(db, EmployeeWeeklyOffPattern, {"employee_id": record.employee_id},
                        record.effective_start_date,
                        values.get("effective_end_date", record.effective_end_date),
                        record.id)
    apply_updates(record, values)
    commit_or_conflict(db, "Weekly-off pattern update conflicts with an existing pattern")
    db.refresh(record)
    return record


@router.delete("/weekly-off-patterns/{pattern_id}", status_code=204)
def delete_weekly_off_pattern(pattern_id: int, db: Session = Depends(get_db)):
    record = get_or_404(db, EmployeeWeeklyOffPattern, pattern_id, "Weekly-off pattern")
    db.delete(record)
    commit_or_conflict(db)


@router.get("/weekly-off-exceptions", response_model=dict)
def list_weekly_off_exceptions(employee_id: int | None = None, offset: int = Query(0, ge=0),
                               limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    query = select(EmployeeWeeklyOffException)
    if employee_id is not None:
        query = query.where(EmployeeWeeklyOffException.employee_id == employee_id)
    return paged(db, query, EmployeeWeeklyOffException, offset, limit)


@router.post("/weekly-off-exceptions", response_model=WeeklyOffExceptionRead, status_code=201)
def create_weekly_off_exception(payload: WeeklyOffExceptionCreate, db: Session = Depends(get_db)):
    ensure_entity_exists(db, Employee, payload.employee_id, "Employee")
    record = EmployeeWeeklyOffException(**payload.model_dump())
    db.add(record)
    commit_or_conflict(db)
    db.refresh(record)
    return record


@router.get("/weekly-off-exceptions/{exception_id}", response_model=WeeklyOffExceptionRead)
def get_weekly_off_exception(exception_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, EmployeeWeeklyOffException, exception_id, "Weekly-off exception")


@router.patch("/weekly-off-exceptions/{exception_id}", response_model=WeeklyOffExceptionRead)
def update_weekly_off_exception(exception_id: int, payload: WeeklyOffExceptionCreate, db: Session = Depends(get_db)):
    record = get_or_404(db, EmployeeWeeklyOffException, exception_id, "Weekly-off exception")
    ensure_entity_exists(db, Employee, payload.employee_id, "Employee")
    apply_updates(record, payload.model_dump())
    commit_or_conflict(db)
    db.refresh(record)
    return record


@router.delete("/weekly-off-exceptions/{exception_id}", status_code=204)
def delete_weekly_off_exception(exception_id: int, db: Session = Depends(get_db)):
    record = get_or_404(db, EmployeeWeeklyOffException, exception_id, "Weekly-off exception")
    db.delete(record)
    commit_or_conflict(db)


@router.get("/availability-overrides", response_model=dict)
def list_availability_overrides(employee_id: int | None = None, offset: int = Query(0, ge=0),
                                limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    query = select(EmployeeAvailabilityOverride)
    if employee_id is not None:
        query = query.where(EmployeeAvailabilityOverride.employee_id == employee_id)
    page = paged(db, query, EmployeeAvailabilityOverride, offset, limit)
    page["items"] = [
        AvailabilityOverrideRead.model_validate(item).model_dump(mode="json")
        for item in page["items"]
    ]
    return page


@router.post("/availability-overrides", response_model=AvailabilityOverrideRead, status_code=201)
def create_availability_override(payload: AvailabilityOverrideCreate, db: Session = Depends(get_db)):
    ensure_entity_exists(db, Employee, payload.employee_id, "Employee")
    record = EmployeeAvailabilityOverride(**payload.model_dump())
    db.add(record)
    commit_or_conflict(db)
    db.refresh(record)
    return record


@router.get("/availability-overrides/{override_id}", response_model=AvailabilityOverrideRead)
def get_availability_override(override_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, EmployeeAvailabilityOverride, override_id, "Availability override")


@router.patch("/availability-overrides/{override_id}", response_model=AvailabilityOverrideRead)
def update_availability_override(override_id: int, payload: AvailabilityOverrideCreate, db: Session = Depends(get_db)):
    record = get_or_404(db, EmployeeAvailabilityOverride, override_id, "Availability override")
    ensure_entity_exists(db, Employee, payload.employee_id, "Employee")
    apply_updates(record, payload.model_dump())
    commit_or_conflict(db)
    db.refresh(record)
    return record


@router.delete("/availability-overrides/{override_id}", status_code=204)
def delete_availability_override(override_id: int, db: Session = Depends(get_db)):
    record = get_or_404(db, EmployeeAvailabilityOverride, override_id, "Availability override")
    db.delete(record)
    commit_or_conflict(db)


@router.get("/leave-requests", response_model=dict)
def list_leave_requests(employee_id: int | None = None, offset: int = Query(0, ge=0),
                        limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    query = select(LeaveRequest)
    if employee_id is not None:
        query = query.where(LeaveRequest.employee_id == employee_id)
    return paged(db, query, LeaveRequest, offset, limit)


@router.post("/leave-requests", response_model=LeaveRead, status_code=201)
def create_leave_request(payload: LeaveCreate, db: Session = Depends(get_db)):
    ensure_entity_exists(db, Employee, payload.employee_id, "Employee")
    record = LeaveRequest(**payload.model_dump())
    db.add(record)
    commit_or_conflict(db)
    db.refresh(record)
    return record


@router.get("/leave-requests/{leave_id}", response_model=LeaveRead)
def get_leave_request(leave_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, LeaveRequest, leave_id, "Leave request")


@router.patch("/leave-requests/{leave_id}", response_model=LeaveRead)
def update_leave_request(leave_id: int, payload: LeaveUpdate, db: Session = Depends(get_db)):
    record = get_or_404(db, LeaveRequest, leave_id, "Leave request")
    values = payload.model_dump(exclude_unset=True)
    if "end_date" in values and values["end_date"] < record.start_date:
        raise HTTPException(
            status_code=422,
            detail="end_date must be on or after start_date",
        )
    apply_updates(record, values)
    commit_or_conflict(db)
    db.refresh(record)
    return record


@router.delete("/leave-requests/{leave_id}", status_code=204)
def delete_leave_request(leave_id: int, db: Session = Depends(get_db)):
    record = get_or_404(db, LeaveRequest, leave_id, "Leave request")
    db.delete(record)
    commit_or_conflict(db)


@router.get("/employees/{employee_id}/availability/{target_date}", response_model=AvailabilityResolution)
def get_resolved_availability(employee_id: int, target_date: date, db: Session = Depends(get_db)):
    return resolve_availability(db, employee_id, target_date)
