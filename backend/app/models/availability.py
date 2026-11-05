from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import EffectiveDateMixin, TimestampMixin


class ExceptionType(str, Enum):
    WORKING_DAY = "working_day"
    OFF_DAY = "off_day"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class AvailabilityStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    RESTRICTED = "restricted"


class LeaveStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class EmployeeWeeklyOffPattern(EffectiveDateMixin, TimestampMixin, Base):
    __tablename__ = "employee_weekly_off_patterns"
    __table_args__ = (
        CheckConstraint(
            "effective_end_date IS NULL OR effective_end_date >= effective_start_date",
            name="ck_weekly_off_pattern_valid_dates",
        ),
        Index("ix_weekly_off_pattern_employee_period", "employee_id", "effective_start_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    recurrence_rule: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    employee: Mapped[Employee] = relationship(back_populates="weekly_off_patterns")


class EmployeeWeeklyOffException(TimestampMixin, Base):
    __tablename__ = "employee_weekly_off_exceptions"
    __table_args__ = (
        Index("ix_weekly_off_exception_employee_date", "employee_id", "date"),
        CheckConstraint("length(trim(reason)) > 0", name="ck_weekly_off_exception_reason"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    exception_type: Mapped[ExceptionType] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    approval_status: Mapped[ApprovalStatus] = mapped_column(
        String(16), default=ApprovalStatus.PENDING, nullable=False
    )
    approved_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    employee: Mapped[Employee] = relationship(back_populates="weekly_off_exceptions")


class EmployeeAvailabilityOverride(TimestampMixin, Base):
    __tablename__ = "employee_availability_overrides"
    __table_args__ = (
        CheckConstraint(
            "available_capacity_units IS NULL OR available_capacity_units >= 0",
            name="ck_availability_nonnegative_capacity",
        ),
        Index("ix_availability_override_employee_date", "employee_id", "date"),
        CheckConstraint("length(trim(reason)) > 0", name="ck_availability_override_reason"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[AvailabilityStatus] = mapped_column(String(16), nullable=False)
    available_capacity_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    approval_status: Mapped[ApprovalStatus] = mapped_column(
        String(16), default=ApprovalStatus.PENDING, nullable=False
    )

    employee: Mapped[Employee] = relationship(back_populates="availability_overrides")


class LeaveRequest(TimestampMixin, Base):
    __tablename__ = "leave_requests"
    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="ck_leave_valid_dates"),
        Index("ix_leave_employee_period", "employee_id", "start_date", "end_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    leave_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[LeaveStatus] = mapped_column(
        String(16), default=LeaveStatus.PENDING, nullable=False
    )
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(160), nullable=True)

    employee: Mapped[Employee] = relationship(back_populates="leave_requests")
