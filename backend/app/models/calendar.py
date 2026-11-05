from __future__ import annotations

from enum import Enum
from datetime import date

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import EffectiveDateMixin, TimestampMixin


class OperatingStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


class BrandProcessOperatingRule(EffectiveDateMixin, TimestampMixin, Base):
    __tablename__ = "brand_process_operating_rules"
    __table_args__ = (
        CheckConstraint(
            "effective_end_date IS NULL OR effective_end_date >= effective_start_date",
            name="ck_operating_rule_valid_dates",
        ),
        CheckConstraint(
            "minimum_daily_staffing >= 0",
            name="ck_operating_rule_nonnegative_staffing",
        ),
        Index(
            "ix_operating_rule_context_period",
            "brand_id",
            "process_id",
            "effective_start_date",
            "effective_end_date",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    brand_id: Mapped[int] = mapped_column(
        ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    process_id: Mapped[int] = mapped_column(
        ForeignKey("processes.id", ondelete="CASCADE"), nullable=False
    )
    operating_weekdays: Mapped[str] = mapped_column(String(14), nullable=False)
    sunday_working: Mapped[bool] = mapped_column(Boolean, nullable=False)
    public_holiday_working: Mapped[bool] = mapped_column(Boolean, nullable=False)
    required_coverage: Mapped[bool] = mapped_column(Boolean, nullable=False)
    minimum_daily_staffing: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    brand: Mapped[Brand] = relationship(back_populates="operating_rules")
    process: Mapped[Process] = relationship(back_populates="operating_rules")


class BrandProcessDateOverride(TimestampMixin, Base):
    __tablename__ = "brand_process_date_overrides"
    __table_args__ = (
        CheckConstraint(
            "minimum_daily_staffing >= 0",
            name="ck_date_override_nonnegative_staffing",
        ),
        Index("ix_date_override_lookup", "brand_id", "process_id", "date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    brand_id: Mapped[int] = mapped_column(
        ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    process_id: Mapped[int] = mapped_column(
        ForeignKey("processes.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    operating_status: Mapped[OperatingStatus] = mapped_column(
        String(16), nullable=False
    )
    required_coverage: Mapped[bool] = mapped_column(Boolean, nullable=False)
    minimum_daily_staffing: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)

    brand: Mapped[Brand] = relationship(back_populates="date_overrides")
    process: Mapped[Process] = relationship(back_populates="date_overrides")


class BrandProcessWorkloadRule(EffectiveDateMixin, TimestampMixin, Base):
    __tablename__ = "brand_process_workload_rules"
    __table_args__ = (
        CheckConstraint(
            "effective_end_date IS NULL OR effective_end_date >= effective_start_date",
            name="ck_workload_rule_valid_dates",
        ),
        CheckConstraint("workload_units > 0", name="ck_workload_rule_positive_units"),
        Index(
            "ix_brand_process_workload_period",
            "brand_id",
            "process_id",
            "effective_start_date",
            "effective_end_date",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    brand_id: Mapped[int] = mapped_column(
        ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    process_id: Mapped[int] = mapped_column(
        ForeignKey("processes.id", ondelete="CASCADE"), nullable=False
    )
    workload_units: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    brand: Mapped[Brand] = relationship(back_populates="workload_rules")
    process: Mapped[Process] = relationship(back_populates="workload_rules")


class PublicHoliday(TimestampMixin, Base):
    __tablename__ = "public_holidays"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    scope: Mapped[str] = mapped_column(String(80), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
