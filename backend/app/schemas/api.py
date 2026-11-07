from __future__ import annotations

from datetime import date, datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import (
    ApprovalStatus,
    AssignmentSource,
    AvailabilityStatus,
    ConflictSeverity,
    EmployeeStatus,
    ExceptionType,
    LeaveStatus,
    OperatingStatus,
    RosterStatus,
    SolverStatus,
    ValidationStatus,
)


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class Page(APIModel, Generic[TypeVar("T")]):
    items: list
    total: int
    offset: int
    limit: int


class EmployeeCreate(APIModel):
    employee_code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=160)
    email: str = Field(min_length=3, max_length=255)
    pod_id: int | None = None
    status: EmployeeStatus = EmployeeStatus.ACTIVE
    daily_capacity_units: int | None = Field(default=None, ge=0)
    weekly_capacity_units: int | None = Field(default=None, ge=0)
    monthly_capacity_units: int | None = Field(default=None, ge=0)
    max_assignments_per_day: int | None = Field(default=None, ge=0)


class EmployeeUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    email: str | None = Field(default=None, min_length=3, max_length=255)
    pod_id: int | None = None
    status: EmployeeStatus | None = None
    daily_capacity_units: int | None = Field(default=None, ge=0)
    weekly_capacity_units: int | None = Field(default=None, ge=0)
    monthly_capacity_units: int | None = Field(default=None, ge=0)
    max_assignments_per_day: int | None = Field(default=None, ge=0)


class EmployeeRead(EmployeeCreate, APIModel):
    id: int
    created_at: datetime
    updated_at: datetime


class PodCreate(APIModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=120)
    lead_employee_id: int | None = None
    is_active: bool = True


class PodUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    lead_employee_id: int | None = None
    is_active: bool | None = None


class PodRead(PodCreate, APIModel):
    id: int
    created_at: datetime
    updated_at: datetime


class BrandCreate(APIModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=160)
    pod_id: int | None = None
    is_active: bool = True


class BrandUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    pod_id: int | None = None
    is_active: bool | None = None


class BrandRead(BrandCreate, APIModel):
    id: int
    created_at: datetime
    updated_at: datetime


class ProcessCreate(APIModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=120)
    is_active: bool = True


class ProcessUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    is_active: bool | None = None


class ProcessRead(ProcessCreate, APIModel):
    id: int
    created_at: datetime
    updated_at: datetime


class EffectivePeriod(APIModel):
    effective_start_date: date
    effective_end_date: date | None = None

    @model_validator(mode="after")
    def validate_period(self):
        if self.effective_end_date and self.effective_end_date < self.effective_start_date:
            raise ValueError("effective_end_date must be on or after effective_start_date")
        return self


class AssignmentCreate(EffectivePeriod):
    employee_id: int
    brand_id: int
    process_id: int
    skill_level: int = Field(default=1, ge=0)
    is_primary: bool = False
    is_active: bool = True


class AssignmentUpdate(APIModel):
    skill_level: int | None = Field(default=None, ge=0)
    is_primary: bool | None = None
    is_active: bool | None = None
    effective_end_date: date | None = None


class AssignmentRead(AssignmentCreate, APIModel):
    id: int
    created_at: datetime
    updated_at: datetime


class WorkloadRuleCreate(EffectivePeriod):
    employee_id: int
    brand_id: int | None = None
    process_id: int | None = None
    daily_capacity_units: int | None = Field(default=None, ge=0)
    weekly_capacity_units: int | None = Field(default=None, ge=0)
    monthly_capacity_units: int | None = Field(default=None, ge=0)
    max_assignments_per_day: int | None = Field(default=None, ge=0)
    is_active: bool = True


class WorkloadRuleUpdate(APIModel):
    effective_end_date: date | None = None
    daily_capacity_units: int | None = Field(default=None, ge=0)
    weekly_capacity_units: int | None = Field(default=None, ge=0)
    monthly_capacity_units: int | None = Field(default=None, ge=0)
    max_assignments_per_day: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class WorkloadRuleRead(WorkloadRuleCreate, APIModel):
    id: int
    created_at: datetime
    updated_at: datetime


class CompatibilityCreate(EffectivePeriod):
    employee_id: int
    brand_id: int | None = None
    process_id: int | None = None
    is_compatible: bool
    reason: str = Field(min_length=1, max_length=500)
    is_active: bool = True


class CompatibilityUpdate(APIModel):
    effective_end_date: date | None = None
    is_compatible: bool | None = None
    reason: str | None = Field(default=None, min_length=1, max_length=500)
    is_active: bool | None = None


class CompatibilityRead(CompatibilityCreate, APIModel):
    id: int
    created_at: datetime
    updated_at: datetime


class OperatingRuleCreate(EffectivePeriod):
    brand_id: int
    process_id: int
    operating_weekdays: str = Field(min_length=1, max_length=14)
    sunday_working: bool
    public_holiday_working: bool
    required_coverage: bool
    minimum_daily_staffing: int = Field(ge=0)
    is_active: bool = True


class OperatingRuleUpdate(APIModel):
    effective_end_date: date | None = None
    operating_weekdays: str | None = Field(default=None, min_length=1, max_length=14)
    sunday_working: bool | None = None
    public_holiday_working: bool | None = None
    required_coverage: bool | None = None
    minimum_daily_staffing: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class OperatingRuleRead(OperatingRuleCreate, APIModel):
    id: int
    created_at: datetime
    updated_at: datetime


class DateOverrideCreate(APIModel):
    brand_id: int
    process_id: int
    date: date
    operating_status: OperatingStatus
    required_coverage: bool
    minimum_daily_staffing: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=500)


class DateOverrideRead(DateOverrideCreate, APIModel):
    id: int
    created_at: datetime
    updated_at: datetime


class BrandWorkloadRuleCreate(EffectivePeriod):
    brand_id: int
    process_id: int
    workload_units: int = Field(gt=0)
    is_active: bool = True


class BrandWorkloadRuleUpdate(APIModel):
    effective_end_date: date | None = None
    workload_units: int | None = Field(default=None, gt=0)
    is_active: bool | None = None


class BrandWorkloadRuleRead(BrandWorkloadRuleCreate, APIModel):
    id: int
    created_at: datetime
    updated_at: datetime


class PublicHolidayCreate(APIModel):
    date: date
    name: str = Field(min_length=1, max_length=160)
    scope: str = Field(min_length=1, max_length=80)
    is_active: bool = True


class PublicHolidayRead(PublicHolidayCreate, APIModel):
    id: int
    created_at: datetime
    updated_at: datetime


class WeeklyOffPatternCreate(EffectivePeriod):
    employee_id: int
    recurrence_rule: str = Field(min_length=1, max_length=255)
    is_active: bool = True


class WeeklyOffPatternUpdate(APIModel):
    effective_end_date: date | None = None
    recurrence_rule: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None


class WeeklyOffPatternRead(WeeklyOffPatternCreate, APIModel):
    id: int
    created_at: datetime
    updated_at: datetime


class WeeklyOffExceptionCreate(APIModel):
    employee_id: int
    date: date
    exception_type: ExceptionType
    reason: str = Field(min_length=1, max_length=500)
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    approved_by: str | None = None
    approved_at: datetime | None = None


class WeeklyOffExceptionRead(WeeklyOffExceptionCreate, APIModel):
    id: int
    created_at: datetime
    updated_at: datetime


class AvailabilityOverrideCreate(APIModel):
    employee_id: int
    date: date
    status: AvailabilityStatus
    available_capacity_units: int | None = Field(default=None, ge=0)
    reason: str = Field(min_length=1, max_length=500)
    approval_status: ApprovalStatus = ApprovalStatus.PENDING


class AvailabilityOverrideRead(AvailabilityOverrideCreate, APIModel):
    id: int
    created_at: datetime
    updated_at: datetime


class LeaveCreate(APIModel):
    employee_id: int
    start_date: date
    end_date: date
    leave_type: str = Field(min_length=1, max_length=80)
    status: LeaveStatus = LeaveStatus.PENDING
    reason: str | None = None
    approved_by: str | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class LeaveUpdate(APIModel):
    end_date: date | None = None
    leave_type: str | None = Field(default=None, min_length=1, max_length=80)
    status: LeaveStatus | None = None
    reason: str | None = None
    approved_by: str | None = None


class LeaveRead(LeaveCreate, APIModel):
    id: int
    created_at: datetime
    updated_at: datetime


class AvailabilityResolution(APIModel):
    employee_id: int
    date: date
    available: bool
    status: AvailabilityStatus
    reason: str
    source_id: int | None = None


class RosterRead(APIModel):
    id: int
    year: int
    month: int
    status: RosterStatus
    current_version_id: int | None
    created_at: datetime
    updated_at: datetime


class RosterVersionRead(APIModel):
    id: int
    roster_id: int
    version_number: int
    source_version_id: int | None
    solver_status: SolverStatus
    validation_status: ValidationStatus
    revalidation_required: bool
    created_at: datetime
    updated_at: datetime


class ConflictRead(APIModel):
    id: int
    roster_version_id: int
    conflict_type: str
    severity: ConflictSeverity
    affected_date: date | None
    employee_id: int | None
    brand_id: int | None
    process_id: int | None
    message: str
    is_resolved: bool


class RosterPeriodRequest(APIModel):
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)


class RosterAssignmentPayload(APIModel):
    employee_id: int
    date: date
    brand_id: int
    process_id: int
    workload_units: int | None = Field(default=None, ge=0)


class RosterValidationResponse(APIModel):
    is_valid: bool
    error_count: int
    warning_count: int
    diagnostics: list[dict]
    affected_employee_ids: list[int]
    affected_dates: list[date]


class RosterPreviewResponse(APIModel):
    year: int
    month: int
    solver_status: SolverStatus
    assignments: list[RosterAssignmentPayload]
    validation: RosterValidationResponse


class RosterSaveRequest(RosterPeriodRequest):
    solver_status: SolverStatus
    assignments: list[RosterAssignmentPayload]


class ManualRosterChange(APIModel):
    operation: Literal["add", "remove", "reassign", "replace"]
    assignment: RosterAssignmentPayload | None = None
    previous_assignment: RosterAssignmentPayload | None = None


class ManualRosterRequest(ManualRosterChange):
    expected_version_id: int
    changed_by: str = Field(min_length=1, max_length=160)


class ManualReplacementCandidatesRequest(APIModel):
    expected_version_id: int
    previous_assignment: RosterAssignmentPayload


class ManualRosterPreviewResponse(APIModel):
    roster_id: int
    source_version_id: int
    proposed_assignments: list[RosterAssignmentPayload]
    validation: RosterValidationResponse


class RosterVersionComparisonResponse(APIModel):
    first_version_id: int
    second_version_id: int
    added: list[RosterAssignmentPayload]
    removed: list[RosterAssignmentPayload]
