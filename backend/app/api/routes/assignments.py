from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import (
    AssignmentCompatibilityRule,
    Brand,
    Employee,
    EmployeeAssignment,
    EmployeeWorkloadRule,
    Process,
)
from app.schemas.api import (
    AssignmentCreate,
    AssignmentRead,
    AssignmentUpdate,
    CompatibilityCreate,
    CompatibilityRead,
    CompatibilityUpdate,
    WorkloadRuleCreate,
    WorkloadRuleRead,
    WorkloadRuleUpdate,
)
from app.services.api import (
    apply_updates,
    commit_or_conflict,
    ensure_entity_exists,
    get_or_404,
    page_query,
    validate_period,
)

router = APIRouter(prefix="/api", tags=["employee assignments"])


def validate_assignment_context(db: Session, employee_id: int, brand_id: int, process_id: int):
    ensure_entity_exists(db, Employee, employee_id, "Employee")
    ensure_entity_exists(db, Brand, brand_id, "Brand")
    ensure_entity_exists(db, Process, process_id, "Process")


@router.get("/assignments", response_model=dict)
def list_assignments(
    employee_id: int | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = select(EmployeeAssignment)
    if employee_id is not None:
        query = query.where(EmployeeAssignment.employee_id == employee_id)
    items = db.scalars(query.order_by(EmployeeAssignment.id).offset(offset).limit(limit)).all()
    total = len(db.scalars(query).all())
    return {"items": items, "total": total, "offset": offset, "limit": limit}


@router.post("/assignments", response_model=AssignmentRead, status_code=status.HTTP_201_CREATED)
def create_assignment(payload: AssignmentCreate, db: Session = Depends(get_db)):
    validate_assignment_context(db, payload.employee_id, payload.brand_id, payload.process_id)
    validate_period(
        db,
        EmployeeAssignment,
        {
            "employee_id": payload.employee_id,
            "brand_id": payload.brand_id,
            "process_id": payload.process_id,
        },
        payload.effective_start_date,
        payload.effective_end_date,
    )
    assignment = EmployeeAssignment(**payload.model_dump())
    db.add(assignment)
    commit_or_conflict(db, "An overlapping or duplicate employee assignment exists")
    db.refresh(assignment)
    return assignment


@router.get("/assignments/{assignment_id}", response_model=AssignmentRead)
def get_assignment(assignment_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, EmployeeAssignment, assignment_id, "Assignment")


@router.patch("/assignments/{assignment_id}", response_model=AssignmentRead)
def update_assignment(
    assignment_id: int, payload: AssignmentUpdate, db: Session = Depends(get_db)
):
    assignment = get_or_404(db, EmployeeAssignment, assignment_id, "Assignment")
    values = payload.model_dump(exclude_unset=True)
    if "effective_end_date" in values or values.get("is_active") is True:
        validate_period(
            db,
            EmployeeAssignment,
            {
                "employee_id": assignment.employee_id,
                "brand_id": assignment.brand_id,
                "process_id": assignment.process_id,
            },
            assignment.effective_start_date,
            values.get("effective_end_date", assignment.effective_end_date),
            assignment.id,
        )
    apply_updates(assignment, values)
    commit_or_conflict(db, "Assignment update conflicts with an existing assignment")
    db.refresh(assignment)
    return assignment


@router.delete("/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_assignment(assignment_id: int, db: Session = Depends(get_db)):
    assignment = get_or_404(db, EmployeeAssignment, assignment_id, "Assignment")
    db.delete(assignment)
    commit_or_conflict(db)


@router.get("/employee-workload-rules", response_model=dict)
def list_workload_rules(
    employee_id: int | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = select(EmployeeWorkloadRule)
    count_query = select(EmployeeWorkloadRule.id)
    if employee_id is not None:
        query = query.where(EmployeeWorkloadRule.employee_id == employee_id)
        count_query = count_query.where(EmployeeWorkloadRule.employee_id == employee_id)
    items = db.scalars(query.order_by(EmployeeWorkloadRule.id).offset(offset).limit(limit)).all()
    total = len(db.scalars(count_query).all())
    return {"items": items, "total": total, "offset": offset, "limit": limit}


@router.post("/employee-workload-rules", response_model=WorkloadRuleRead, status_code=201)
def create_workload_rule(payload: WorkloadRuleCreate, db: Session = Depends(get_db)):
    validate_assignment_context(
        db, payload.employee_id, payload.brand_id, payload.process_id
    ) if payload.brand_id is not None and payload.process_id is not None else ensure_entity_exists(
        db, Employee, payload.employee_id, "Employee"
    )
    if payload.brand_id is not None:
        ensure_entity_exists(db, Brand, payload.brand_id, "Brand")
    if payload.process_id is not None:
        ensure_entity_exists(db, Process, payload.process_id, "Process")
    validate_period(
        db,
        EmployeeWorkloadRule,
        {"employee_id": payload.employee_id, "brand_id": payload.brand_id, "process_id": payload.process_id},
        payload.effective_start_date,
        payload.effective_end_date,
    )
    record = EmployeeWorkloadRule(**payload.model_dump())
    db.add(record)
    commit_or_conflict(db, "An overlapping workload rule exists")
    db.refresh(record)
    return record


@router.get("/employee-workload-rules/{rule_id}", response_model=WorkloadRuleRead)
def get_workload_rule(rule_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, EmployeeWorkloadRule, rule_id, "Workload rule")


@router.patch("/employee-workload-rules/{rule_id}", response_model=WorkloadRuleRead)
def update_workload_rule(
    rule_id: int, payload: WorkloadRuleUpdate, db: Session = Depends(get_db)
):
    record = get_or_404(db, EmployeeWorkloadRule, rule_id, "Workload rule")
    values = payload.model_dump(exclude_unset=True)
    if "effective_end_date" in values or values.get("is_active") is True:
        validate_period(
            db, EmployeeWorkloadRule,
            {"employee_id": record.employee_id, "brand_id": record.brand_id, "process_id": record.process_id},
            record.effective_start_date,
            values.get("effective_end_date", record.effective_end_date),
            record.id,
        )
    apply_updates(record, values)
    commit_or_conflict(db, "Workload rule update conflicts with an existing rule")
    db.refresh(record)
    return record


@router.delete("/employee-workload-rules/{rule_id}", status_code=204)
def delete_workload_rule(rule_id: int, db: Session = Depends(get_db)):
    record = get_or_404(db, EmployeeWorkloadRule, rule_id, "Workload rule")
    db.delete(record)
    commit_or_conflict(db)


@router.get("/assignment-compatibility-rules", response_model=dict)
def list_compatibility_rules(
    employee_id: int | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = select(AssignmentCompatibilityRule)
    if employee_id is not None:
        query = query.where(AssignmentCompatibilityRule.employee_id == employee_id)
    items = db.scalars(query.order_by(AssignmentCompatibilityRule.id).offset(offset).limit(limit)).all()
    total = len(db.scalars(query).all())
    return {"items": items, "total": total, "offset": offset, "limit": limit}


@router.post("/assignment-compatibility-rules", response_model=CompatibilityRead, status_code=201)
def create_compatibility_rule(payload: CompatibilityCreate, db: Session = Depends(get_db)):
    ensure_entity_exists(db, Employee, payload.employee_id, "Employee")
    if payload.brand_id is not None:
        ensure_entity_exists(db, Brand, payload.brand_id, "Brand")
    if payload.process_id is not None:
        ensure_entity_exists(db, Process, payload.process_id, "Process")
    validate_period(
        db, AssignmentCompatibilityRule,
        {"employee_id": payload.employee_id, "brand_id": payload.brand_id, "process_id": payload.process_id},
        payload.effective_start_date, payload.effective_end_date,
    )
    record = AssignmentCompatibilityRule(**payload.model_dump())
    db.add(record)
    commit_or_conflict(db, "An overlapping compatibility rule exists")
    db.refresh(record)
    return record


@router.get("/assignment-compatibility-rules/{rule_id}", response_model=CompatibilityRead)
def get_compatibility_rule(rule_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, AssignmentCompatibilityRule, rule_id, "Compatibility rule")


@router.patch("/assignment-compatibility-rules/{rule_id}", response_model=CompatibilityRead)
def update_compatibility_rule(
    rule_id: int, payload: CompatibilityUpdate, db: Session = Depends(get_db)
):
    record = get_or_404(db, AssignmentCompatibilityRule, rule_id, "Compatibility rule")
    values = payload.model_dump(exclude_unset=True)
    if "effective_end_date" in values or values.get("is_active") is True:
        validate_period(
            db,
            AssignmentCompatibilityRule,
            {
                "employee_id": record.employee_id,
                "brand_id": record.brand_id,
                "process_id": record.process_id,
            },
            record.effective_start_date,
            values.get("effective_end_date", record.effective_end_date),
            record.id,
        )
    apply_updates(record, values)
    commit_or_conflict(db, "Compatibility rule update conflicts with an existing rule")
    db.refresh(record)
    return record


@router.delete("/assignment-compatibility-rules/{rule_id}", status_code=204)
def delete_compatibility_rule(rule_id: int, db: Session = Depends(get_db)):
    record = get_or_404(db, AssignmentCompatibilityRule, rule_id, "Compatibility rule")
    db.delete(record)
    commit_or_conflict(db)
