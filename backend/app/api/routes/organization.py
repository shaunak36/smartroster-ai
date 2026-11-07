from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Brand, Employee, EmployeeStatus, Pod, Process
from app.schemas.api import (
    BrandCreate,
    BrandRead,
    BrandUpdate,
    EmployeeCreate,
    EmployeeRead,
    EmployeeUpdate,
    PodCreate,
    PodRead,
    PodUpdate,
    ProcessCreate,
    ProcessRead,
    ProcessUpdate,
)
from app.services.api import (
    apply_updates,
    commit_or_conflict,
    ensure_entity_exists,
    ensure_no_dependents,
    get_or_404,
    page_query,
)
from app.services.auth import (
    OrganizationContext,
    get_current_user,
    get_organization_context,
)

router = APIRouter(
    prefix="/api", tags=["organization"], dependencies=[Depends(get_current_user)]
)


def _page(items, total: int, offset: int, limit: int, schema):
    return {
        "items": [
            schema.model_validate(item).model_dump(mode="json")
            for item in items
        ],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/employees", response_model=dict)
def list_employees(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    items, total = page_query(
        db,
        Employee,
        offset,
        limit,
        order_by=(Employee.updated_at.desc(), Employee.id.desc()),
    )
    return _page(items, total, offset, limit, EmployeeRead)


@router.post("/employees", response_model=EmployeeRead, status_code=status.HTTP_201_CREATED)
def create_employee(
    payload: EmployeeCreate,
    db: Session = Depends(get_db),
    context: OrganizationContext = Depends(get_organization_context),
):
    if payload.pod_id is not None:
        ensure_entity_exists(db, Pod, payload.pod_id, "Pod")
    employee = Employee(
        **payload.model_dump(), organization_id=context.organization_id
    )
    db.add(employee)
    commit_or_conflict(db, "Employee code or email already exists")
    db.refresh(employee)
    return employee


@router.get("/employees/{employee_id}", response_model=EmployeeRead)
def get_employee(employee_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, Employee, employee_id, "Employee")


@router.patch("/employees/{employee_id}", response_model=EmployeeRead)
def update_employee(
    employee_id: int, payload: EmployeeUpdate, db: Session = Depends(get_db)
):
    employee = get_or_404(db, Employee, employee_id, "Employee")
    if payload.pod_id is not None:
        ensure_entity_exists(db, Pod, payload.pod_id, "Pod")
    apply_updates(employee, payload.model_dump(exclude_unset=True))
    commit_or_conflict(db, "Employee email already exists")
    db.refresh(employee)
    return employee


@router.delete("/employees/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_employee(employee_id: int, db: Session = Depends(get_db)):
    employee = get_or_404(db, Employee, employee_id, "Employee")
    ensure_no_dependents(
        db,
        employee,
        ("assignments", "workload_rules", "compatibility_rules", "weekly_off_patterns",
         "weekly_off_exceptions", "availability_overrides", "leave_requests", "roster_assignments"),
        "employee",
    )
    db.delete(employee)
    commit_or_conflict(db)


@router.get("/pods", response_model=dict)
def list_pods(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    items, total = page_query(db, Pod, offset, limit)
    return _page(items, total, offset, limit, PodRead)


@router.post("/pods", response_model=PodRead, status_code=status.HTTP_201_CREATED)
def create_pod(payload: PodCreate, db: Session = Depends(get_db)):
    if payload.lead_employee_id is not None:
        ensure_entity_exists(db, Employee, payload.lead_employee_id, "Employee")
    pod = Pod(**payload.model_dump())
    db.add(pod)
    commit_or_conflict(db, "Pod code already exists")
    db.refresh(pod)
    return pod


@router.get("/pods/{pod_id}", response_model=PodRead)
def get_pod(pod_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, Pod, pod_id, "Pod")


@router.patch("/pods/{pod_id}", response_model=PodRead)
def update_pod(pod_id: int, payload: PodUpdate, db: Session = Depends(get_db)):
    pod = get_or_404(db, Pod, pod_id, "Pod")
    if payload.lead_employee_id is not None:
        ensure_entity_exists(db, Employee, payload.lead_employee_id, "Employee")
    apply_updates(pod, payload.model_dump(exclude_unset=True))
    commit_or_conflict(db)
    db.refresh(pod)
    return pod


@router.delete("/pods/{pod_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_pod(pod_id: int, db: Session = Depends(get_db)):
    pod = get_or_404(db, Pod, pod_id, "Pod")
    ensure_no_dependents(db, pod, ("employees", "brands"), "pod")
    db.delete(pod)
    commit_or_conflict(db)


@router.get("/brands", response_model=dict)
def list_brands(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    items, total = page_query(db, Brand, offset, limit)
    return _page(items, total, offset, limit, BrandRead)


@router.post("/brands", response_model=BrandRead, status_code=status.HTTP_201_CREATED)
def create_brand(payload: BrandCreate, db: Session = Depends(get_db)):
    if payload.pod_id is not None:
        ensure_entity_exists(db, Pod, payload.pod_id, "Pod")
    brand = Brand(**payload.model_dump())
    db.add(brand)
    commit_or_conflict(db, "Brand code already exists")
    db.refresh(brand)
    return brand


@router.get("/brands/{brand_id}", response_model=BrandRead)
def get_brand(brand_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, Brand, brand_id, "Brand")


@router.patch("/brands/{brand_id}", response_model=BrandRead)
def update_brand(brand_id: int, payload: BrandUpdate, db: Session = Depends(get_db)):
    brand = get_or_404(db, Brand, brand_id, "Brand")
    if payload.pod_id is not None:
        ensure_entity_exists(db, Pod, payload.pod_id, "Pod")
    apply_updates(brand, payload.model_dump(exclude_unset=True))
    commit_or_conflict(db)
    db.refresh(brand)
    return brand


@router.delete("/brands/{brand_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_brand(brand_id: int, db: Session = Depends(get_db)):
    brand = get_or_404(db, Brand, brand_id, "Brand")
    ensure_no_dependents(
        db,
        brand,
        ("assignments", "operating_rules", "date_overrides", "workload_rules", "roster_assignments"),
        "brand",
    )
    db.delete(brand)
    commit_or_conflict(db)


@router.get("/processes", response_model=dict)
def list_processes(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    items, total = page_query(db, Process, offset, limit)
    return _page(items, total, offset, limit, ProcessRead)


@router.post("/processes", response_model=ProcessRead, status_code=status.HTTP_201_CREATED)
def create_process(payload: ProcessCreate, db: Session = Depends(get_db)):
    process = Process(**payload.model_dump())
    db.add(process)
    commit_or_conflict(db, "Process code already exists")
    db.refresh(process)
    return process


@router.get("/processes/{process_id}", response_model=ProcessRead)
def get_process(process_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, Process, process_id, "Process")


@router.patch("/processes/{process_id}", response_model=ProcessRead)
def update_process(process_id: int, payload: ProcessUpdate, db: Session = Depends(get_db)):
    process = get_or_404(db, Process, process_id, "Process")
    apply_updates(process, payload.model_dump(exclude_unset=True))
    commit_or_conflict(db)
    db.refresh(process)
    return process


@router.delete("/processes/{process_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_process(process_id: int, db: Session = Depends(get_db)):
    process = get_or_404(db, Process, process_id, "Process")
    ensure_no_dependents(
        db,
        process,
        ("assignments", "operating_rules", "date_overrides", "workload_rules", "roster_assignments"),
        "process",
    )
    db.delete(process)
    commit_or_conflict(db)
