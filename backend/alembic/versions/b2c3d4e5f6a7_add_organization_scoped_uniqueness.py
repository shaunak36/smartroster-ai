"""add organization scoped uniqueness to rosters and public holidays

Revision ID: b2c3d4e5f6a7
Revises: 9a1b2c3d4e5f
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "9a1b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _replace_public_holiday_unique_constraint(
    bind, drop_name: str, create_name: str, columns: list[str]
) -> None:
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(
            "public_holidays",
            naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"},
        ) as batch_op:
            batch_op.drop_constraint(drop_name, type_="unique")
            batch_op.create_unique_constraint(create_name, columns)
        return

    op.drop_constraint(drop_name, "public_holidays", type_="unique")
    op.create_unique_constraint(create_name, "public_holidays", columns)


def _date_unique_constraint_name(bind) -> str:
    if bind.dialect.name == "sqlite":
        # SQLite reflects this UNIQUE constraint without a name.
        return "uq_public_holidays_date"

    constraints = [
        constraint
        for constraint in sa.inspect(bind).get_unique_constraints("public_holidays")
        if constraint["column_names"] == ["date"]
    ]
    if len(constraints) != 1 or not constraints[0]["name"]:
        raise RuntimeError(
            "Expected one named unique constraint on public_holidays.date"
        )
    return constraints[0]["name"]


def upgrade() -> None:
    # 1. Update rosters: replace uq_roster_period with composite (organization_id, year, month)
    with op.batch_alter_table("rosters") as batch_op:
        batch_op.drop_constraint("uq_roster_period", type_="unique")
        batch_op.create_unique_constraint(
            "uq_roster_org_period", ["organization_id", "year", "month"]
        )

    # 2. Update public_holidays: drop global unique on date, create composite (organization_id, date)
    _replace_public_holiday_unique_constraint(
        op.get_bind(),
        _date_unique_constraint_name(op.get_bind()),
        "uq_public_holiday_org_date",
        ["organization_id", "date"],
    )


def downgrade() -> None:
    _replace_public_holiday_unique_constraint(
        op.get_bind(),
        "uq_public_holiday_org_date",
        "uq_public_holidays_date",
        ["date"],
    )

    with op.batch_alter_table("rosters") as batch_op:
        batch_op.drop_constraint("uq_roster_org_period", type_="unique")
        batch_op.create_unique_constraint("uq_roster_period", ["year", "month"])
