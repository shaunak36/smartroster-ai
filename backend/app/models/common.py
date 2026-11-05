from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class EffectiveDateMixin:
    effective_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    effective_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class CapacityMixin:
    daily_capacity_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weekly_capacity_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    monthly_capacity_units: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_assignments_per_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
