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
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import TimestampMixin


class RosterStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    REVALIDATION_REQUIRED = "revalidation_required"
    ARCHIVED = "archived"


class SolverStatus(str, Enum):
    NOT_RUN = "not_run"
    OPTIMAL = "optimal"
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"
    UNKNOWN = "unknown"


class ValidationStatus(str, Enum):
    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"


class AssignmentSource(str, Enum):
    GENERATED = "generated"
    MANUAL = "manual"
    REPLACEMENT = "replacement"


class ConflictSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class Roster(TimestampMixin, Base):
    __tablename__ = "rosters"
    __table_args__ = (UniqueConstraint("year", "month", name="uq_roster_period"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[RosterStatus] = mapped_column(
        String(32), default=RosterStatus.DRAFT, nullable=False
    )
    current_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("roster_versions.id", ondelete="SET NULL"), nullable=True
    )

    versions: Mapped[list[RosterVersion]] = relationship(
        back_populates="roster",
        cascade="all, delete-orphan",
        foreign_keys="RosterVersion.roster_id",
    )
    current_version: Mapped[RosterVersion | None] = relationship(
        foreign_keys=[current_version_id], post_update=True
    )


class RosterVersion(TimestampMixin, Base):
    __tablename__ = "roster_versions"
    __table_args__ = (
        UniqueConstraint("roster_id", "version_number", name="uq_roster_version_number"),
        Index("ix_roster_version_status", "roster_id", "validation_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    roster_id: Mapped[int] = mapped_column(
        ForeignKey("rosters.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("roster_versions.id", ondelete="SET NULL"), nullable=True
    )
    solver_status: Mapped[SolverStatus] = mapped_column(
        String(16), default=SolverStatus.NOT_RUN, nullable=False
    )
    validation_status: Mapped[ValidationStatus] = mapped_column(
        String(16), default=ValidationStatus.PENDING, nullable=False
    )
    objective_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revalidation_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    roster: Mapped[Roster] = relationship(
        back_populates="versions", foreign_keys=[roster_id]
    )
    source_version: Mapped[RosterVersion | None] = relationship(
        remote_side="RosterVersion.id"
    )
    assignments: Mapped[list[RosterAssignment]] = relationship(
        back_populates="roster_version", cascade="all, delete-orphan"
    )
    validation_runs: Mapped[list[ValidationRun]] = relationship(
        back_populates="roster_version", cascade="all, delete-orphan"
    )
    conflicts: Mapped[list[SchedulingConflict]] = relationship(
        back_populates="roster_version", cascade="all, delete-orphan"
    )
    changes: Mapped[list[RosterChangeHistory]] = relationship(
        back_populates="roster_version",
        cascade="all, delete-orphan",
        foreign_keys="RosterChangeHistory.roster_version_id",
    )


class RosterAssignment(TimestampMixin, Base):
    __tablename__ = "roster_assignments"
    __table_args__ = (
        UniqueConstraint(
            "roster_version_id",
            "date",
            "employee_id",
            "brand_id",
            "process_id",
            name="uq_roster_assignment",
        ),
        Index("ix_roster_assignment_date", "roster_version_id", "date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    roster_version_id: Mapped[int] = mapped_column(
        ForeignKey("roster_versions.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False
    )
    brand_id: Mapped[int] = mapped_column(
        ForeignKey("brands.id", ondelete="RESTRICT"), nullable=False
    )
    process_id: Mapped[int] = mapped_column(
        ForeignKey("processes.id", ondelete="RESTRICT"), nullable=False
    )
    workload_units: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[AssignmentSource] = mapped_column(
        String(16), default=AssignmentSource.GENERATED, nullable=False
    )
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    roster_version: Mapped[RosterVersion] = relationship(back_populates="assignments")
    employee: Mapped[Employee] = relationship(back_populates="roster_assignments")
    brand: Mapped[Brand] = relationship(back_populates="roster_assignments")
    process: Mapped[Process] = relationship(back_populates="roster_assignments")


class ValidationRun(TimestampMixin, Base):
    __tablename__ = "validation_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    roster_version_id: Mapped[int] = mapped_column(
        ForeignKey("roster_versions.id", ondelete="CASCADE"), nullable=False
    )
    trigger_type: Mapped[str] = mapped_column(String(80), nullable=False)
    affected_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    affected_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), nullable=True
    )
    affected_brand_id: Mapped[int | None] = mapped_column(
        ForeignKey("brands.id", ondelete="SET NULL"), nullable=True
    )
    affected_process_id: Mapped[int | None] = mapped_column(
        ForeignKey("processes.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[ValidationStatus] = mapped_column(
        String(16), default=ValidationStatus.PENDING, nullable=False
    )
    message: Mapped[str | None] = mapped_column(Text, nullable=True)

    roster_version: Mapped[RosterVersion] = relationship(back_populates="validation_runs")


class SchedulingConflict(TimestampMixin, Base):
    __tablename__ = "scheduling_conflicts"
    __table_args__ = (
        Index(
            "ix_scheduling_conflict_scope",
            "roster_version_id",
            "affected_date",
            "brand_id",
            "process_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    roster_version_id: Mapped[int] = mapped_column(
        ForeignKey("roster_versions.id", ondelete="CASCADE"), nullable=False
    )
    conflict_type: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[ConflictSeverity] = mapped_column(String(16), nullable=False)
    affected_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), nullable=True
    )
    brand_id: Mapped[int | None] = mapped_column(
        ForeignKey("brands.id", ondelete="SET NULL"), nullable=True
    )
    process_id: Mapped[int | None] = mapped_column(
        ForeignKey("processes.id", ondelete="SET NULL"), nullable=True
    )
    required_coverage: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    required_minimum_staffing: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assigned_staffing: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    roster_version: Mapped[RosterVersion] = relationship(back_populates="conflicts")


class RosterChangeHistory(TimestampMixin, Base):
    __tablename__ = "roster_change_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    roster_version_id: Mapped[int] = mapped_column(
        ForeignKey("roster_versions.id", ondelete="CASCADE"), nullable=False
    )
    previous_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("roster_versions.id", ondelete="SET NULL"), nullable=True
    )
    change_type: Mapped[str] = mapped_column(String(80), nullable=False)
    changed_date: Mapped[date] = mapped_column(Date, nullable=False)
    employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), nullable=True
    )
    brand_id: Mapped[int | None] = mapped_column(
        ForeignKey("brands.id", ondelete="SET NULL"), nullable=True
    )
    process_id: Mapped[int | None] = mapped_column(
        ForeignKey("processes.id", ondelete="SET NULL"), nullable=True
    )
    previous_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_status: Mapped[ValidationStatus] = mapped_column(
        String(16), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    changed_by: Mapped[str] = mapped_column(String(160), nullable=False)

    roster_version: Mapped[RosterVersion] = relationship(
        back_populates="changes", foreign_keys=[roster_version_id]
    )
    previous_version: Mapped[RosterVersion | None] = relationship(
        foreign_keys=[previous_version_id]
    )
    employee: Mapped[Employee | None] = relationship()
    brand: Mapped[Brand | None] = relationship()
    process: Mapped[Process | None] = relationship()
