from datetime import date
from typing import Any

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import Session


class EffectivePeriodOverlapError(ValueError):
    """Raised when an active effective-dated rule overlaps an existing rule."""


def ensure_no_effective_period_overlap(
    session: Session,
    model: Any,
    context_filters: dict[str, Any],
    effective_start_date: date,
    effective_end_date: date | None,
    exclude_id: int | None = None,
) -> None:
    if effective_end_date is not None and effective_end_date < effective_start_date:
        raise ValueError("effective_end_date must be on or after effective_start_date")

    overlap = and_(
        model.effective_start_date <= (effective_end_date or date.max),
        or_(
            model.effective_end_date.is_(None),
            model.effective_end_date >= effective_start_date,
        ),
    )
    conditions = [getattr(model, key) == value for key, value in context_filters.items()]
    conditions.append(model.is_active.is_(True))
    conditions.append(overlap)
    if exclude_id is not None:
        conditions.append(model.id != exclude_id)

    existing = session.scalar(select(model.id).where(*conditions).limit(1))
    if existing is not None:
        raise EffectivePeriodOverlapError(
            f"{model.__tablename__} has an overlapping active period for this context"
        )
