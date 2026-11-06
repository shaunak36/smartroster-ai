from __future__ import annotations

from enum import Enum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.common import CapacityMixin, EffectiveDateMixin, TimestampMixin
from app.db.base import Base


class EmployeeStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class Pod(TimestampMixin, Base):
    __tablename__ = "pods"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True
    )
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    lead_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    lead: Mapped[Employee | None] = relationship(
        back_populates="led_pods", foreign_keys=[lead_employee_id]
    )
    employees: Mapped[list[Employee]] = relationship(
        back_populates="pod", foreign_keys="Employee.pod_id"
    )
    brands: Mapped[list[Brand]] = relationship(back_populates="pod")


class Employee(CapacityMixin, TimestampMixin, Base):
    __tablename__ = "employees"
    __table_args__ = (
        CheckConstraint(
            "(daily_capacity_units IS NULL OR daily_capacity_units >= 0) AND "
            "(weekly_capacity_units IS NULL OR weekly_capacity_units >= 0) AND "
            "(monthly_capacity_units IS NULL OR monthly_capacity_units >= 0) AND "
            "(max_assignments_per_day IS NULL OR max_assignments_per_day >= 0)",
            name="ck_employee_nonnegative_capacity",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True
    )
    employee_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    pod_id: Mapped[int | None] = mapped_column(
        ForeignKey("pods.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[EmployeeStatus] = mapped_column(
        String(16), default=EmployeeStatus.ACTIVE, nullable=False
    )

    pod: Mapped[Pod | None] = relationship(
        back_populates="employees", foreign_keys=[pod_id]
    )
    led_pods: Mapped[list[Pod]] = relationship(
        back_populates="lead", foreign_keys="Pod.lead_employee_id"
    )
    assignments: Mapped[list[EmployeeAssignment]] = relationship(
        back_populates="employee", cascade="all, delete-orphan"
    )
    workload_rules: Mapped[list[EmployeeWorkloadRule]] = relationship(
        back_populates="employee", cascade="all, delete-orphan"
    )
    compatibility_rules: Mapped[list[AssignmentCompatibilityRule]] = relationship(
        back_populates="employee", cascade="all, delete-orphan"
    )
    weekly_off_patterns: Mapped[list[EmployeeWeeklyOffPattern]] = relationship(
        back_populates="employee", cascade="all, delete-orphan"
    )
    weekly_off_exceptions: Mapped[list[EmployeeWeeklyOffException]] = relationship(
        back_populates="employee", cascade="all, delete-orphan"
    )
    availability_overrides: Mapped[list[EmployeeAvailabilityOverride]] = relationship(
        back_populates="employee", cascade="all, delete-orphan"
    )
    leave_requests: Mapped[list[LeaveRequest]] = relationship(
        back_populates="employee", cascade="all, delete-orphan"
    )
    roster_assignments: Mapped[list[RosterAssignment]] = relationship(
        back_populates="employee"
    )


class Brand(TimestampMixin, Base):
    __tablename__ = "brands"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True
    )
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    pod_id: Mapped[int | None] = mapped_column(
        ForeignKey("pods.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    pod: Mapped[Pod | None] = relationship(back_populates="brands")
    assignments: Mapped[list[EmployeeAssignment]] = relationship(
        back_populates="brand", cascade="all, delete-orphan"
    )
    operating_rules: Mapped[list[BrandProcessOperatingRule]] = relationship(
        back_populates="brand", cascade="all, delete-orphan"
    )
    date_overrides: Mapped[list[BrandProcessDateOverride]] = relationship(
        back_populates="brand", cascade="all, delete-orphan"
    )
    workload_rules: Mapped[list[BrandProcessWorkloadRule]] = relationship(
        back_populates="brand", cascade="all, delete-orphan"
    )
    roster_assignments: Mapped[list[RosterAssignment]] = relationship(
        back_populates="brand"
    )


class Process(TimestampMixin, Base):
    __tablename__ = "processes"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True
    )
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    assignments: Mapped[list[EmployeeAssignment]] = relationship(
        back_populates="process", cascade="all, delete-orphan"
    )
    operating_rules: Mapped[list[BrandProcessOperatingRule]] = relationship(
        back_populates="process", cascade="all, delete-orphan"
    )
    date_overrides: Mapped[list[BrandProcessDateOverride]] = relationship(
        back_populates="process", cascade="all, delete-orphan"
    )
    workload_rules: Mapped[list[BrandProcessWorkloadRule]] = relationship(
        back_populates="process", cascade="all, delete-orphan"
    )
    roster_assignments: Mapped[list[RosterAssignment]] = relationship(
        back_populates="process"
    )


class EmployeeAssignment(EffectiveDateMixin, TimestampMixin, Base):
    __tablename__ = "employee_assignments"
    __table_args__ = (
        CheckConstraint("skill_level >= 0", name="ck_employee_assignment_skill_level"),
        CheckConstraint(
            "effective_end_date IS NULL OR effective_end_date >= effective_start_date",
            name="ck_employee_assignment_valid_dates",
        ),
        UniqueConstraint(
            "employee_id",
            "brand_id",
            "process_id",
            "effective_start_date",
            name="uq_employee_brand_process_assignment_start",
        ),
        Index("ix_employee_assignment_lookup", "employee_id", "brand_id", "process_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    brand_id: Mapped[int] = mapped_column(
        ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    process_id: Mapped[int] = mapped_column(
        ForeignKey("processes.id", ondelete="CASCADE"), nullable=False
    )
    skill_level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    employee: Mapped[Employee] = relationship(back_populates="assignments")
    brand: Mapped[Brand] = relationship(back_populates="assignments")
    process: Mapped[Process] = relationship(back_populates="assignments")


class EmployeeWorkloadRule(EffectiveDateMixin, TimestampMixin, Base):
    __tablename__ = "employee_workload_rules"
    __table_args__ = (
        Index(
            "ix_employee_workload_rule_context",
            "employee_id",
            "brand_id",
            "process_id",
            "effective_start_date",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    brand_id: Mapped[int | None] = mapped_column(
        ForeignKey("brands.id", ondelete="CASCADE"), nullable=True
    )
    process_id: Mapped[int | None] = mapped_column(
        ForeignKey("processes.id", ondelete="CASCADE"), nullable=True
    )
    daily_capacity_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weekly_capacity_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    monthly_capacity_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_assignments_per_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    employee: Mapped[Employee] = relationship(back_populates="workload_rules")
    brand: Mapped[Brand | None] = relationship()
    process: Mapped[Process | None] = relationship()


class AssignmentCompatibilityRule(EffectiveDateMixin, TimestampMixin, Base):
    __tablename__ = "assignment_compatibility_rules"
    __table_args__ = (
        Index(
            "ix_assignment_compatibility_context",
            "employee_id",
            "brand_id",
            "process_id",
            "effective_start_date",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    brand_id: Mapped[int | None] = mapped_column(
        ForeignKey("brands.id", ondelete="CASCADE"), nullable=True
    )
    process_id: Mapped[int | None] = mapped_column(
        ForeignKey("processes.id", ondelete="CASCADE"), nullable=True
    )
    is_compatible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    employee: Mapped[Employee] = relationship(back_populates="compatibility_rules")
    brand: Mapped[Brand | None] = relationship()
    process: Mapped[Process | None] = relationship()
