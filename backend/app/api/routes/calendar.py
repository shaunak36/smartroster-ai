from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import (
    Brand,
    BrandProcessDateOverride,
    BrandProcessOperatingRule,
    BrandProcessWorkloadRule,
    Process,
    PublicHoliday,
)
from app.schemas.api import (
    BrandWorkloadRuleCreate,
    BrandWorkloadRuleRead,
    BrandWorkloadRuleUpdate,
    DateOverrideCreate,
    DateOverrideRead,
    OperatingRuleCreate,
    OperatingRuleRead,
    OperatingRuleUpdate,
    PublicHolidayCreate,
    PublicHolidayRead,
)
from app.services.api import (
    apply_updates,
    commit_or_conflict,
    ensure_entity_exists,
    get_or_404,
    validate_period,
)
from app.services.auth import get_current_user

router = APIRouter(
    prefix="/api", tags=["calendars"], dependencies=[Depends(get_current_user)]
)


def validate_brand_process(db: Session, brand_id: int, process_id: int):
    ensure_entity_exists(db, Brand, brand_id, "Brand")
    ensure_entity_exists(db, Process, process_id, "Process")


def paged(db, query, model, offset, limit):
    items = db.scalars(query.order_by(model.id).offset(offset).limit(limit)).all()
    total = len(db.scalars(query).all())
    return {"items": items, "total": total, "offset": offset, "limit": limit}


@router.get("/operating-rules", response_model=dict)
def list_operating_rules(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    return paged(db, select(BrandProcessOperatingRule), BrandProcessOperatingRule, offset, limit)


@router.post("/operating-rules", response_model=OperatingRuleRead, status_code=status.HTTP_201_CREATED)
def create_operating_rule(payload: OperatingRuleCreate, db: Session = Depends(get_db)):
    validate_brand_process(db, payload.brand_id, payload.process_id)
    validate_period(db, BrandProcessOperatingRule, {"brand_id": payload.brand_id, "process_id": payload.process_id},
                    payload.effective_start_date, payload.effective_end_date)
    record = BrandProcessOperatingRule(**payload.model_dump())
    db.add(record)
    commit_or_conflict(db, "An overlapping operating rule exists")
    db.refresh(record)
    return record


@router.get("/operating-rules/{rule_id}", response_model=OperatingRuleRead)
def get_operating_rule(rule_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, BrandProcessOperatingRule, rule_id, "Operating rule")


@router.patch("/operating-rules/{rule_id}", response_model=OperatingRuleRead)
def update_operating_rule(rule_id: int, payload: OperatingRuleUpdate, db: Session = Depends(get_db)):
    record = get_or_404(db, BrandProcessOperatingRule, rule_id, "Operating rule")
    values = payload.model_dump(exclude_unset=True)
    if "effective_end_date" in values or values.get("is_active") is True:
        validate_period(db, BrandProcessOperatingRule, {"brand_id": record.brand_id, "process_id": record.process_id},
                        record.effective_start_date,
                        values.get("effective_end_date", record.effective_end_date),
                        record.id)
    apply_updates(record, values)
    commit_or_conflict(db, "Operating rule update conflicts with an existing rule")
    db.refresh(record)
    return record


@router.delete("/operating-rules/{rule_id}", status_code=204)
def delete_operating_rule(rule_id: int, db: Session = Depends(get_db)):
    record = get_or_404(db, BrandProcessOperatingRule, rule_id, "Operating rule")
    db.delete(record)
    commit_or_conflict(db)


@router.get("/operating-overrides", response_model=dict)
def list_operating_overrides(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    return paged(db, select(BrandProcessDateOverride), BrandProcessDateOverride, offset, limit)


@router.post("/operating-overrides", response_model=DateOverrideRead, status_code=201)
def create_operating_override(payload: DateOverrideCreate, db: Session = Depends(get_db)):
    validate_brand_process(db, payload.brand_id, payload.process_id)
    record = BrandProcessDateOverride(**payload.model_dump())
    db.add(record)
    commit_or_conflict(db)
    db.refresh(record)
    return record


@router.get("/operating-overrides/{override_id}", response_model=DateOverrideRead)
def get_operating_override(override_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, BrandProcessDateOverride, override_id, "Operating override")


@router.patch("/operating-overrides/{override_id}", response_model=DateOverrideRead)
def update_operating_override(override_id: int, payload: DateOverrideCreate, db: Session = Depends(get_db)):
    record = get_or_404(db, BrandProcessDateOverride, override_id, "Operating override")
    validate_brand_process(db, payload.brand_id, payload.process_id)
    apply_updates(record, payload.model_dump())
    commit_or_conflict(db)
    db.refresh(record)
    return record


@router.delete("/operating-overrides/{override_id}", status_code=204)
def delete_operating_override(override_id: int, db: Session = Depends(get_db)):
    record = get_or_404(db, BrandProcessDateOverride, override_id, "Operating override")
    db.delete(record)
    commit_or_conflict(db)


@router.get("/brand-process-workload-rules", response_model=dict)
def list_brand_workload_rules(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    return paged(db, select(BrandProcessWorkloadRule), BrandProcessWorkloadRule, offset, limit)


@router.post("/brand-process-workload-rules", response_model=BrandWorkloadRuleRead, status_code=201)
def create_brand_workload_rule(payload: BrandWorkloadRuleCreate, db: Session = Depends(get_db)):
    validate_brand_process(db, payload.brand_id, payload.process_id)
    validate_period(db, BrandProcessWorkloadRule, {"brand_id": payload.brand_id, "process_id": payload.process_id},
                    payload.effective_start_date, payload.effective_end_date)
    record = BrandProcessWorkloadRule(**payload.model_dump())
    db.add(record)
    commit_or_conflict(db, "An overlapping brand/process workload rule exists")
    db.refresh(record)
    return record


@router.patch("/brand-process-workload-rules/{rule_id}", response_model=BrandWorkloadRuleRead)
def update_brand_workload_rule(rule_id: int, payload: BrandWorkloadRuleUpdate, db: Session = Depends(get_db)):
    record = get_or_404(db, BrandProcessWorkloadRule, rule_id, "Brand/process workload rule")
    values = payload.model_dump(exclude_unset=True)
    if "effective_end_date" in values or values.get("is_active") is True:
        validate_period(db, BrandProcessWorkloadRule, {"brand_id": record.brand_id, "process_id": record.process_id},
                        record.effective_start_date,
                        values.get("effective_end_date", record.effective_end_date),
                        record.id)
    apply_updates(record, values)
    commit_or_conflict(db, "Workload rule update conflicts with an existing rule")
    db.refresh(record)
    return record


@router.delete("/brand-process-workload-rules/{rule_id}", status_code=204)
def delete_brand_workload_rule(rule_id: int, db: Session = Depends(get_db)):
    record = get_or_404(db, BrandProcessWorkloadRule, rule_id, "Brand/process workload rule")
    db.delete(record)
    commit_or_conflict(db)


@router.get("/public-holidays", response_model=dict)
def list_public_holidays(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    return paged(db, select(PublicHoliday), PublicHoliday, offset, limit)


@router.post("/public-holidays", response_model=PublicHolidayRead, status_code=201)
def create_public_holiday(payload: PublicHolidayCreate, db: Session = Depends(get_db)):
    record = PublicHoliday(**payload.model_dump())
    db.add(record)
    commit_or_conflict(db, "A public holiday already exists for this date")
    db.refresh(record)
    return record


@router.get("/public-holidays/{holiday_id}", response_model=PublicHolidayRead)
def get_public_holiday(holiday_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, PublicHoliday, holiday_id, "Public holiday")


@router.patch("/public-holidays/{holiday_id}", response_model=PublicHolidayRead)
def update_public_holiday(holiday_id: int, payload: PublicHolidayCreate, db: Session = Depends(get_db)):
    record = get_or_404(db, PublicHoliday, holiday_id, "Public holiday")
    apply_updates(record, payload.model_dump())
    commit_or_conflict(db, "A public holiday already exists for this date")
    db.refresh(record)
    return record


@router.delete("/public-holidays/{holiday_id}", status_code=204)
def delete_public_holiday(holiday_id: int, db: Session = Depends(get_db)):
    record = get_or_404(db, PublicHoliday, holiday_id, "Public holiday")
    db.delete(record)
    commit_or_conflict(db)
